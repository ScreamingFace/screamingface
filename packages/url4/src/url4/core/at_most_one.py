"""The ``expand.at_most_one=true`` package extension: its key and its form (contract C19).

FEATURE: Router Recipe extension, contract C19 — a named ``;expand`` source bounded to zero
or one element, so a Fusion member slot can be absent without failing and, when present,
keeps its own name.

The mark is a generic execution key (Spec B §4.2 ``exec-key=value``), outside the closed
``coord.`` set and the §8.1.3 exclusive source keys, so every reader accepts it and an older
one ignores it (Spec C §10.2). This module is the one owner of its form: the parser
(:mod:`url4.core.grammar`), the DAG text path (:mod:`url4.core.descriptor_head`),
:func:`url4.src` and the renderer all call it, so none accepts what another refuses.
"""

from __future__ import annotations

from url4.core._annotations import is_source_level_key
from url4.core.errors import ParseError
from url4.core.nodes import Expression, Node, Params, RelExpr, RemoteExpr, Source

AT_MOST_ONE_KEY = "expand.at_most_one"
"""The mark's key. Renaming it after release would be a wire migration."""

AT_MOST_ONE_VALUE = "true"
"""The mark's only accepted value."""

_GUARDS = frozenset({"required", "optional"})
_EXPR_VALUED = (RelExpr, RemoteExpr, Expression)


def is_at_most_one(annotations: Params) -> bool:
    """True when a source's execution chain carries the mark, in any form."""
    return any(key == AT_MOST_ONE_KEY for key, _ in annotations)


def refuse_mark_as_param(params: Params) -> None:
    """Refuse the mark among an expression's ``;`` params.

    The grammar calls this on the expression side of a sugar-form chain (§8.1.2) and the
    envelope decoder on a complete group or iteration envelope.

    WHY: a chain that puts the mark before every source-level key, or carries none, would
    make the mark an expression parameter. An older reader reads it so, as a no-op; this
    reader never does, and refuses the text instead.
    """
    if is_at_most_one(params):
        raise ParseError(
            f"{AT_MOST_ONE_KEY} is a source execution key, never an expression parameter; "
            "on an expression-valued source it must follow ;required or ;optional"
        )


def with_mark(annotations: Params) -> Params:
    """The chain with the mark inserted right after its first guard, or appended without one.

    WHY: :func:`url4.src` writes the mark right after the guard whichever argument gave the
    guard, so on an expression-valued source a source-level key precedes the mark (§8.1.2).
    A chain with no guard or two still gets the mark; :func:`check_at_most_one` then refuses
    it with the rule it breaks.
    """
    keys = [key for key, _ in annotations]
    at = next((i + 1 for i, key in enumerate(keys) if key in _GUARDS), len(keys))
    return (*annotations[:at], (AT_MOST_ONE_KEY, AT_MOST_ONE_VALUE), *annotations[at:])


def check_at_most_one(source: Source) -> None:
    """Refuse a marked source whose form breaks a C19 rule; raise ``malformed_source``.

    INVARIANT: a marked source is named, carries ``;expand`` and exactly one of
    ``;required`` / ``;optional`` as a flag, holds the mark once as ``expand.at_most_one=true`` and,
    on an expression-valued source, has a source-level key before the mark. An unmarked
    source is never checked.
    """
    if not is_at_most_one(source.annotations):
        return
    problem = _first_broken_rule(source)
    if problem is not None:
        raise ParseError(f"invalid {AT_MOST_ONE_KEY} source: {problem}")


def checked_form(node: Node) -> Node:
    """Return a parsed source once :func:`check_at_most_one` passes; a non-Source passes as is.

    WHY the parser calls this on a whole parsed source, not inside descriptor parsing: the
    form needs ``;expand``, which a ``*`` prefix sets only once the whole source is parsed.
    """
    if isinstance(node, Source):
        check_at_most_one(node)
    return node


def _first_broken_rule(source: Source) -> str | None:
    keys = [key for key, _ in source.annotations]
    marks = [value for key, value in source.annotations if key == AT_MOST_ONE_KEY]
    guards = [value for key, value in source.annotations if key in _GUARDS]
    rules = (
        (marks == [AT_MOST_ONE_VALUE], f"write the mark once, as {AT_MOST_ONE_KEY}=true"),
        (source.expand, "the source needs ;expand"),
        # WHY: an unnamed expansion calls its elements `src[i]`; there is no name to give.
        (source.name is not None, "the source needs a name"),
        (len(guards) == 1, "the source needs one of ;required/;optional"),
        # WHY: the runtime reads a guard by its key alone, so `;optional=false` would act
        # as `;optional` and swallow the two-plus failure.
        (guards == [None], "write ;required or ;optional as a flag, without a value"),
        (_after_a_source_key(source, keys), "the mark must follow a source-level key"),
    )
    return next((message for holds, message in rules if not holds), None)


def _after_a_source_key(source: Source, keys: list[str]) -> bool:
    """On an expression-valued source, a source-level key precedes the mark (§8.1.2)."""
    if not isinstance(source.value, _EXPR_VALUED):
        return True
    return any(is_source_level_key(key) for key in keys[: keys.index(AT_MOST_ONE_KEY)])
