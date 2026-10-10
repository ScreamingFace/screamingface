"""The iteration envelope (Spec B §5.3): ``src*(body)`` and its reduce shapes, as raw text.

Split out of :mod:`url4.core.parser` (module-size cap), which re-exports
:class:`IterationEnvelope`. :func:`url4.core.parser.decode_envelope` calls
:func:`_decode_iteration` after it has split the top-level intent and params;
this module decides whether the source side is an iteration, a
reduce-over-iteration, or neither.
"""

from __future__ import annotations

from dataclasses import dataclass

from url4.core._annotations import DirectiveFields, directives_from_fields
from url4.core._descriptor_head import classify_head, name_and_value
from url4.core._lexical import _IDENT_RE, reject_chained_intent
from url4.core._splitters import (
    _split_at_iteration_body,
    split_collection_iteration,
    split_directive_fields,
    split_intent,
    split_top_level_commas,
    strip_one_paren_layer,
)
from url4.core.errors import ErrorCode, ParseError
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
    source_expr: str, raw_intent: str | None, directives: DirectiveFields
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
        inner_clean, _, inner_directives = split_directive_fields(inner)
        inner_src, per_row_intent, _ = split_intent(inner_clean)
        collection, body = split_collection_iteration(inner_src)
        if collection is not None and body is not None and not _is_descriptored(collection):
            merged = _merge_directives(inner_directives, directives)
            return IterationEnvelope(
                collection, body, per_row_intent, raw_intent, directives_from_fields(merged)
            )

    # Plain iteration: ``src*(body)``; a top-level ``raw_intent`` reduces per row.
    collection, body = split_collection_iteration(source_expr)
    if collection is not None and body is not None:
        return IterationEnvelope(
            collection, body, raw_intent, None, directives_from_fields(directives)
        )
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


def _merge_directives(primary: DirectiveFields, secondary: DirectiveFields) -> DirectiveFields:
    """Field-wise merge: a field ``primary`` GAVE wins (audit A8 — an explicit inner
    ``iteration.on_error=collect`` beats the outer policy).

    The order is intentional and the merge is therefore NOT commutative — the
    result depends on which argument is ``primary``. That is correct while both
    directive sets come from the SAME expression (one source, one evaluation
    order). If two independent sources ever supply directives, this function
    needs a defined conflict rule instead.
    """
    return {**secondary, **primary}


def check_iteration_envelope(
    envelope: IterationEnvelope, stripped: str, require_intent: bool
) -> None:
    """Refuse a decoded iteration the grammar has no reading for (Spec B §8).

    The collection must be a value, the per-row intent and the reducer must be
    single intents (D-1b), and — unless the caller is the engine's own spawn
    boundary (``require_intent=False``) — the per-row intent must be present.
    """
    _check_collection_ref(envelope.collection, stripped)
    for tail in (envelope.intent, envelope.reducer):
        if tail is not None:
            reject_chained_intent(tail)
    if envelope.intent is None and require_intent:
        # INVARIANT: iteration-expr takes a full expression after "*", and
        # an expression's intent is mandatory (`OME-508`) — the cross-row
        # shape spells it `(src*(body)!peri)!reducer`.
        raise ParseError(
            f"iteration {stripped!r} has no per-row intent — the expression "
            "after '*' must carry !intent (src*(body)!intent)",
            code=ErrorCode.MISSING_INTENT,
        )


def _check_collection_ref(collection: str, stripped: str) -> None:
    """A collection-ref is a value (Spec B §8 ``iteration-expr``); refuse what is not.

    The envelope scan never yields an empty collection (a leading ``*`` is the
    expansion prefix, never iteration), so that case is an asserted invariant.
    """
    text = collection.strip()
    assert text, "the envelope scan never yields an empty collection"
    if text.startswith("*"):
        raise ParseError(
            f"a collection cannot start with '*' in {stripped!r} — '*' marks a source for "
            "expansion inside a group; a collection is a value"
        )
    value = _descriptor_value(text)
    if value is not None and (not value or value.startswith("*")):
        # Spec B §8 rule 5: `n=…` / `n:…` is a descriptor, and its value (here the
        # text before the iteration '*(') can neither be empty nor start with '*'.
        raise ParseError(
            f"{text!r} is a descriptor whose value cannot start with '*' in {stripped!r} — "
            "expand a named source with '*name=(…)!intent'"
        )


def _descriptor_value(text: str) -> str | None:
    """The value after a descriptor head (``src=``, ``n=``, ``n:``), or None for a bare value."""
    if text[-1] in "=:" and _IDENT_RE.fullmatch(text[:-1]):
        return ""  # `n=` / `n:` with nothing after: classify_head reads these as bare values
    if classify_head(text)[0] == "value":
        return None
    binding = name_and_value(text)
    return None if binding is None else binding[2].strip()
