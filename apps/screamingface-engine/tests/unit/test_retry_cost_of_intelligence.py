"""A retry never makes a model call unpriced: the price is the successful request's (OME-1687).

FEATURE: cost of intelligence (OME-1687). The leaderboard shows what a model's answers cost in a
perfect world, where every model answers on the first attempt. A retry is an infrastructure event.
STORY: as a reader of the leaderboard, I see the price of a model's successful answers, and a
transport blip or a gateway 5xx on one call does not turn the whole run into "—".

This reverses the OME-1220 rule ("a call retried after a possibly billed failure is unpriced").
The retry flag itself stays: `CacheOutcome.retried` is still recorded, and no price reads it.

INVARIANT under test: only the price rule changes. A connect-phase retry, a frozen-copy capture
after a lost reply, and a failed response's missing Usage behave exactly as before.
"""

from __future__ import annotations

import dataclasses
from decimal import Decimal
from typing import Any
from unittest import mock

import httpx
import pytest

from screamingface_engine.runner.cache_counters import RunCacheCounters
from screamingface_engine.runner.executor import _RunState
from screamingface_engine.world.accounting import (
    OPENROUTER_CREDIT_UNIT,
    PRICING_VERSION,
    AvoidedCost,
    avoided_usd_for_outcome,
    retained_operation_accounting,
)
from screamingface_engine.world.cache_readback import CacheOutcome, CacheStatus
from screamingface_engine.world.config import ModelSpec
from screamingface_engine.world.connector import (
    AigatewayConfig,
    _CaptureProbe,
    build_aigateway_world,
)
from url4.core.errors import ResolutionError
from url4.dag import run as url4_run
from url4.observe import ModelResponse, NodeStarted, ObservationEvent, Usage

_MODEL = "openrouter/anthropic/claude-x"
_HIT_HEADERS = {"X-AIGW-Cache": "hit", "X-AIGW-Cache-Reason": "fresh"}
_MISS_HEADERS = {"X-AIGW-Cache": "miss", "X-AIGW-Cache-Reason": "absent"}

# The failures OME-1220 called "possibly billed": they may follow a request that reached the
# gateway. Connect-phase failures were always priced and are covered in
# `test_ambiguous_retry_pricing.py`.
_AMBIGUOUS = [
    httpx.ReadError(""),
    httpx.ReadTimeout(""),
    httpx.RemoteProtocolError(""),
    httpx.WriteError(""),
    httpx.WriteTimeout(""),
]


class _Recorder:
    def __init__(self) -> None:
        self.events: list[ObservationEvent] = []

    def on_event(self, event: ObservationEvent) -> None:
        self.events.append(event)

    @property
    def usages(self) -> list[Usage]:
        return [e for e in self.events if isinstance(e, Usage)]

    @property
    def responses(self) -> list[ModelResponse]:
        return [e for e in self.events if isinstance(e, ModelResponse)]


def _billed_aigw() -> dict[str, Any]:
    """A priced MISS: one succeeded attempt and a complete provider-authored subtotal."""
    return {
        "usage_accounting": {
            "capture_status": "complete",
            "omitted_attempts": 0,
            "cache": {"status": "miss", "reference": None},
            "attempts": [
                {
                    "provider": "openrouter",
                    "response_model": "anthropic/claude-x-20260801",
                    "outcome": "succeeded",
                    "usage": {"input": {"total": 11}, "output": {"total": 7}},
                }
            ],
        },
        "request_economics": {
            "direct_cost_status": "complete",
            "known_direct_cost_subtotals": [
                {"amount": "0.001", "unit": OPENROUTER_CREDIT_UNIT, "source": "openrouter"}
            ],
        },
    }


def _served_aigw() -> dict[str, Any]:
    """A HIT whose stored reference carries the original call's reported cost (the saving)."""
    return {
        "usage_accounting": {
            "capture_status": "complete",
            "omitted_attempts": 0,
            "cache": {
                "status": "hit",
                "reference": {
                    "direct_cost": {
                        "status": "reported",
                        "amount": "0.002",
                        "unit": OPENROUTER_CREDIT_UNIT,
                        "source": "openrouter.usage.cost",
                    }
                },
            },
            "attempts": [],
        },
        "request_economics": {
            "direct_cost_status": "not_applicable",
            "known_direct_cost_subtotals": [],
        },
    }


def _body(aigw: dict[str, Any]) -> dict[str, Any]:
    return {
        "choices": [
            {"message": {"role": "assistant", "content": "an answer"}, "finish_reason": "stop"}
        ],
        "usage": {"prompt_tokens": 11, "completion_tokens": 7},
        "_aigw": aigw,
    }


def _no_backoff() -> Any:
    return mock.patch.multiple(
        "screamingface_engine.world.connector",
        _TRANSPORT_BACKOFF_BASE_S=0.0,
        _TRANSPORT_BACKOFF_JITTER_S=0.0,
    )


async def _run(
    body: dict[str, Any], headers: dict[str, str], first_failure: Exception | None
) -> _Recorder:
    """One model call whose FIRST attempt fails with `first_failure` (if any)."""
    posts = 0

    def handle(request: httpx.Request) -> httpx.Response:
        nonlocal posts
        posts += 1
        if first_failure is not None and posts == 1:
            raise first_failure
        return httpx.Response(200, headers=headers, json=body)

    rec = _Recorder()
    cfg = AigatewayConfig(models=(ModelSpec(id=_MODEL, web_search=False),), default_model=_MODEL)
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handle), base_url="http://aigateway.test"
    ) as client:
        world = await build_aigateway_world(cfg, client=client)
        with _no_backoff():
            assert await url4_run(f"/{_MODEL}(ctx)!go", io=world.node, observer=rec) == "an answer"
    assert posts == (1 if first_failure is None else 2)
    return rec


