"""Static ReDoS ban for regex@1 over the stdlib parse tree (OME-1289, E4a gap RX-D1).

FEATURE: a regex that can backtrack without bound is refused when the spec is checked.
STORY: as an operator of the Engine, a hostile pattern never reaches a worker's event loop.

Mental model: a customs officer reading the parse tree, not the pattern text. Three shapes are
turned away: a repeat inside an unbounded repeat, an alternation inside an unbounded repeat, and
two unbounded repeats side by side whose characters may overlap. Anything the officer does not
recognize is turned away too (fail closed).

INVARIANT: the module is pure; it holds no mutable state and imports only ``re`` and the stdlib.
WHY not a runtime timeout: a plugin cannot use threads or signals, and a stuck ``re`` call cannot
be interrupted.
AIDEV-NOTE: re._parser is private; ET/test_combine_regex.py pins its tree shape on 3.12 and 3.13.
The SDK (unit 4) mirrors this module with a conformance test.
AIDEV-NOTE: the ban is a tripwire, not a proof. A pattern such as ``[a-z]+[0-9]+`` is accepted
and costs O(n^2) on a 1024-character window (about 5 ms); a pattern with a bounded repeat of an
alternation is accepted too. A fourth shape needs a new ``@version``.
"""

from __future__ import annotations

import re
import re._parser as _sre  # type: ignore[import-not-found]
from collections.abc import Callable, Iterator, Sequence
from types import MappingProxyType
from typing import Any

SHAPES = (
    "unsupported_construct",
    "nested_quantifier",
    "quantified_alternation",
    "adjacent_overlap",
)

# An item of the parse tree is (opcode, argument); the argument's type depends on the opcode.
_Item = tuple[Any, Any]
_Seq = Sequence[_Item]

_REPEATS = frozenset({"MAX_REPEAT", "MIN_REPEAT", "POSSESSIVE_REPEAT"})
_GROUPS = frozenset({"SUBPATTERN", "ATOMIC_GROUP"})
_ALTERNATIONS = frozenset({"BRANCH", "GROUPREF_EXISTS"})
_ZERO_WIDTH = frozenset({"AT", "ASSERT", "ASSERT_NOT", "GROUPREF"})
_LEAVES = frozenset({"LITERAL", "NOT_LITERAL", "ANY", "IN", "AT", "GROUPREF"})
_CLASS_ATOMS = frozenset({"LITERAL", "NOT_LITERAL", "IN"})
_SMALL_SET_MAX = 128

_CATEGORY_SOURCE = MappingProxyType(
    {
        "CATEGORY_DIGIT": r"\d",
        "CATEGORY_NOT_DIGIT": r"\D",
        "CATEGORY_SPACE": r"\s",
        "CATEGORY_NOT_SPACE": r"\S",
        "CATEGORY_WORD": r"\w",
        "CATEGORY_NOT_WORD": r"\W",
    }
)
# Pairs of one-category sets that share no code point (checked over all of Unicode by
# ET/test_combine_regex.py). Any other pair of non-small atoms is assumed to overlap (F6).
_DISJOINT = frozenset(
    {
        frozenset({"CATEGORY_DIGIT", "CATEGORY_NOT_DIGIT"}),
        frozenset({"CATEGORY_SPACE", "CATEGORY_NOT_SPACE"}),
        frozenset({"CATEGORY_WORD", "CATEGORY_NOT_WORD"}),
        frozenset({"CATEGORY_SPACE", "CATEGORY_WORD"}),
        frozenset({"CATEGORY_SPACE", "CATEGORY_DIGIT"}),
    }
)


# --- the tree ---------------------------------------------------------------------------------
# Child sequences of one item, by opcode name (the argument layouts are the stdlib parser's).
_CHILDREN: MappingProxyType[str, Callable[[Any], list[_Seq]]] = MappingProxyType(
    {
        "SUBPATTERN": lambda av: [av[3]],
        "ATOMIC_GROUP": lambda av: [av],
        "BRANCH": lambda av: list(av[1]),
        "MAX_REPEAT": lambda av: [av[2]],
        "MIN_REPEAT": lambda av: [av[2]],
        "POSSESSIVE_REPEAT": lambda av: [av[2]],
        "ASSERT": lambda av: [av[1]],
        "ASSERT_NOT": lambda av: [av[1]],
        "GROUPREF_EXISTS": lambda av: [av[1], *([] if av[2] is None else [av[2]])],
    }
)
_KNOWN = frozenset(_LEAVES | _CHILDREN.keys())


