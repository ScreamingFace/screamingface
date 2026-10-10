"""The Parser facade + the string-level envelope decoders around the grammar.

Two layers live here:

1. :class:`Parser` — the public facade over the grammar. ``build(text)``
   splits the top-level intent, decodes the trailing ``;`` expression params,
   parses the source group, and returns a single unified
   :class:`~url4.core.nodes.Expression` (or :class:`~url4.core.nodes.Iteration`) root.
   ``walk(node)`` traverses it.

2. String decoders (:func:`split_intent`, :func:`split_expr_params`,
   :func:`split_collection_iteration`, :func:`split_top_level_commas`) —
   depth/quote-aware scans that peel off the parts of the surface envelope
   handled above the source grammar: the outermost ``!``/``!*`` split, the
   ``;key=val`` per-expression protocol parameters (spec §9.2, including the
   ``iteration.*`` directives of §5.3.6 and the ``;broadcast`` flag of §6.1),
   and the ``src*(body)`` iteration shape. They live in
   :mod:`url4.core._splitters` and are re-exported here. The DAG compiler
   reuses them directly (in this exact order), which is what keeps its surface
   semantics identical to ``build``'s.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field

from url4.core._annotations import validate_params
from url4.core._iteration_envelope import (
    IterationEnvelope,
    _decode_iteration,
    _merge_directives,
    check_iteration_envelope,
)
from url4.core._lexical import _SCHEME_RE, check_tail_url_intent
from url4.core._scan import balanced_body
from url4.core._splitters import (
    split_collection_iteration,
    split_envelope_intent,
    split_expr_params,
    split_foreach_annotations,
    split_intent,
    split_top_level_commas,
    strip_one_paren_layer,
)
from url4.core.errors import ErrorCode, ParseError
from url4.core.grammar import intent_atom, parse_group_root
from url4.core.nodes import (
    Expression,
    ForeachDirectives,
    Iteration,
    IterationDirectives,
    Node,
    Params,
)
from url4.core.nodes import walk as _walk


def assemble_expression(
    source_expr: str, raw_intent: str | None, broadcast: bool, params: Params = ()
) -> Expression:
    """Parse a source group and wrap it into a unified :class:`Expression` root.

    Parses ``source_expr`` via the grammar's ``parse_group_root`` — the caller
    holds the ``split_intent`` result, so the source side legally arrives as a
    bare ``(…)`` — unwraps that group so both ``(a, b)`` and a single source
    ``x`` yield flat ``sources``, and attaches the classified intent.
    """
    parsed = parse_group_root(source_expr) if source_expr else Expression(sources=())
    if isinstance(parsed, Expression) and parsed.intent is None:
        sources = parsed.sources
        params = parsed.params + params
    else:
        sources = (parsed,)
    intent = intent_atom(raw_intent) if raw_intent is not None else None
    return Expression(sources=sources, intent=intent, broadcast=broadcast, params=params)


def _collection_node(source: str) -> Node:
    """Parse an iteration's collection source into a resolvable node.

    A bare paren-collection is legal in this position (`paren-collection` is
    its own intent-less production), so this goes through ``parse_group_root``.
    """
    return parse_group_root(source) if source else Expression(sources=())


@dataclass(frozen=True)
class GroupEnvelope:
    """A decoded non-iteration expression: the raw source group, its top-level
    ``intent`` (``None`` for a bare group), the ``!*`` ``broadcast`` flag, and
    the remaining per-expression protocol ``params`` (spec §9.2)."""

    source_expr: str
    intent: str | None
    broadcast: bool
    params: Params = field(default=())


Envelope = IterationEnvelope | GroupEnvelope


def decode_envelope(text: str, *, require_intent: bool = True) -> Envelope:
    """Peel the surface envelope the source grammar sits under, as raw text.

    Runs the string scanners in the fixed order — a depth-0 ``*(body)`` bound
    FIRST, then the top-level ``!intent`` split, trailing ``;`` expression
    params (both sides of the ``!``), the ``(src*(body)[!peri])!reducer``
    reduce-over-iteration shape, then the plain ``src*(body)`` iteration — and
    classifies the result. ``require_intent`` enforces the grammar's mandatory
    ``intent-op intent`` (`OME-508`); the executor's spawn boundary passes
    False, because the engine's OWN wrappers (a map row's ``(body)``, a wire
    ``(context)`` whose intent travels separately) legally arrive intent-less.
    This is the single source of truth for that ordering:
    both the eager parse tree (:func:`build`) and the lazy DAG
    (:mod:`url4.dag.compiler`) interpret this same decode, so their surface
    semantics can never drift.

    # INVARIANT: a depth-0 ``*(`` binds tighter than the top-level ``!`` split.
    # A collection may carry its OWN mandatory intent (``uri-collection-ref``
    # admits local/relative/remote expressions), so in ``(a)!y*('b')!x`` the
    # first depth-0 ``!`` belongs to the COLLECTION, not to the envelope.
    # Splitting on it first silently destroyed the iteration — the bug this
    # ordering exists to prevent (`OME-501`). ``grammar.parse_value`` has always
    # scanned for ``*(`` unconditionally; this keeps the two entry points in
    # agreement.
    """
    stripped = text.strip()
    source_expr, raw_intent, broadcast = split_envelope_intent(stripped)
    source_expr, src_params, src_directives = _split_source_side(source_expr)
    params: Params = src_params
    directives = src_directives
    if raw_intent is not None:
        raw_intent, tail_params, tail_directives = split_expr_params(raw_intent)
        params += tail_params
        directives = _merge_directives(directives, tail_directives)
    broadcast = broadcast or any(key == "broadcast" for key, _ in params)
    params = tuple(pair for pair in params if pair[0] != "broadcast")
    # `expr-param = param-key "=" param-value` — the SAME two productions the
    # query sites use, so one validator serves all three (`OME-507`). It runs
    # here, on the resolved expression params, rather than inside
    # `split_expr_params`: at split time `_split_source_side` has not yet
    # decided which `;` pairs are expression-level and which are a bare
    # source's own exec chain (whose keys obey a different rule, `OME-504`).
    validate_params(params)

    envelope = _decode_iteration(source_expr, raw_intent, directives)
    if envelope is not None:
        check_iteration_envelope(envelope, stripped, require_intent)
        return envelope
    _check_group_envelope(source_expr, raw_intent, stripped, require_intent)
    return GroupEnvelope(source_expr, raw_intent, broadcast, params)


def _check_group_envelope(
    source_expr: str, raw_intent: str | None, stripped: str, require_intent: bool
) -> None:
    if raw_intent is not None and source_expr.lstrip().startswith("*("):
        # B2 / F4: "*(...)" at top level. The "!" belongs to the outer expression,
        # so the group after "*" has no intent of its own.
        raise ParseError(
            f"a leading '*' expands a source inside a group; at top level the '!' "
            f"belongs to the outer expression in {stripped!r}",
            code=ErrorCode.MISSING_INTENT,
        )
    if raw_intent is not None and _SCHEME_RE.match(raw_intent.strip()):
        check_tail_url_intent(raw_intent.strip())
    if require_intent and raw_intent is None and strip_one_paren_layer(source_expr) is not None:
        # INVARIANT: expression = "(" source-list ")" intent-op intent — a
        # parenthesized envelope with no intent has no grammar form (`OME-508`).
        # This decode is shared by build() and the DAG text path, so both
        # entries reject identically.
        raise ParseError(
            f"expression group {stripped!r} has no intent — a parenthesized "
            "source group must be followed by !intent (or !*intent)",
            code=ErrorCode.MISSING_INTENT,
        )


def _split_source_side(source_expr: str) -> tuple[str, Params, IterationDirectives]:
    """Strip a trailing ``;`` chain from the source side — but only when it
    belongs to the envelope (an iteration or a parenthesized group).

    A bare single source's ``;`` chain (``https://x;required``) is that
    *source's* execution chain and must reach the grammar intact (§4.2);
    stripping it here would silently re-scope per-source annotations to the
    expression.
    """
    clean, params, directives = split_expr_params(source_expr)
    if clean == source_expr.strip():
        return clean, params, directives
    is_iteration = split_collection_iteration(clean) != (None, None)
    if is_iteration or clean.startswith("("):
        return clean, params, directives
    return source_expr.strip(), (), IterationDirectives()


def build(text: str) -> Node:
    """Parse a full url4 expression into its (eager) AST root.

    Decodes the surface envelope (:func:`decode_envelope`) — the top-level
    ``!intent``, the ``;`` expression params, and the ``src*(body)`` iteration
    syntax — and eagerly parses the rest into a single parse-tree root: an
    :class:`~url4.core.nodes.Iteration` for the iteration forms, an
    :class:`~url4.core.nodes.Expression` otherwise. The DAG compiler accepts either
    surface text or this tree (see :func:`url4.dag.compile_expression`).
    """
    env = decode_envelope(text)
    if isinstance(env, IterationEnvelope):
        return Iteration(
            collection=_collection_node(env.collection),
            body=env.body,
            intent=env.intent,
            reducer=env.reducer,
            directives=env.directives,
        )
    return assemble_expression(env.source_expr, env.intent, env.broadcast, env.params)


def walk(node: Node) -> Iterator[Node]:
    """Yield ``node`` and every descendant in preorder. See :func:`url4.core.nodes.walk`."""
    yield from _walk(node)


class Parser:
    """Facade over the url4 grammar. Stateless; safe to reuse or re-instantiate."""

    def build(self, text: str) -> Node:
        """Parse ``text`` into its AST root (an :class:`~url4.core.nodes.Expression`
        or, for the ``src*(body)`` forms, an :class:`~url4.core.nodes.Iteration`)."""
        return build(text)

    def walk(self, node: Node) -> Iterator[Node]:
        """Yield ``node`` and all descendants in preorder."""
        yield from _walk(node)


__all__ = [
    "Envelope",
    "ForeachDirectives",
    "GroupEnvelope",
    "IterationDirectives",
    "IterationEnvelope",
    "Parser",
    "assemble_expression",
    "balanced_body",
    "build",
    "decode_envelope",
    "intent_atom",
    "split_collection_iteration",
    "split_expr_params",
    "split_foreach_annotations",
    "split_intent",
    "split_top_level_commas",
    "strip_one_paren_layer",
    "walk",
]