def _outcome(status: CacheStatus) -> CacheOutcome:
    return CacheOutcome(status=status, reason=None, key=None, age_s=None, retried=True)


# ── call level: the Usage a span and the run total are built from ──────────────────────────────


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", _AMBIGUOUS, ids=lambda e: type(e).__name__)
async def test_a_miss_retried_after_an_ambiguous_failure_is_priced_from_its_answer(
    failure: Exception,
) -> None:
    rec = await _run(_body(_billed_aigw()), _MISS_HEADERS, failure)

    (usage,) = rec.usages
    assert usage.cost_usd == Decimal("0.001")


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", _AMBIGUOUS, ids=lambda e: type(e).__name__)
async def test_a_hit_retried_after_an_ambiguous_failure_is_priced_at_zero(
    failure: Exception,
) -> None:
    rec = await _run(_body(_served_aigw()), _HIT_HEADERS, failure)

    (usage,) = rec.usages
    assert usage.cost_usd == Decimal("0")


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", _AMBIGUOUS, ids=lambda e: type(e).__name__)
async def test_a_hit_retried_after_an_ambiguous_failure_claims_its_saving(
    failure: Exception,
) -> None:
    # WHY the saving counts: the leaderboard's reproduction cost is spend plus saving, and in a
    # perfect world the hit replaces the original call, whose cost the reference holds.
    rec = await _run(_body(_served_aigw()), _HIT_HEADERS, failure)

    (response,) = rec.responses
    assert response.cache_saved_cost_usd == Decimal("0.002")
    assert response.cache_saved_cost_provenance == "reported"


# ── operation level and saved cost: the retained accounting a run artifact keeps ──────────────


@pytest.mark.parametrize(
    ("aigw", "status", "cost"),
    [(_billed_aigw(), "miss", "0.001"), (_served_aigw(), "hit", "0")],
    ids=["miss", "hit"],
)
def test_a_retried_round_trip_keeps_its_price_in_the_retained_operation(
    aigw: dict[str, Any], status: CacheStatus, cost: str
) -> None:
    retained = retained_operation_accounting(
        request_model=_MODEL,
        usage={"prompt_tokens": 11, "completion_tokens": 7},
        aigw=aigw,
        cache=_outcome(status),
    )

    assert retained.usage.cost_usd == cost


def test_a_retried_hit_saving_enters_the_priced_total() -> None:
    saved = avoided_usd_for_outcome(_served_aigw(), _outcome("hit"))
    counters = RunCacheCounters()
    counters.record("hit", None)
    counters.record_saved_cost(saved.usd, saved.provenance)

    assert saved == AvoidedCost(usd=Decimal("0.002"), provenance="reported")
    assert counters.unpriced_hits == 0
    assert counters.saved_cost_usd == Decimal("0.002")


# ── run level ──────────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_a_run_with_a_retried_call_is_priced_and_sums_its_calls() -> None:
    retried = (await _run(_body(_billed_aigw()), _MISS_HEADERS, httpx.ReadError(""))).usages[0]
    clean = (await _run(_body(_billed_aigw()), _MISS_HEADERS, None)).usages[0]
    state = _RunState()
    span = "a" * 16
    state.map(NodeStarted(span_id=span, parent_span_id=None, node_kind="RelUrlNode", detail="m"))
    for usage in (retried, clean):
        state.map(dataclasses.replace(usage, span_id=span))

    subtree = state.build_subtree()

    assert subtree.pricing_version == PRICING_VERSION
    assert subtree.cost.total_usd == Decimal("0.002")


# ── what must not change ───────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_a_gateway_502_emits_no_usage_and_the_next_call_is_priced_on_its_own() -> None:
    # The url4 `;retry=` path (P3): `_raise_for_status` raises before any accounting is read, so
    # the failed response adds nothing, and the re-run call is priced from its own `_aigw`.
    posts = 0

    def handle(request: httpx.Request) -> httpx.Response:
        nonlocal posts
        posts += 1
        if posts == 1:
            return httpx.Response(502, json={"detail": {"code": "provider_error"}})
        return httpx.Response(200, headers=_MISS_HEADERS, json=_body(_billed_aigw()))

    rec = _Recorder()
    cfg = AigatewayConfig(models=(ModelSpec(id=_MODEL, web_search=False),), default_model=_MODEL)
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handle), base_url="http://aigateway.test"
    ) as client:
        world = await build_aigateway_world(cfg, client=client)
        with pytest.raises(ResolutionError) as failed:
            await url4_run(f"/{_MODEL}(ctx)!go", io=world.node, observer=rec)
        assert rec.usages == []
        assert await url4_run(f"/{_MODEL}(ctx)!go", io=world.node, observer=rec) == "an answer"

    assert failed.value.permanent is False
    (usage,) = rec.usages
    assert usage.cost_usd == Decimal("0.001")


def test_a_lost_reply_still_makes_the_capture_ambiguous() -> None:
    # The REPLAY/CAPTURE half of the retry fact is not a price and does not change.
    probe = _CaptureProbe()
    probe.lost_reply()
    probe.read(httpx.Response(200, headers={}))

    assert probe.status() == "ambiguous"