def _children(item: _Item) -> list[_Seq]:
    handler = _CHILDREN.get(item[0].name)
    return [] if handler is None else handler(item[1])


def _walk(items: _Seq) -> Iterator[_Item]:
    """Every item at any depth, parents before children, in author order."""
    for item in items:
        yield item
        for child in _children(item):
            yield from _walk(child)


def _sequences(items: _Seq) -> Iterator[_Seq]:
    """The sequence itself and every child sequence below it."""
    yield items
    for item in items:
        for child in _children(item):
            yield from _sequences(child)


def _is_repeat(item: _Item) -> bool:
    return bool(item[0].name in _REPEATS)


def _is_unbounded(item: _Item) -> bool:
    return _is_repeat(item) and bool(item[1][1] == _sre.MAXREPEAT)


# --- checks 1 to 3 ----------------------------------------------------------------------------


def _has_unsupported(tree: _Seq) -> bool:
    return any(item[0].name not in _KNOWN for item in _walk(tree))


def _unbounded_body_has(tree: _Seq, names: frozenset[str]) -> bool:
    """An unbounded repeat whose body holds, at any depth, an item named in ``names``."""
    return any(
        _is_unbounded(item) and any(inner[0].name in names for inner in _walk(_children(item)[0]))
        for item in _walk(tree)
    )


def _has_nested_quantifier(tree: _Seq) -> bool:
    return _unbounded_body_has(tree, _REPEATS)


def _has_quantified_alternation(tree: _Seq) -> bool:
    return _unbounded_body_has(tree, _ALTERNATIONS)


# --- check 4: adjacent unbounded repeats whose characters may overlap -------------------------


def _seq_nullable(items: _Seq) -> bool:
    return all(_nullable(item) for item in items)


_NULLABLE: MappingProxyType[str, Callable[[Any], bool]] = MappingProxyType(
    {
        **{name: (lambda av: True) for name in _ZERO_WIDTH},
        **{name: (lambda av: av[0] == 0 or _seq_nullable(av[2])) for name in _REPEATS},
        "BRANCH": lambda av: any(_seq_nullable(alt) for alt in av[1]),
        "SUBPATTERN": lambda av: _seq_nullable(av[3]),
        "ATOMIC_GROUP": lambda av: _seq_nullable(av),
        "GROUPREF_EXISTS": lambda av: _seq_nullable(av[1]) or av[2] is None or _seq_nullable(av[2]),
    }
)


def _nullable(item: _Item) -> bool:
    """True when the item can match the empty string (conservative: unknown means nullable)."""
    handler = _NULLABLE.get(item[0].name)
    return False if handler is None else bool(handler(item[1]))


def _flat(items: _Seq) -> list[_Item]:
    """The sequence with group bodies inlined, so ``(\\d*)\\d*`` reads as ``\\d*\\d*``."""
    flat: list[_Item] = []
    for item in items:
        if item[0].name in _GROUPS:
            flat.extend(_flat(_children(item)[0]))
        else:
            flat.append(item)
    return flat


def _leaves(item: _Item) -> list[_Item]:
    return [inner for inner in _walk([item]) if inner[0].name in _LEAVES]


def _chars(atom: _Item) -> str | None:
    """The characters of a small set (a literal, or a plain class of at most 128), else None."""
    op, av = atom[0].name, atom[1]
    if op == "LITERAL":
        return chr(av)
    if op != "IN" or any(part[0].name not in ("LITERAL", "RANGE") for part in av):
        return None
    chars = "".join(chr(part[1]) if part[0].name == "LITERAL" else _span(part[1]) for part in av)
    return chars if len(chars) <= _SMALL_SET_MAX else None


def _span(bounds: tuple[int, int]) -> str:
    low, high = bounds
    return "".join(map(chr, range(low, min(high, low + _SMALL_SET_MAX) + 1)))


