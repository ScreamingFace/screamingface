"""C19 in the url4 a run parses later: an iteration's row and reducer, a relative call's context.

FEATURE: Router Recipe extension, contract C19.

The parser keeps some url4 as raw text, and a run parses it later: an iteration's body and
intent once per row, its reducer at reduce time, a relative call's context when the call is
lowered (a source list, else prose) and, on the text path, a deferred group when it runs. A
malformed mark there surfaced after the collection fetch and the per-row calls, or never: a
skipped row, a prose context shipped outbound. :func:`check_target` parses each such text at the
entry, as the run will parse it, and refuses a C19 error there. Any other parse error keeps its
base behavior: the run meets it where it did before.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace

from url4.core.at_most_one import (
    AtMostOneFormError,
    check_tree,
    refuse_mark_as_param,
    refuse_too_deep,
)
from url4.core.descriptor_head import deferrable_group
from url4.core.errors import ParseError
from url4.core.grammar import parse as grammar_parse
from url4.core.grammar import parse_group_root
from url4.core.nodes import Iteration, Node, RelExpr
from url4.core.parser import build, split_directive_fields, split_intent, split_top_level_commas
from url4.dag.source_scan import holds_holdings_ref


def check_target(target: str | Node) -> None:
    """Refuse a C19 form anywhere a run of ``target`` parses url4; raise ``malformed_source``.

    INVARIANT: :func:`url4.dag.compile_expression` and :func:`url4.dag.run` call this first, so
    a C19 form is refused before any fetch or call, whether it sits in a tree node or in a text
    the run parses later. Text is read eagerly here, so a deferred group's sources are too. A
    remote call's context is the remote node's to parse (C6), and a relative reducer's context
    ships to its route with the rows: this node parses neither, and neither is read here.
    """
    tree = _lenient(build, target) if isinstance(target, str) else target
    if tree is not None:
        check_tree(tree, later=_later_trees)


def read_source_list[T](context: str | None, read: Callable[[str], T]) -> list[T] | None:
    """A relative call's context read as a source list, segment by segment; ``None`` for prose.

    INVARIANT (spec §5.6.3.1/.2): a holdings ref (``@``) in a call's context is scoped to the
    RECEIVING route, so such a context ships verbatim and is never read here; whether it holds
    one is the run-start scan's own predicate (OME-1945).

    INVARIANT (C19): a C19 error is never prose. A context whose every segment reads but for a
    C19 error is refused. A context with a segment that does not read for another reason is
    prose and ships verbatim, a mark written in it included, whatever the segments' order.
    WHY prose at all: the ABNF's source-list is the canonical reading, but a call's parens have
    carried free prose since v1.
    """
    if context is None or not context.strip() or _receiver_owned(context):
        return None
    sources: list[T] = []
    refused: AtMostOneFormError | None = None
    try:
        for segment in filter(None, (part.strip() for part in split_top_level_commas(context))):
            try:
                sources.append(read(segment))
            except AtMostOneFormError as error:
                refused = refused or error
    except ParseError:
        return None
    if refused is not None:
        raise refused
    return sources or None


def _receiver_owned(context: str) -> bool:
    """Whether ``context`` holds a holdings ref, the receiving route's to read (§5.6.3).

    INVARIANT (FAIL CLOSED): the holdings-ref reading parses each segment in order before the
    C19 reading, so a segment too deep for the eager parser that it met first escaped as a
    ``RecursionError``. One that names the mark is refused, as :func:`_read` refuses it; any
    other keeps its base error. A holdings ref ahead of it still makes the context the
    receiver's.
    """
    try:
        return holds_holdings_ref(context)
    except RecursionError:
        refuse_too_deep(context)
        raise


def _later_trees(node: Node) -> list[Node]:
    """The trees of the url4 ``node`` keeps as raw text, each parsed as the run parses it."""
    if isinstance(node, Iteration):
        reducer = None if node.reducer is None else _lenient(_reducer_tree, node.reducer)
        return [tree for tree in (*_row_trees(node), reducer) if tree is not None]
    if isinstance(node, RelExpr):
        members = read_source_list(node.context, _context_member) or []
        return [tree for tree in members if tree is not None]
    return []


def _context_member(segment: str) -> Node | None:
    """A call context's segment as lowering reads it (``_lowering._slot_from_text``).

    INVARIANT: a segment is a source, prose or a C19 refusal alike here and in lowering, as
    both ask :func:`~url4.core.descriptor_head.deferrable_group` first. A group the text path
    defers is a source whatever its sources hold: they are read here for a C19 error only, and
    any other error is the run's to meet when the group runs (``None``). WHY: read with the
    eager grammar, such a group made the context prose here and a source list in lowering.
    """
    deferred = deferrable_group(segment)
    if deferred is not None:
        return _lenient(build, deferred[2])
    return _read(grammar_parse, segment)


def _row_trees(node: Iteration) -> tuple[Node | None, ...]:
    """The row's body and its intent, each read alone as the row (`MapNode.fragment`) reads it.

    WHY apart: the row reads its intent's params before its body and its intent's call after
    it, so an error in one would hide a C19 error in the other. WHY an empty text as the
    intent's body: the grammar reads an intent the same whatever group precedes it.
    """
    body = _lenient(parse_group_root, f"({node.body})")
    return (body, _lenient(build, f"('')!{node.intent}")) if node.intent else (body,)


def _reducer_tree(reducer: str) -> Node:
    # WHY the `;` chain first: the text path splits a reducer's params off and refuses the mark
    # among them (`decode_envelope`) whatever its source side holds, which may fail on another
    # rule. WHY the source side as `ReduceNode` reads it: only that side is parsed, and a
    # relative reducer's context ships verbatim to its route, which parses it.
    refuse_mark_as_param(split_directive_fields(reducer)[1])
    tree = grammar_parse(split_intent(reducer)[0])
    return replace(tree, context=None) if isinstance(tree, RelExpr) else tree


def _lenient(parse: Callable[[str], Node], text: str) -> Node | None:
    """``parse(text)``, or ``None`` when it fails on anything but a C19 rule."""
    try:
        return _read(parse, text)
    except AtMostOneFormError:
        raise
    except ParseError:
        return None  # WHY: not C19's to refuse; the run meets this error where it did before


def _read(parse: Callable[[str], Node], text: str) -> Node:
    """``parse(text)``; a text too deep for the eager parser raises a parse error instead.

    WHY: the run compiles a deep group lazily, so such a text compiled before this check.
    One that names the mark is refused (:func:`~url4.core.at_most_one.refuse_too_deep`); any
    other is not C19's to refuse.
    """
    try:
        return parse(text)
    except RecursionError:
        refuse_too_deep(text)
        raise ParseError("nested too deeply for the eager parser") from None
