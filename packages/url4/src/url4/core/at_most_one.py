"""The ``expand.at_most_one=true`` package extension: its key and its form (contract C19).

FEATURE: Router Recipe extension, contract C19 — a named ``;expand`` source bounded to zero
or one element, so a Fusion member slot can be absent without failing and, when present,
keeps its own name.

The mark is a generic execution key (Spec B §4.2 ``exec-key=value``), outside the closed
``coord.`` set and the §8.1.3 exclusive source keys, so every reader accepts it and an older
one ignores it (Spec C §10.2). This module is the one owner of its form: the parser
(:mod:`url4.core.grammar`, which the DAG text path parses through), the tree path
(:func:`check_tree`), :func:`url4.src` and the renderer all call it, so none accepts what
another refuses. The rule that the mark is never an expression param belongs to the param
validator (:func:`url4.core._annotations.validate_param`), shared by text, render and the
HTTP query; a tree built in code skips that validator, so :func:`check_tree` applies it.
Every C19 refusal raises :class:`AtMostOneFormError`, a ``ParseError`` no lenient reader
may swallow.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable

from url4.core._annotations import (
    AT_MOST_ONE_KEY,
    MARK_AS_PARAM,
    AtMostOneFormError,
    c19_refuses,
    is_source_level_key,
)
from url4.core._annotations import c19_blind as c19_blind  # WHY: public for the DAG layer
from url4.core._lexical import _IDENT_RE
from url4.core.errors import ParseError
from url4.core.nodes import Expression, Node, Params, RelExpr, RemoteExpr, Source, children

AT_MOST_ONE_VALUE = "true"
"""The mark's only accepted value."""

_GUARDS = frozenset({"required", "optional"})
_EXPR_VALUED = (RelExpr, RemoteExpr, Expression)


def is_at_most_one(annotations: Params) -> bool:
    """True when a source's execution chain carries the mark, in any form."""
    return any(key == AT_MOST_ONE_KEY for key, _ in annotations)


def keeps_valued_expand(annotations: Params) -> bool:
    """True when the grammar keeps a valued ``;expand`` in a source's chain, for C19 to refuse.

    WHY: the grammar reads ``;expand`` by its key alone and drops it, so ``;expand=false``
    expands, and the mark would bound a collection its author wrote as not expanded. On a
    marked source it stays in the chain and :func:`check_at_most_one` refuses it; an unmarked
    source keeps its base reading.
    """
    return c19_refuses() and is_at_most_one(annotations)


def raise_if_c19(error: ParseError) -> None:
    """Re-raise ``error`` when a C19 rule raised it, so a lenient reader falls back on no other.

    INVARIANT (C19): a reader that turns a parse error into prose, a code pointer or a
    reference (an intent, the intent classifier) never turns a C19 error into one: the text
    parsed as url4 up to a broken mark. WHY: a C19 error is a ``ParseError``, which those
    fallbacks catch, so the intent once reached the model as a prompt.
    """
    if isinstance(error, AtMostOneFormError):
        raise error


