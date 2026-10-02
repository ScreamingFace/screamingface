"""Pre-spend check of a regex@1 pattern (OME-1289 gap RX-E1/E2, RE2 decision 2026-10-02).

The Engine runs regex@1 on RE2 (linear time) and its RE2 compile is AUTHORITATIVE: a pattern this
check accepts but RE2 rejects fails the Case with combine_spec_invalid at run time.
RE2 semantics: \\d and \\w are ASCII; use \\p{L} / \\p{N} for Unicode letters / digits.
WHY re._parser (private): the stdlib parse tree is the only dependency-free view of a pattern's
constructs; it is imported lazily, so `import screamingface` never depends on it.
INVARIANT: no message contains the pattern.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterator, Mapping
from types import MappingProxyType
from typing import Any

MAX_PATTERN_CHARS = 256
MAX_REPEAT_COUNT = 1000
REGEX_ARGS = frozenset({"pattern", "group", "occurrence", "ignore_case"})
_OCCURRENCES = ("last", "first")
_FLAG_TEXT = "an ASCII, LOCALE or VERBOSE flag"
_BAD_FLAGS = re.ASCII | re.LOCALE | re.VERBOSE


def check_regex(args: Mapping[str, object], label: str) -> None:
    """Refuse, before any spend, a regex@1 argument set the Engine would refuse."""

    if "pattern" not in args or not set(args) <= REGEX_ARGS:
        raise ValueError(
            f"{label} needs a pattern and takes only pattern, group, occurrence and ignore_case"
        )
    pattern = args["pattern"]
    if not isinstance(pattern, str):
        raise TypeError(f"{label} pattern must be text")
    if not 1 <= len(pattern) <= MAX_PATTERN_CHARS:
        raise ValueError(f"{label} pattern must be 1 to {MAX_PATTERN_CHARS} characters")
    ignore_case = args.get("ignore_case", False)
    if not isinstance(ignore_case, bool):
        raise TypeError(f"{label} ignore_case must be a bool")
    if args.get("occurrence", "last") not in _OCCURRENCES:
        raise ValueError(f"{label} occurrence must be 'last' or 'first'")
    compiled = _compile(pattern, ignore_case, label)
    if (shape := unsupported_construct(pattern)) is not None:
        raise ValueError(
            f"{label} pattern uses {shape}, which the Engine's RE2 regex engine does not support"
        )
    if not _group_exists(args.get("group", 0), compiled):
        raise ValueError(f"{label} group must name a group of the pattern")


def _compile(pattern: str, ignore_case: bool, label: str) -> re.Pattern[str]:
    try:
        return re.compile(_python_view(pattern), re.IGNORECASE if ignore_case else 0)
    except (re.error, OverflowError):
        # INVARIANT: not chained. A re.error message quotes the pattern.
        raise ValueError(f"{label} pattern does not compile") from None


def _group_exists(group: object, compiled: re.Pattern[str]) -> bool:
    if isinstance(group, str):
        return group in compiled.groupindex
    return isinstance(group, int) and not isinstance(group, bool) and 0 <= group <= compiled.groups


def _python_view(pattern: str) -> str:
    """The pattern as Python's `re` reads it: RE2's \\p{..} / \\P{..} become \\w (F15 carve-out).

    The group count never changes, so the group check is the same on both sides.
    """

    out: list[str] = []
    index = 0
    while index < len(pattern):
        pair = pattern[index : index + 2]
        if pair[1:] in {"p", "P"} and pair[0] == "\\":
            out.append("\\w")
            index = _after_property(pattern, index + 2)
        else:
            out.append(pair if pair[0] == "\\" else pair[0])
            index += len(out[-1])
    return "".join(out)


def _after_property(pattern: str, index: int) -> int:
    """The index after a \\p name: a {...} block up to its }, else one following character."""

    close = pattern.find("}", index) if pattern[index : index + 1] == "{" else -1
    return close + 1 if close >= 0 else index + 1


def unsupported_construct(pattern: str) -> str | None:
    """The first construct RE2 does not support (a name for messages), or None."""

    # WHY lazy and type-ignored: typeshed has no stub for the private parser, and only regex
    # users should depend on it.
    import re._parser as _sre  # type: ignore[import-not-found]

    parsed = _sre.parse(_python_view(pattern), 0)
    for opcode, value in _walk(parsed):
        found = _HITS.get(str(opcode))
        if found is not None and (text := found(value, _sre.MAXREPEAT)) is not None:
            return text
    return _FLAG_TEXT if parsed.state.flags & _BAD_FLAGS else None


def _walk(parsed: Any) -> Iterator[tuple[object, Any]]:
    """Every item at every depth, parents before their children."""

    for opcode, value in parsed:
        yield opcode, value
        for child in _children(str(opcode), value):
            yield from _walk(child)


def _children(opcode: str, value: Any) -> tuple[Any, ...]:
    pick = _CHILDREN.get(opcode)
    return () if pick is None else tuple(item for item in pick(value) if item is not None)


def _repeat_text(value: Any, unbounded: int) -> str | None:
    low, high = value[0], value[1]
    if low > MAX_REPEAT_COUNT or (high != unbounded and high > MAX_REPEAT_COUNT):
        return f"a repeat count over {MAX_REPEAT_COUNT}"
    return None


def _scoped_flag_text(value: Any, _unbounded: int) -> str | None:
    return _FLAG_TEXT if value[1] & _BAD_FLAGS else None


def _always(text: str) -> Callable[[Any, int], str | None]:
    return lambda _value, _unbounded: text


_HITS: Mapping[str, Callable[[Any, int], str | None]] = MappingProxyType(
    {
        "GROUPREF": _always("a backreference"),
        "ASSERT": _always("a lookaround"),
        "ASSERT_NOT": _always("a lookaround"),
        "GROUPREF_EXISTS": _always("a conditional group"),
        "ATOMIC_GROUP": _always("an atomic group"),
        "POSSESSIVE_REPEAT": _always("a possessive repeat"),
        "MAX_REPEAT": _repeat_text,
        "MIN_REPEAT": _repeat_text,
        "SUBPATTERN": _scoped_flag_text,
    }
)
_CHILDREN: Mapping[str, Callable[[Any], tuple[Any, ...]]] = MappingProxyType(
    {
        "SUBPATTERN": lambda value: (value[3],),
        "ATOMIC_GROUP": lambda value: (value,),
        "BRANCH": lambda value: tuple(value[1]),
        "MAX_REPEAT": lambda value: (value[2],),
        "MIN_REPEAT": lambda value: (value[2],),
        "POSSESSIVE_REPEAT": lambda value: (value[2],),
        "ASSERT": lambda value: (value[1],),
        "ASSERT_NOT": lambda value: (value[1],),
        "GROUPREF_EXISTS": lambda value: (value[1], value[2]),
    }
)


__all__: list[str] = []
