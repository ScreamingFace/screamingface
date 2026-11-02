"""An OpenRouter refusal before output is priced as $0 (spec 2026-10-26, P3–P5).

FEATURE: cost of intelligence (OME-1287). Anthropic refuses some biology questions before the
model writes output. Through OpenRouter that reply carries no `usage` and leaves no generation
record, so nothing is billed. The gateway certifies it as `provider_guaranteed_zero` with the
source `openrouter.pre_output_refusal`.

STORY: as a reader of the lab_bench board, I see a cost for a run of a model that refused some
questions, instead of "—".

INVARIANT under test (P5): only the refusal source prices. A guaranteed zero from a rule this
engine does not know stays unpriced, exactly as OME-1687 R3 says.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import httpx
import pytest

from screamingface_engine.runner.cache_counters import RunCacheCounters
from screamingface_engine.runner.executor import _RunState
from screamingface_engine.world.accounting import (
    OPENROUTER_CREDIT_UNIT,
    PRICING_VERSION,
    AvoidedCost,
    avoided_usd_from_aigw,
    usd_from_aigw,
)
from screamingface_engine.world.config import ModelSpec
from screamingface_engine.world.connector import AigatewayConfig, build_aigateway_world
from url4.core.errors import ResolutionError
from url4.dag import run as url4_run
from url4.observe import NodeStarted, ObservationEvent, Usage

_MODEL = "openrouter/anthropic/claude-x"
_MISS_HEADERS = {"X-AIGW-Cache": "miss", "X-AIGW-Cache-Reason": "absent"}
_REFUSAL_SOURCE = "openrouter.pre_output_refusal"


def _zero(source: str = _REFUSAL_SOURCE, unit: str = OPENROUTER_CREDIT_UNIT) -> dict[str, Any]:
    return {"status": "provider_guaranteed_zero", "amount": "0", "unit": unit, "source": source}


def _unavailable_usage() -> dict[str, Any]:
    return {
        "status": "unavailable",
        "source": "provider_raw_response",
        "input": {"total": None, "cache_read": None, "cache_write": None},
        "output": {"total": None, "reasoning": None},
    }


def _refused_miss_aigw(direct_cost: dict[str, Any]) -> dict[str, Any]:
    """One succeeded 200 attempt that the gateway certified, as the gateway renders it."""
    return {
        "usage_accounting": {
            "capture_status": "complete",
            "omitted_attempts": 0,
            "cache": {"status": "miss", "reference": None},
            "attempts": [
                {
                    "provider": "openrouter",
                    "outcome": "succeeded",
                    "http_status": 200,
                    "usage": _unavailable_usage(),
                    "direct_cost": direct_cost,
                }
            ],
            "succeeded_attempt_usage": _unavailable_usage(),
        },
        "request_economics": {
            # WHY "partial": the gateway never builds an empty zero subtotal (OME-1446), so an
            # all-zero call is "partial" with no subtotal. The successful-attempt key is the price.
            "direct_cost_status": "partial",
            "known_direct_cost_subtotals": [],
            "succeeded_attempt_direct_cost": direct_cost,
        },
    }


def _refused_hit_aigw(reference_cost: dict[str, Any]) -> dict[str, Any]:
    return {
        "usage_accounting": {
            "capture_status": "complete",
            "omitted_attempts": 0,
            "cache": {
                "status": "hit",
                "reference": {
                    "kind": "cached_final_response",
                    "coverage": "final_successful_response_only",
                    "incurred_in_current_request": False,
                    "usage": {**_unavailable_usage(), "source": "cached_converted_response"},
                    "direct_cost": reference_cost,
                },
            },
            "attempts": [],
        },
        "request_economics": {
            "direct_cost_status": "not_applicable",
            "known_direct_cost_subtotals": [],
        },
    }


# ── P3: the successful attempt ─────────────────────────────────────────────────────────────────


def test_a_certified_pre_output_refusal_is_priced_at_exactly_zero() -> None:
    assert usd_from_aigw(_refused_miss_aigw(_zero())) == Decimal(0)


@pytest.mark.parametrize(
    "direct_cost",
    [
        _zero(source="openrouter.zero_completion_insurance"),
        _zero(source="some.future_rule"),
        {**_zero(), "source": None},
        _zero(unit="usd_cents"),
        {**_zero(), "amount": "0.1"},
        {**_zero(), "amount": None},
        {**_zero(), "status": "unavailable"},
    ],
    ids=[
        "insurance",
        "unknown_source",
        "no_source",
        "unknown_unit",
        "nonzero",
        "no_amount",
        "status",
    ],
)
def test_any_other_guaranteed_zero_on_the_successful_attempt_stays_unpriced(
    direct_cost: dict[str, Any],
) -> None:
    # P5: R3 holds for every zero rule this engine does not know.
    assert usd_from_aigw(_refused_miss_aigw(direct_cost)) is None


# ── P4: the cache reference of a hit ───────────────────────────────────────────────────────────


def test_a_hit_on_a_certified_refusal_is_a_priced_hit_that_saved_zero() -> None:
    aigw = _refused_hit_aigw(_zero())

    assert avoided_usd_from_aigw(aigw) == AvoidedCost(usd=Decimal(0), provenance="reported")
    # I1: the current request stays free whatever the reference holds.
    assert usd_from_aigw(aigw) == Decimal(0)


def test_a_hit_on_a_certified_refusal_is_not_counted_as_an_unpriced_hit() -> None:
    counters = RunCacheCounters()

    avoided = avoided_usd_from_aigw(_refused_hit_aigw(_zero()))
    counters.record_saved_cost(avoided.usd, avoided.provenance)

    assert (counters.reported_hits, counters.unpriced_hits) == (1, 0)
    assert counters.saved_cost_usd == Decimal(0)


@pytest.mark.parametrize(
    "reference_cost",
    [_zero(source="openrouter.zero_completion_insurance"), _zero(unit="usd_cents")],
    ids=["insurance", "unknown_unit"],
)
def test_a_hit_on_any_other_guaranteed_zero_stays_unpriced(reference_cost: dict[str, Any]) -> None:
    assert avoided_usd_from_aigw(_refused_hit_aigw(reference_cost)) == AvoidedCost()


# ── end to end: a refused call no longer makes the run unpriced ────────────────────────────────


class _Recorder:
    def __init__(self) -> None:
        self.events: list[ObservationEvent] = []

    def on_event(self, event: ObservationEvent) -> None:
        self.events.append(event)


async def _refused_usage(aigw: dict[str, Any]) -> Usage:
    # The live OpenRouter body (2026-10-26) as the gateway returns it: no usage, no content.
    body = {
        "id": "gen-refused",
        "model": "anthropic/claude-x",
        "choices": [
            {
                "index": 0,
                "finish_reason": "content_filter",
                "message": {"role": "assistant", "content": None},
            }
        ],
        "_aigw": aigw,
    }

    def handle(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers=_MISS_HEADERS, json=body)

    rec = _Recorder()
    cfg = AigatewayConfig(models=(ModelSpec(id=_MODEL, web_search=False),), default_model=_MODEL)
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handle), base_url="http://aigateway.test"
    ) as client:
        world = await build_aigateway_world(cfg, client=client)
        with pytest.raises(ResolutionError) as raised:
            await url4_run(f"/{_MODEL}(ctx)!go", io=world.node, observer=rec)
    assert raised.value.code == "provider_refusal"
    (usage,) = [event for event in rec.events if isinstance(event, Usage)]
    return usage


@pytest.mark.asyncio
async def test_a_refused_call_reports_a_zero_cost_and_the_run_stays_priced() -> None:
    usage = await _refused_usage(_refused_miss_aigw(_zero()))
    state = _RunState()
    span = usage.span_id or "a" * 16
    state.map(NodeStarted(span_id=span, parent_span_id=None, node_kind="RelUrlNode", detail="m"))
    state.map(usage)

    subtree = state.build_subtree()

    assert usage.cost_usd == Decimal(0)
    assert subtree.pricing_version == PRICING_VERSION
    assert subtree.cost.total_usd == Decimal(0)