def refuse_mark_as_param(params: Params) -> None:
    """Refuse the mark among params that never reach the param validator.

    The validator refuses the mark wherever it runs. Two readers skip it: the iteration
    decoder, which keeps only the ``iteration.*`` directives of a reduce over iteration's
    inner tail, and :func:`check_tree`, for params built in code. Both call this.

    WHY: an older reader reads such a mark as an expression parameter, a no-op; this reader
    never does, and refuses it instead of dropping it without a word.
    """
    if c19_refuses() and is_at_most_one(params):
        raise AtMostOneFormError(MARK_AS_PARAM)


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

    INVARIANT: a marked source has a source name (an identifier other than the reserved
    ``src``, §4.3), carries ``;expand`` and exactly one of
    ``;required`` / ``;optional`` as a flag, holds the mark once as ``expand.at_most_one=true`` and,
    on an expression-valued source, has a source-level key before the mark. An unmarked
    source is never checked.
    """
    if not c19_refuses() or not is_at_most_one(source.annotations):
        return
    problem = _first_broken_rule(source)
    if problem is not None:
        raise AtMostOneFormError(f"invalid {AT_MOST_ONE_KEY} source: {problem}")


def checked_form(node: Node) -> Node:
    """Return a parsed source once :func:`check_at_most_one` passes; a non-Source passes as is.

    WHY the parser calls this on a whole parsed source, not inside descriptor parsing: the
    form needs ``;expand``, which a ``*`` prefix sets only once the whole source is parsed.
    """
    if isinstance(node, Source):
        check_at_most_one(node)
    return node


def checked_members(parts: Iterable[str], parse: Callable[[str], Node]) -> tuple[Node, ...]:
    """A group's members, each parsed and form-checked (:func:`checked_form`), all read first.

    INVARIANT: among one group's members a C19 error outranks any other, so a member that
    breaks another rule never hides another member's malformed mark; a nested group is read
    the same way. Without a C19 error the first error is raised, as before. WHY: a skipped or
    collected iteration row failed on its first error alone, and the mark after it vanished.
    A member that breaks another rule in its own chain or intent is not read further: C19 is
    not a full validator.
    """
    members: list[Node] = []
    first: ParseError | None = None
    for part in parts:
        try:
            members.append(checked_form(parse(part)))
        except AtMostOneFormError:
            raise
        except ParseError as error:
            first = first or error
        except RecursionError:
            if first is None:
                raise  # WHY: as before; read only to find a C19 error, it must not raise this
            refuse_too_deep(part)
    if first is not None:
        raise first
    return tuple(members)


def refuse_too_deep(text: str) -> None:
    """Refuse a url4 text too deep for the eager parser when it names the mark (FAIL CLOSED).

    WHY: its form cannot be read, so a mark in it cannot be checked. A text that names the mark
    nowhere has no C19 form to check and keeps its base behavior. As in the remote-call
    precheck (``url4.dag._remote_walk``), only a text too deep to parse is read as characters:
    a mark in quoted prose there is refused too.

    INVARIANT: the public eager readers (``parse``, ``parse_value``, :func:`url4.build`,
    :func:`url4.core.intent.classify_intent`) call this in an ``except RecursionError`` of their
    own frame and re-raise. WHY not through a wrapper: the parser re-enters none of them, so the
    refusal runs once the stack has unwound; a wrapper frame would cost every read its depth, and
    an unmarked text near the limit that base read would fail. So does every other caller that
    reads a given text as an intent: the builders' intent and reducer, ``is_named_job`` and the
    renderer reading a structured intent back.
    """
    if c19_refuses() and AT_MOST_ONE_KEY in text:
        raise AtMostOneFormError(
            f"the expression is nested too deeply to check its {AT_MOST_ONE_KEY} mark "
            "before it runs"
        )


def check_tree(tree: Node, later: Callable[[Node], Iterable[Node]] = lambda _: ()) -> None:
    """Refuse a tree that breaks a C19 rule; raise ``malformed_source``.

    INVARIANT: ``run(tree)`` enforces the same C19 marked-source and reserved-param constraints
    as ``run(text)``, before any fetch or call. A tree skips the parser, so
    :func:`url4.dag.compile_expression` and the run-start file phase of :func:`url4.dag.run`
    call this first: every source's form and every expression's, relative call's and remote
    call's params. It is not a full validator of a tree built in code; outside C19 such a tree
    keeps the base behavior. WHY one walk over every node, not a check per lowering: an inline
    collection is lowered as a list, not as an expression, and a check per lowering missed it.

    ``later`` gives the trees of the url4 a node keeps as raw text for the run to parse later
    (an iteration's row, a call's context); they join the same walk. This module parses no
    text, so the caller that knows how the run reads it supplies them.
    """
    stack = [tree]
    while stack:  # WHY a stack: a tree deep enough to exhaust recursion still gets checked
        node = stack.pop()
        if isinstance(node, Source):
            check_at_most_one(node)
        elif isinstance(node, _EXPR_VALUED):
            refuse_mark_as_param(node.params)
        stack.extend(later(node))
        stack.extend(reversed(children(node)))


def _first_broken_rule(source: Source) -> str | None:
    keys = [key for key, _ in source.annotations]
    marks = [value for key, value in source.annotations if key == AT_MOST_ONE_KEY]
    guards = [value for key, value in source.annotations if key in _GUARDS]
    rules = (
        (marks == [AT_MOST_ONE_VALUE], f"write the mark once, as {AT_MOST_ONE_KEY}=true"),
        (source.expand, "the source needs ;expand"),
        # WHY: the grammar reads `;expand` by its key alone, so `;expand=false` expands.
        (_expand_is_a_flag(source), "write ;expand as a flag, without a value"),
        # WHY: an unnamed expansion calls its elements `src[i]`; there is no name to give. A
        # tree may hold a name no text or url4.src could write: empty, reserved or not an ident.
        (_is_source_name(source.name), "the source needs a name: an identifier other than src"),
        (len(guards) == 1, "the source needs one of ;required/;optional"),
        # WHY: the runtime reads a guard by its key alone, so `;optional=false` would act
        # as `;optional` and swallow the two-plus failure.
        (guards == [None], "write ;required or ;optional as a flag, without a value"),
        (_after_a_source_key(source, keys), "the mark must follow a source-level key"),
    )
    return next((message for holds, message in rules if not holds), None)


def _is_source_name(name: object) -> bool:
    """A name the text form and :func:`url4.src` accept (§4.3): an identifier, never ``src``."""
    return isinstance(name, str) and name != "src" and _IDENT_RE.fullmatch(name) is not None


def _expand_is_a_flag(source: Source) -> bool:
    """No ``;expand`` with a value: the grammar keeps one on a marked source for this rule."""
    return all(value is None for key, value in source.annotations if key == "expand")


def _after_a_source_key(source: Source, keys: list[str]) -> bool:
    """On an expression-valued source, a source-level key precedes the mark (§8.1.2)."""
    if not isinstance(source.value, _EXPR_VALUED):
        return True
    return any(is_source_level_key(key) for key in keys[: keys.index(AT_MOST_ONE_KEY)])
