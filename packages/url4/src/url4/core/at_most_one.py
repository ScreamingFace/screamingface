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
from url4.core.nodes import Expression, Params, RelExpr, RemoteExpr, Source

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
    """Refuse the mark on the expression side of a sugar-form ``;`` chain (§8.1.2).

    WHY: a chain that puts the mark before every source-level key, or carries none, would
    make the mark an expression parameter. An older reader reads it so; this reader never
    does, and refuses the chain instead.
    """
    if is_at_most_one(params):
        raise ParseError(
            f"{AT_MOST_ONE_KEY} on an expression-valued source must follow ;required or "
            ";optional, never be an expression parameter"
        )


def check_at_most_one(source: Source) -> None:
    """Refuse a marked source whose form breaks a C19 rule; raise ``malformed_source``.

    INVARIANT: a marked source is named, carries ``;expand`` and exactly one of
    ``;required`` / ``;optional``, holds the mark once as ``expand.at_most_one=true`` and,
    on an expression-valued source, has a source-level key before the mark. An unmarked
    source is never checked.
    """
    if not is_at_most_one(source.annotations):
        return
    problem = _first_broken_rule(source)
    if problem is not None:
        raise ParseError(f"invalid {AT_MOST_ONE_KEY} source: {problem}")


def _first_broken_rule(source: Source) -> str | None:
    keys = [key for key, _ in source.annotations]
    marks = [value for key, value in source.annotations if key == AT_MOST_ONE_KEY]
    rules = (
        (marks == [AT_MOST_ONE_VALUE], f"write the mark once, as {AT_MOST_ONE_KEY}=true"),
        (source.expand, "the source needs ;expand"),
        # WHY: an unnamed expansion calls its elements `src[i]`; there is no name to give.
        (source.name is not None, "the source needs a name"),
        (sum(key in _GUARDS for key in keys) == 1, "the source needs one of ;required/;optional"),
        (_after_a_source_key(source, keys), "the mark must follow a source-level key"),
    )
    return next((message for holds, message in rules if not holds), None)


def _after_a_source_key(source: Source, keys: list[str]) -> bool:
    """On an expression-valued source, a source-level key precedes the mark (§8.1.2)."""
    if not isinstance(source.value, _EXPR_VALUED):
        return True
    return any(is_source_level_key(key) for key in keys[: keys.index(AT_MOST_ONE_KEY)])
