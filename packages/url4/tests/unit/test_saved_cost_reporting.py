"""Saved-cost reporting on the observation seam (PRD tasks E1/E2, ERD §4).

FEATURE: run-level saved cost (PRD ans:Q2). A cache hit costs nothing upstream; the amount it
avoided must travel BESIDE the cache outcome that says so, on the same round trip, so the engine
can total it without inventing a second seam or mixing it into token accounting.
STORY: as an operator I can see what the run's cache hits would have cost, and from WHICH kind of
evidence — provider-authored or archive-paired — each figure came.

WHY the two values must stay out of `CostBreakdown`: that wire object is CLOSED
(`extra="forbid"`), and avoided money is not consumption. Smuggling it into the cost block would
let one call be counted twice — once as spend and once as saving.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from pydantic import ValidationError

from url4.dag import run
from url4.io.static import StaticIOLayer
from url4.observe import (
    ModelResponse,
    NodeStarted,
    ObservationEvent,
    SavedCostProvenance,
    current_response_sink,
)
from url4.streaming.protocol import SpanData
from url4.streaming.protocol.taxonomy import CostBreakdown


class RecordingObserver:
    def __init__(self) -> None:
        self.events: list[ObservationEvent] = []

    def on_event(self, event: ObservationEvent) -> None:
        self.events.append(event)


class _CtxSavedCostNode:
    deps: dict = {}

    async def resolve(self, inputs, ctx):
        ctx.report_response(
            finish_reason="stop",
            refusal=None,
            cache_status="hit",
            cache_reason="fresh",
            cache_saved_cost_usd=Decimal("0.0125"),
            cache_saved_cost_provenance="reported",
        )
        return "ok"


class _SinkSavedCostNode:
    deps: dict = {}

    async def resolve(self, inputs, ctx):
        sink = current_response_sink()
        assert sink is not None
        sink(
            finish_reason="stop",
            refusal=None,
            cache_status="hit",
            cache_reason=None,
            cache_saved_cost_usd=Decimal("4.5"),
            cache_saved_cost_provenance="archive_matched",
        )
        return "ok"


class _CtxNoSavedCostNode:
    deps: dict = {}

    async def resolve(self, inputs, ctx):
        ctx.report_response(
            finish_reason="stop",
            refusal=None,
            cache_status="hit",
            cache_reason="fresh",
        )
        return "ok"


def test_a_model_response_defaults_both_saved_cost_fields_to_none() -> None:
    # Boundary: an older gateway, or a hit with nothing priceable, reports neither. `None` is
    # "not priced", deliberately distinct from `Decimal("0")` ("was genuinely free").
    response = ModelResponse("span", "stop", None, "hit", None)

    assert response.cache_saved_cost_usd is None
    assert response.cache_saved_cost_provenance is None


def test_the_provenance_literal_names_exactly_the_two_claims() -> None:
    # Both provenances exist and nothing else does. `reported` is provider-authored money;
    # `archive_matched` is a paired seed price whose per-row attribution is unproven (ans:Q5) —
    # and the engine never sums the two.
    provenances: tuple[SavedCostProvenance, ...] = ("reported", "archive_matched")

    assert set(provenances) == {"reported", "archive_matched"}


@pytest.mark.asyncio
async def test_ctx_report_response_forwards_the_saved_cost_to_the_observer() -> None:
    rec = RecordingObserver()
    await run(_CtxSavedCostNode(), StaticIOLayer(), observer=rec)

    (response,) = [e for e in rec.events if isinstance(e, ModelResponse)]
    assert response.cache_saved_cost_usd == Decimal("0.0125")
    assert response.cache_saved_cost_provenance == "reported"


@pytest.mark.asyncio
async def test_the_ctx_less_sink_carries_the_archive_provenance_too() -> None:
    rec = RecordingObserver()
    await run(_SinkSavedCostNode(), StaticIOLayer(), observer=rec)

    (response,) = [e for e in rec.events if isinstance(e, ModelResponse)]
    assert response.cache_saved_cost_usd == Decimal("4.5")
    assert response.cache_saved_cost_provenance == "archive_matched"
    (start,) = [e for e in rec.events if isinstance(e, NodeStarted)]
    assert response.span_id == start.span_id


@pytest.mark.asyncio
async def test_a_caller_that_reports_no_saved_cost_is_unaffected() -> None:
    # INVARIANT: a live seam. Existing callers must keep compiling and must read as "nothing
    # reported" rather than a fabricated zero saving, so a node that reports only its cache
    # outcome leaves both saved-cost fields None downstream.
    rec = RecordingObserver()
    await run(_CtxNoSavedCostNode(), StaticIOLayer(), observer=rec)

    (response,) = [e for e in rec.events if isinstance(e, ModelResponse)]
    assert response.cache_status == "hit"
    assert response.cache_saved_cost_usd is None
    assert response.cache_saved_cost_provenance is None


def test_span_data_carries_both_saved_cost_fields() -> None:
    # One field per provenance, each a total over this span's hits of that kind. The provenance
    # is carried by the FIELD NAME rather than by a tag beside a single amount, so no consumer
    # can add the tags away and produce a figure PRD S5 forbids.
    span = SpanData(
        name="aigateway",
        operation="chat",
        provider="openrouter",
        cache_status="hit",
        cache_saved_cost_usd=Decimal("0.0125"),
        cache_saved_cost_archive_usd=Decimal("5"),
        start=datetime.now(UTC),
    )

    assert span.cache_saved_cost_usd == Decimal("0.0125")
    assert span.cache_saved_cost_archive_usd == Decimal("5")


def test_both_saved_cost_fields_are_absent_by_default_on_a_span() -> None:
    span = SpanData(name="static", operation="fetch", start=datetime.now(UTC))

    assert span.cache_saved_cost_usd is None
    assert span.cache_saved_cost_archive_usd is None


def test_the_cost_block_is_still_closed_to_saved_cost() -> None:
    # E2's load-bearing decision. `CostBreakdown` is `extra="forbid"`, so saved cost cannot be
    # smuggled into it — it must be its own field on `SpanData`.
    with pytest.raises(ValidationError):
        # The unknown keyword is the point of the test: pyright is right that the field does
        # not exist, and `extra="forbid"` is what turns that into a runtime rejection too.
        CostBreakdown(total_usd=Decimal("0"), cache_saved_cost_usd=Decimal("1"))  # pyright: ignore[reportCallIssue]

    assert "cache_saved_cost_usd" not in CostBreakdown.model_fields


# --- the pairing invariant is enforced, not merely documented ----------------------------------


def test_an_amount_without_a_provenance_is_refused() -> None:
    """INVARIANT: `cache_saved_cost_provenance` is set if and only if `cache_saved_cost_usd` is.

    WHY this is a guard and not a convention: `observe` is a live seam and adapters construct
    `ModelResponse` directly. An amount that arrives with no provenance cannot be routed to
    either total, so it would be silently dropped into the unpriced bucket — money that was
    measured, reported, and then quietly lost. `AvoidedCost` on the accounting side has enforced
    the same pairing since it was written; the wire-adjacent seam must not be the weaker one.
    """
    with pytest.raises(ValueError):
        ModelResponse(
            "span",
            "stop",
            None,
            "hit",
            None,
            cache_saved_cost_usd=Decimal("0.0038"),
            cache_saved_cost_provenance=None,
        )


def test_a_provenance_without_an_amount_is_refused() -> None:
    """The other half of the same invariant: a claim about evidence with no money to attach."""
    with pytest.raises(ValueError):
        ModelResponse(
            "span",
            "stop",
            None,
            "hit",
            None,
            cache_saved_cost_usd=None,
            cache_saved_cost_provenance="reported",
        )


@pytest.mark.parametrize("provenance", ["reported", "archive_matched"])
def test_a_paired_amount_and_provenance_is_accepted(provenance: SavedCostProvenance) -> None:
    """Both provenances construct normally when paired — the guard refuses only the broken shape."""
    response = ModelResponse(
        "span",
        "stop",
        None,
        "hit",
        None,
        cache_saved_cost_usd=Decimal("0.0038"),
        cache_saved_cost_provenance=provenance,
    )

    assert response.cache_saved_cost_usd == Decimal("0.0038")
    assert response.cache_saved_cost_provenance == provenance


def test_a_round_trip_that_saved_nothing_still_constructs() -> None:
    """Boundary: neither set is the common case — a miss, or a hit with nothing priceable."""
    response = ModelResponse("span", "stop", None, "miss", "no-store")

    assert response.cache_saved_cost_usd is None
    assert response.cache_saved_cost_provenance is None


# --- the amount and provenance stay inside money's domain, not just paired ---------------------


def test_a_negative_saved_cost_is_refused() -> None:
    """Negative savings are not a claim the cache can make: a hit avoids money or it does not."""
    with pytest.raises(ValueError, match="cache_saved_cost_usd must be a finite non-negative"):
        ModelResponse(
            span_id="s1",
            finish_reason="stop",
            refusal=None,
            cache_status="hit",
            cache_saved_cost_usd=Decimal("-0.01"),
            cache_saved_cost_provenance="reported",
        )


def test_an_unknown_saved_cost_provenance_is_refused() -> None:
    """An unrecognised provenance would be counted as an unpriced hit, losing measured money."""
    with pytest.raises(ValueError, match="cache_saved_cost_provenance must be one of"):
        ModelResponse(
            span_id="s1",
            finish_reason="stop",
            refusal=None,
            cache_status="hit",
            cache_saved_cost_usd=Decimal("0.01"),
            cache_saved_cost_provenance="bogus",  # type: ignore[arg-type]
        )


def test_a_non_finite_saved_cost_is_refused() -> None:
    """NaN and Infinity pass a bare `< 0` check and would poison every downstream total."""
    for amount in (Decimal("NaN"), Decimal("Infinity")):
        with pytest.raises(ValueError, match="cache_saved_cost_usd must be a finite non-negative"):
            ModelResponse(
                span_id="s1",
                finish_reason="stop",
                refusal=None,
                cache_status="hit",
                cache_saved_cost_usd=amount,
                cache_saved_cost_provenance="reported",
            )


def test_the_span_wire_seam_refuses_negative_saved_cost() -> None:
    """The same domain rule on the wire type, which an outside consumer reaches first."""
    with pytest.raises(ValidationError, match="cache_saved_cost_usd must be a finite non-negative"):
        SpanData(
            name="aigateway",
            operation="chat",
            start=datetime.now(UTC),
            cache_saved_cost_usd=Decimal("-0.01"),
        )


def test_the_span_wire_seam_refuses_negative_archive_saved_cost() -> None:
    with pytest.raises(
        ValidationError, match="cache_saved_cost_archive_usd must be a finite non-negative"
    ):
        SpanData(
            name="aigateway",
            operation="chat",
            start=datetime.now(UTC),
            cache_saved_cost_archive_usd=Decimal("-0.01"),
        )


def test_a_zero_saved_cost_is_still_accepted() -> None:
    """Zero is a real claim — a genuinely free call — and must survive the non-negative guard."""
    response = ModelResponse(
        span_id="s1",
        finish_reason="stop",
        refusal=None,
        cache_status="hit",
        cache_saved_cost_usd=Decimal("0"),
        cache_saved_cost_provenance="reported",
    )
    assert response.cache_saved_cost_usd == Decimal("0")