def _variants(chars: str) -> set[str]:
    """Every character plus its single-character case variants."""
    found = set(chars)
    for char in chars:
        found.update(
            v for v in (char.lower(), char.upper(), char.swapcase(), char.casefold()) if len(v) == 1
        )
    return found


def _escaped(code: int) -> str:
    return re.escape(chr(code))


_IN_PART: MappingProxyType[str, Callable[[Any], str | None]] = MappingProxyType(
    {
        "NEGATE": lambda arg: "^",
        "LITERAL": lambda arg: _escaped(arg),
        "RANGE": lambda arg: _escaped(arg[0]) + "-" + _escaped(arg[1]),
        "CATEGORY": lambda arg: _CATEGORY_SOURCE.get(arg.name),
    }
)


def _in_part(part: _Item) -> str | None:
    handler = _IN_PART.get(part[0].name)
    return None if handler is None else handler(part[1])


def _leaf_source(atom: _Item) -> str | None:
    """A regex source that matches exactly the atom's characters; None for an unknown atom."""
    op, av = atom[0].name, atom[1]
    if op == "LITERAL":
        return _escaped(av)
    if op == "NOT_LITERAL":
        return "[^" + _escaped(av) + "]"
    parts = [_in_part(part) for part in av]
    known = [part for part in parts if part is not None]
    return "[" + "".join(known) + "]" if len(known) == len(parts) else None


def _hits(chars: str, other: _Item) -> bool:
    """True when some character of the small set (or a case variant) is in ``other``."""
    source = _leaf_source(other)
    if source is None:
        return True
    return any(re.fullmatch(source, char, re.IGNORECASE) for char in _variants(chars))


def _category(atom: _Item) -> str | None:
    """The category name of an atom that is exactly one ``\\d``, ``\\s`` or ``\\w`` class."""
    if atom[0].name == "IN" and len(atom[1]) == 1 and atom[1][0][0].name == "CATEGORY":
        return str(atom[1][0][1].name)
    return None


def _categories_overlap(first: _Item, second: _Item) -> bool:
    names = (_category(first), _category(second))
    return None in names or frozenset(names) not in _DISJOINT


def _atoms_overlap(first: _Item, second: _Item) -> bool:
    """Conservative: True unless the two atoms are proven to share no character."""
    if not (first[0].name in _CLASS_ATOMS and second[0].name in _CLASS_ATOMS):
        return True  # ANY, GROUPREF, AT: assume overlap
    small = (_chars(first), _chars(second))
    if small == (None, None):
        return _categories_overlap(first, second)
    return (small[0] is not None and _hits(small[0], second)) or (
        small[1] is not None and _hits(small[1], first)
    )


def _overlap(first: Sequence[_Item], second: Sequence[_Item]) -> bool:
    return any(_atoms_overlap(a, b) for a in first for b in second)


def _overlaps_later(flat: list[_Item], index: int) -> bool:
    """Does the unbounded repeat at ``index`` overlap a later one that only nullables separate?"""
    mine = _leaves(flat[index])
    for other in flat[index + 1 :]:
        if _is_unbounded(other) and _overlap(mine, _leaves(other)):
            return True
        if not _nullable(other):
            return False
    return False


def _has_adjacent_overlap(tree: _Seq) -> bool:
    for sequence in _sequences(tree):
        flat = _flat(sequence)
        if any(_is_unbounded(item) and _overlaps_later(flat, i) for i, item in enumerate(flat)):
            return True
    return False


# --- entry point ------------------------------------------------------------------------------

_CHECKS: tuple[tuple[str, Callable[[_Seq], bool]], ...] = (
    ("unsupported_construct", _has_unsupported),
    ("nested_quantifier", _has_nested_quantifier),
    ("quantified_alternation", _has_quantified_alternation),
    ("adjacent_overlap", _has_adjacent_overlap),
)


def backtracking_shape(pattern: str) -> str | None:
    """The first banned shape found in ``pattern`` (one of ``SHAPES``), or None when it is fine.

    The caller has already compiled ``pattern``, so the parse cannot fail on syntax.
    """
    tree: list[_Item] = _sre.parse(pattern, 0).data
    return next((shape for shape, found in _CHECKS if found(tree)), None)
