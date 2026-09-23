"""Span-level saved cost: one accumulator per provenance, on the span exactly as on the run.

FEATURE: run-level saved cost (PRD ans:Q2), published per SPAN as well as per run.
STORY: as an operator reading a trace I can sum a span's saved-cost attribute across the run's
spans and get the run's own total back, instead of a figure that silently dropped every hit but
the last one.

INVARIANT: a span's saved cost ACCUMULATES per gateway round trip (PRD §4.1 — "O(1) per gateway
round trip, not per turn"), it does not latch the last one. A tool-calling turn is several
independently-keyed calls against ONE span, and money is additive where a status is not.

INVARIANT (S7/M8): `reported` money and `archive_matched` money live in two accumulators and are
never summed, on a span exactly as on the run. This file asserts the span grows no third one.

INVARIANT: the span accumulates only for a HIT — the same guard the run counter beside it uses.
A miss or a bypass avoided nothing, whatever price rides along with it.
"""

from __future__ import annotations

from collections.abc import Iterable
from decimal import Decimal
from typing import Literal

from screamingface_engine.runner.executor import _RunState
from url4.observe import ModelResponse, NodeFinished, NodeStarted, SavedCostProvenance
from url4.streaming.protocol import SpanData

_SPAN = "a" * 16
_OTHER_SPAN = "b" * 16


def _hit(
    amount: str | None,
    provenance: SavedCostProvenance | None = "reported",
    *,
    span_id: str = _SPAN,
    status: Literal["hit", "miss", "bypass"] = "hit",
) -> ModelResponse:
    """One round trip's outcome, priced as the connector would price it."""
    return ModelResponse(
        span_id=span_id,
        finish_reason="stop",
        refusal=None,
        cache_status=status,
        cache_reason=None,
        cache_saved_cost_usd=None if amount is None else Decimal(amount),
        cache_saved_cost_provenance=provenance,
    )


def _total(amounts: Iterable[Decimal | None]) -> Decimal:
    """What a trace backend would sum out of one attribute across a run's spans.

    Absent is skipped rather than read as zero, exactly as the spans mean it.
    """
    return sum((amount for amount in amounts if amount is not None), Decimal("0"))


def _span_after(*responses: ModelResponse) -> SpanData:
    """Drive `_RunState` through ONE node that reports `responses` against the same span."""
    state = _RunState()
    state.map(NodeStarted(span_id=_SPAN, parent_span_id=None, node_kind="RelUrlNode", detail="m"))
    for response in responses:
        state.map(response)
    frames = state.map(NodeFinished(span_id=_SPAN, status="ok", engine_seq=1))
    return next(f.payload for f in frames if isinstance(f.payload, SpanData))


def test_a_span_publishes_the_sum_of_its_reported_hits() -> None:
    # The finding this file exists for: three $0.01 hits on one tool-calling turn published
    # $0.01 while the run published $0.03, so summing the span attribute reported a third of
    # the truth with nothing to say two amounts had been dropped.
    span = _span_after(_hit("0.01"), _hit("0.01"), _hit("0.01"))

    assert span.cache_saved_cost_usd == Decimal("0.03")


def test_a_span_keeps_the_two_provenances_in_separate_totals() -> None:
    span = _span_after(_hit("0.03"), _hit("5", "archive_matched"))

    assert span.cache_saved_cost_usd == Decimal("0.03")
    assert span.cache_saved_cost_archive_usd == Decimal("5")


def test_an_unpriceable_hit_leaves_an_earlier_total_standing() -> None:
    # A hit the engine cannot price is coverage, not a correction: it must not blank money that
    # an earlier round trip on the same span genuinely established.
    span = _span_after(_hit("0.02"), _hit(None, None))

    assert span.cache_saved_cost_usd == Decimal("0.02")


def test_a_priced_non_hit_adds_nothing_to_the_span() -> None:
    # Guard parity with `RunCacheCounters.record_saved_cost`, which is reached only for a hit.
    # Nothing emits a price on a miss today; the two guards encode ONE invariant and must not
    # be free to drift apart the first time something does.
    span = _span_after(_hit("0.02"), _hit("9", status="miss"), _hit("7", status="bypass"))

    assert span.cache_saved_cost_usd == Decimal("0.02")
    assert span.cache_saved_cost_archive_usd is None


def test_a_span_that_saw_no_hit_publishes_neither_total() -> None:
    # `None` is "no hit reported a priceable saving", which a `0` would misstate as "the cache
    # saved nothing" — the same distinction the run totals keep.
    span = _span_after(_hit(None, None, status="miss"))

    assert span.cache_saved_cost_usd is None
    assert span.cache_saved_cost_archive_usd is None


def test_the_span_totals_reconcile_with_the_run_totals() -> None:
    # The whole point of accumulating: what a trace backend sums out of the spans is what the
    # run summary states, per provenance. A last-wins span cannot satisfy this.
    state = _RunState()
    state.map(NodeStarted(span_id=_SPAN, parent_span_id=None, node_kind="RelUrlNode", detail="m"))
    state.map(
        NodeStarted(span_id=_OTHER_SPAN, parent_span_id=_SPAN, node_kind="RelUrlNode", detail="n")
    )
    state.map(_hit("0.01"))
    state.map(_hit("0.01"))
    state.map(_hit("0.02", span_id=_OTHER_SPAN))
    state.map(_hit("5", "archive_matched", span_id=_OTHER_SPAN))
    spans = [
        f.payload
        for span_id in (_OTHER_SPAN, _SPAN)
        for f in state.map(NodeFinished(span_id=span_id, status="ok", engine_seq=1))
        if isinstance(f.payload, SpanData)
    ]

    assert _total(s.cache_saved_cost_usd for s in spans) == state.cache_counters.saved_cost_usd
    assert (
        _total(s.cache_saved_cost_archive_usd for s in spans)
        == state.cache_counters.saved_cost_archive_usd
    )


def test_the_span_wire_record_carries_exactly_two_saved_cost_fields() -> None:
    # Structural, mirroring the run counter's own guard: a third field — a combined total — would
    # fail here even before anything read it, and so would a lone un-summable figure returning.
    saved_cost_fields = {name for name in SpanData.model_fields if "saved_cost" in name}

    assert saved_cost_fields == {"cache_saved_cost_usd", "cache_saved_cost_archive_usd"}
