"""The iteration envelope (Spec B §5.3): ``src*(body)`` and its reduce shapes, as raw text.

Split out of :mod:`url4.core.parser` (module-size cap), which re-exports
:class:`IterationEnvelope`. :func:`url4.core.parser.decode_envelope` calls
:func:`_decode_iteration` after it has split the top-level intent and params;
this module decides whether the source side is an iteration, a
reduce-over-iteration, or neither.
"""

from __future__ import annotations

from dataclasses import dataclass

from url4.core._splitters import (
    _split_at_iteration_body,
    split_collection_iteration,
    split_expr_params,
    split_intent,
    split_top_level_commas,
    strip_one_paren_layer,
)
from url4.core.errors import ParseError
from url4.core.grammar import parse
from url4.core.nodes import Binding, IterationDirectives, Source


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


def _decode_iteration(
    source_expr: str, raw_intent: str | None, directives: IterationDirectives
) -> IterationEnvelope | None:
    # Reduce over iteration: ``(src*(body)[!peri];iteration.*)!reducer``. The
    # inner paren layer wraps its own directives + per-row intent;
    # ``raw_intent`` reduces across rows. A *descriptored* inner collection
    # (``(name:w:src*(body)…)!intent``) is NOT this shape — per §5.3.10 the
    # descriptor attributes the iteration as a source of the enclosing
    # expression, so the group route (the grammar) must handle it. So does a leading
    # "*" expansion inner source (B2): it is never a collection.
    if (
        raw_intent is not None
        and (inner := strip_one_paren_layer(source_expr)) is not None
        and not _is_source_list(inner)
        and not inner.lstrip().startswith("*")
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
