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
   and the ``src*(body)`` iteration shape. The DAG compiler reuses these
   directly (in this exact order), which is what keeps its surface semantics
   identical to ``build``'s.
"""

from __future__ import annotations

import re
import warnings
from collections.abc import Iterator
from dataclasses import dataclass, field

from url4.core._annotations import extract_directives, split_annotation_pairs, validate_params
from url4.core._scan import (
    balanced_body,
    find_unquoted,
    iter_iteration_stars,
    one_paren_layer,
)
from url4.core._scan import iter_top_level as _iter_top_level
from url4.core._scan import split_top_level as _split_top_level
from url4.core.errors import ErrorCode, ParseError
from url4.core.grammar import intent_atom, parse, parse_group_root
from url4.core.nodes import (
    Binding,
    Expression,
    ForeachDirectives,
    Iteration,
    IterationDirectives,
    Node,
    Params,
    Source,
)
from url4.core.nodes import walk as _walk

# The `path` production (§8): "/" segment *( "/" segment ), segment charset
# ALPHA / DIGIT / "-" / "_" / "." / "~". Anchored ASCII, like every other
# grammar pattern (`OME-504`).
_CALL_PATH_RE = re.compile(r"(?:/[A-Za-z0-9\-_.~]*)+", re.ASCII)


def split_intent(expr: str) -> tuple[str, str | None, bool]:
    """Split ``expr`` on the outermost ``!`` / ``!*`` (outside nesting/quotes).

    Returns ``(source_expression, intent, broadcast)``. ``broadcast`` is True
    for the ``!*`` operator (apply intent per source). A ``!`` immediately
    preceded by ``()`` belongs to a relative expression's intent tail
    (``/path()!``) and is skipped.
    """
    for i, ch in _iter_top_level(expr):
        if ch == "!" and not _is_backend_call_tail(expr, i):
            if i + 1 < len(expr) and expr[i + 1] == "*":
                return expr[:i], expr[i + 2 :], True
            return expr[:i], expr[i + 1 :], False
    return expr, None, False


def _is_backend_call_tail(expr: str, bang: int) -> bool:
    """True if the ``!`` at ``bang`` closes a leading relative/remote CALL.

    ``/path(ctx)!intent`` and ``url4://node/path(ctx)!intent`` are single call
    tokens: every call production carries its own ``intent-op intent``
    (`OME-508`), so that ``!`` belongs to the CALL, not to an enclosing
    envelope. Splitting it off produced a ``RelExpr(intent=None)`` that the
    grammar cannot derive and the renderer cannot emit — and left the text path
    disagreeing with ``grammar.parse``, which has always read the whole token
    as one RelExpr (the disagreement ``_fold_intent_into_call`` exists to undo).

    The discriminator: the FIRST depth-0 ``(`` closes immediately before the
    ``!``, and everything before it is a call target (``/path`` or
    ``url4://authority/path``). So ``()!intent`` (empty source list) and
    ``src*()!intent`` (iteration body) still split — their head is not a call
    target — and ``https://x!go`` still splits, since no ``)`` precedes it.
    """
    if bang < 1 or expr[bang - 1] != ")":
        return False
    opener = find_unquoted(expr, "(")
    body = None if opener is None else balanced_body(expr, opener + 1)
    if opener is None or body is None or opener + 1 + len(body) != bang - 1:
        return False
    return _is_call_target(expr[:opener])


def _is_call_target(head: str) -> bool:
    """True when ``head`` is a relative or remote call's ``/path`` prefix."""
    if head.startswith("url4://"):
        rest = head[len("url4://") :]
        slash = rest.find("/")
        return slash > 0 and _CALL_PATH_RE.fullmatch(rest[slash:]) is not None
    return _CALL_PATH_RE.fullmatch(head) is not None


def split_expr_params(expr: str) -> tuple[str, Params, IterationDirectives]:
    """Strip the trailing depth-0 ``;key[=val]`` chain (spec §9.2).

    Returns ``(clean_expr, params, directives)``: the ``iteration.*`` keys
    (§5.3.6; deprecated ``foreach.*`` spellings warn) decode into
    :class:`~url4.core.nodes.IterationDirectives`, every other key is preserved
    verbatim in ``params`` (flags carry a None value).
    """
    parts = _split_top_level(expr, ";")
    if len(parts) <= 1:
        return expr.strip(), (), IterationDirectives()
    params, directives = extract_directives(split_annotation_pairs(parts[1:]))
    return parts[0], params, directives


def split_foreach_annotations(expr: str) -> tuple[str, IterationDirectives]:
    """Deprecated pre-0.2 name for the directive split; use :func:`split_expr_params`."""
    warnings.warn(
        "split_foreach_annotations() is deprecated; use split_expr_params()",
        DeprecationWarning,
        stacklevel=2,
    )
    clean, _, directives = split_expr_params(expr)
    return clean, directives


def split_collection_iteration(source_expr: str) -> tuple[str | None, str | None]:
    """Detect the ``source*(body)`` collection-iteration pattern.

    Scans for ``*(`` at depth 0. On a match returns
    ``(collection_source, iteration_body)``; otherwise ``(None, None)``.
    """
    for i in iter_iteration_stars(source_expr):
        body = balanced_body(source_expr, i + 2)
        if body is not None:
            return source_expr[:i].strip(), body
    return None, None


def _split_at_iteration_body(text: str) -> tuple[str | None, str]:
    """Split ``text`` just after a depth-0 ``*(body)``, or ``(None, "")``.

    Returns ``(head, tail)`` where ``head`` runs from the start through the
    closing ``)`` of the iteration body and ``tail`` is whatever follows.

    # WHY: only a depth-0 ``*(`` is an envelope-level iteration. The
    # reduce-over-iteration shape ``(src*(body)!peri)!reducer`` and a
    # descriptored collection (§5.3.10) both nest their ``*(`` inside parens,
    # so they are invisible here and keep their existing decode route.
    """
    for i in iter_iteration_stars(text):
        body = balanced_body(text, i + 2)
        if body is not None:
            end = i + 2 + len(body) + 1
            return text[:end], text[end:]
    return None, ""


def split_top_level_commas(expr: str) -> list[str]:
    """Split ``expr`` on commas outside nesting/quotes; empty input → ``[]``."""
    return _split_top_level(expr, ",")


def strip_one_paren_layer(expr: str) -> str | None:
    """Return the contents of ``expr`` if it is exactly one balanced paren layer.

    ``(a, b)`` → ``a, b``; ``(a)(b)`` or a non-parenthesized string → ``None``.
    Surrounding whitespace is insignificant here (the envelope decoders hand
    over unstripped segments); the shared primitive itself is strip-free.
    """
    return one_paren_layer(expr.strip())


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
class IterationEnvelope:
    """A decoded ``src*(body)`` iteration: collection + per-row body, with the two
    optional reduce tails (per-row ``intent`` and cross-row ``reducer``) and the
    ``;iteration.*`` directives. All fields are still raw text — laziness is the
    interpreter's choice, not the envelope's."""

    collection: str
    body: str
    intent: str | None
    reducer: str | None
    directives: IterationDirectives


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
    head, tail = _split_at_iteration_body(stripped)
    if head is None:
        source_expr, raw_intent, broadcast = split_intent(stripped)
    else:
        # Only the text AFTER the iteration body can carry the envelope's own
        # ``!intent`` / ``;params``; everything up to and including the body is
        # the source side.
        tail_src, raw_intent, broadcast = split_intent(tail) if tail else ("", None, False)
        source_expr = head + tail_src
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
        if envelope.intent is None and require_intent:
            # INVARIANT: iteration-expr takes a full expression after "*", and
            # an expression's intent is mandatory (`OME-508`) — the cross-row
            # shape spells it `(src*(body)!peri)!reducer`.
            raise ParseError(
                f"iteration {stripped!r} has no per-row intent — the expression "
                "after '*' must carry !intent (src*(body)!intent)",
                code=ErrorCode.MISSING_INTENT,
            )
        return envelope
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
    return GroupEnvelope(source_expr, raw_intent, broadcast, params)


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


def _decode_iteration(
    source_expr: str, raw_intent: str | None, directives: IterationDirectives
) -> IterationEnvelope | None:
    # Reduce over iteration: ``(src*(body)[!peri];iteration.*)!reducer``. The
    # inner paren layer wraps its own directives + per-row intent;
    # ``raw_intent`` reduces across rows. A *descriptored* inner collection
    # (``(name:w:src*(body)…)!intent``) is NOT this shape — per §5.3.10 the
    # descriptor attributes the iteration as a source of the enclosing
    # expression, so the group route (the grammar) must handle it.
    if (
        raw_intent is not None
        and (inner := strip_one_paren_layer(source_expr)) is not None
        and not _is_source_list(inner)
    ):
        inner_clean, _, inner_directives = split_expr_params(inner)
        inner_src, per_row_intent, _ = split_intent(inner_clean)
        collection, body = split_collection_iteration(inner_src)
        if collection is not None and body is not None and not _is_descriptored(collection):
            merged = _merge_directives(inner_directives, directives)
            return IterationEnvelope(collection, body, per_row_intent, raw_intent, merged)

    # Plain iteration: ``src*(body)``; a top-level ``raw_intent`` reduces per row.
    collection, body = split_collection_iteration(source_expr)
    if collection is not None and body is not None:
        return IterationEnvelope(collection, body, raw_intent, None, directives)
    return None


def _is_source_list(inner: str) -> bool:
    """Return whether an iteration-looking parenthesis contains sibling sources.

    A depth-zero comma before the iteration body or after it proves the parenthesized
    value is an expression source list, rather than one reduce-over-iteration expression.
    """

    head, tail = _split_at_iteration_body(inner)
    if head is None:
        return False
    return len(split_top_level_commas(head)) > 1 or len(split_top_level_commas(tail)) > 1


def _is_descriptored(collection: str) -> bool:
    """True when an iteration's collection text carries a source descriptor.

    ``name:weight:src*(body)`` names the *iteration expression* (outer-plane
    attribution, §5.3.10), not the collection — such text must reach the
    grammar as a group source rather than decode as reduce-over-iteration.
    """
    if not collection.strip():
        return False
    try:
        node = parse(collection)
    except ParseError:
        return False
    return isinstance(node, (Source, Binding))


def _merge_directives(
    primary: IterationDirectives, secondary: IterationDirectives
) -> IterationDirectives:
    """Field-wise merge: an explicitly non-default ``primary`` field wins.

    The order is intentional and the merge is therefore NOT commutative — the
    result depends on which argument is ``primary``. That is correct while both
    directive sets come from the SAME expression (one source, one evaluation
    order). If two independent sources ever supply directives, this function
    needs a defined conflict rule instead.
    """
    default = IterationDirectives()
    return IterationDirectives(
        concurrency=primary.concurrency or secondary.concurrency,
        on_error=primary.on_error if primary.on_error != default.on_error else secondary.on_error,
        slice=primary.slice or secondary.slice,
        fmt_result=primary.fmt_result or secondary.fmt_result,
    )


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
