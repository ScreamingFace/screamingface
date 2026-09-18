"""A cache hit that followed a transport retry cannot prove it cost nothing.

FEATURE: per-run cost reporting (OME-849/OME-868) meeting the saved-cost feature (PRD ans:Q2).
STORY: as an operator reading a run summary I can tell "this call was free" from "we cannot know
what this call cost", because only one of them is safe to add into a total.

The defect this pins (PR #930 review round 3, finding 1): `avoided_usd_for_outcome` already
WITHDRAWS the saved-cost claim when a round trip was retried — a lost reply may have been
processed and billed upstream, so the row the next attempt hits may be the one the lost attempt
paid for and wrote. But `_report_usage` still routed every hit through `_report_served_from_cache`,
which publishes `cost_usd=Decimal(0)`. The run therefore reported no saving AND an affirmative
zero spend for a round trip whose spend is precisely what nobody knows.

INVARIANT under test: withdrawing the saving and asserting the spend are the SAME claim about the
same ambiguous evidence, so they must move together. `None` ("not priced") is the honest answer;
`Decimal("0")` ("was genuinely free") is a claim the evidence does not support.

INVARIANT: the withdrawal is scoped to the RETRY, not to hits in general. An unretried hit is
still priced at zero — that is a real saving and OME-851's P0 — and this file pins both halves so
the fix cannot over-correct into blanking every cache hit's price.

A separate module rather than an append to `test_cache_hit_tokens.py`: the repo's append-only gate
compares file status, so growing an existing test file reads as a modified prior test even when
the diff is purely additive.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any
from unittest import mock

import httpx
import pytest

from screamingface_engine.runner.accounting import (
    OPENROUTER_CREDIT_UNIT,
    PRICING_VERSION,
    UNPRICED,
)
from screamingface_engine.runner.connector import AigatewayConfig, build_aigateway_world
from screamingface_engine.runner.executor import _RunState
from screamingface_engine.world_config import ModelSpec
from url4.dag import run as url4_run
from url4.observe import NodeStarted, ObservationEvent, Usage

_MODEL = "openrouter/anthropic/claude-x"
_HIT_HEADERS = {"X-AIGW-Cache": "hit", "X-AIGW-Cache-Reason": "fresh"}
_MISS_HEADERS = {"X-AIGW-Cache": "miss", "X-AIGW-Cache-Reason": "absent"}


class _Recorder:
    def __init__(self) -> None:
        self.events: list[ObservationEvent] = []

    def on_event(self, event: ObservationEvent) -> None:
        self.events.append(event)

    @property
    def usages(self) -> list[Usage]:
        return [e for e in self.events if isinstance(e, Usage)]


def _served_aigw() -> dict[str, Any]:
    """The `_aigw` shape a HIT produces: no attempts, no subtotals, `not_applicable`."""
    return {
        "usage_accounting": {
            "capture_status": "complete",
            "cache": {"status": "hit", "reference": None},
            "attempts": [],
        },
        "request_economics": {
            "direct_cost_status": "not_applicable",
            "known_direct_cost_subtotals": [],
        },
    }


def _billed_aigw() -> dict[str, Any]:
    """The `_aigw` shape a real provider call produces — a priced MISS."""
    return {
        "usage_accounting": {
            "capture_status": "complete",
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


def _body(aigw: dict[str, Any]) -> dict[str, Any]:
    return {
        "choices": [
            {"message": {"role": "assistant", "content": "an answer"}, "finish_reason": "stop"}
        ],
        "usage": {"prompt_tokens": 651, "completion_tokens": 25},
        "_aigw": aigw,
    }


async def _run(
    body: dict[str, Any], headers: dict[str, str], rec: _Recorder, *, fail_first: bool
) -> str:
    """Drive one gateway round trip, optionally losing the FIRST attempt's reply.

    A lost reply is what `_post_completion` retries, and the retry is the only thing that sets
    `CacheOutcome.retried` — the fact is unobservable anywhere else, which is why it is threaded
    rather than re-derived.
    """
    posts = 0

    def handle(request: httpx.Request) -> httpx.Response:
        nonlocal posts
        posts += 1
        if fail_first and posts == 1:
            raise httpx.ReadError("")
        return httpx.Response(200, headers=headers, json=body)

    cfg = AigatewayConfig(models=(ModelSpec(id=_MODEL, web_search=False),), default_model=_MODEL)
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handle), base_url="http://aigateway.test"
    ) as client:
        world = await build_aigateway_world(cfg, client=client)
        with (
            mock.patch("screamingface_engine.runner.connector._TRANSPORT_BACKOFF_BASE_S", 0.0),
            mock.patch("screamingface_engine.runner.connector._TRANSPORT_BACKOFF_JITTER_S", 0.0),
        ):
            return await url4_run(f"/{_MODEL}(ctx)!go", io=world.node, observer=rec)


def _usage(*, cost_usd: Decimal | None, span: str) -> Usage:
    """One round trip's usage as the connector reports it for a CACHE HIT: no tokens, and a price
    that is either a definite zero or an honest unknown."""
    return Usage(
        span_id=span,
        provider="openrouter",
        model=_MODEL,
        input_tokens=0,
        output_tokens=0,
        cache_read_tokens=0,
        cache_creation_tokens=0,
        reasoning_tokens=0,
        cost_usd=cost_usd,
    )


# ── the defect ─────────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_a_hit_after_a_retry_reports_an_unknown_price_not_a_zero_one() -> None:
    rec = _Recorder()

    assert await _run(_body(_served_aigw()), _HIT_HEADERS, rec, fail_first=True) == "an answer"

    assert rec.usages[0].cost_usd is None


@pytest.mark.asyncio
async def test_a_hit_with_no_retry_is_still_priced_at_zero() -> None:
    # The other half of the invariant: an unretried hit avoided real money and says so. Blanking
    # every hit's price would hide a true saving, which is the opposite defect.
    rec = _Recorder()

    await _run(_body(_served_aigw()), _HIT_HEADERS, rec, fail_first=False)

    assert rec.usages[0].cost_usd == Decimal("0")


@pytest.mark.asyncio
async def test_a_retried_hit_still_reports_no_tokens_consumed() -> None:
    # Only the PRICE is unknown. The provider demonstrably did no work for THIS request, so the
    # token counts stay the definite zeros OME-868 established — `None` there would invent a gap.
    rec = _Recorder()

    await _run(_body(_served_aigw()), _HIT_HEADERS, rec, fail_first=True)

    usage = rec.usages[0]
    assert (usage.input_tokens, usage.output_tokens) == (0, 0)
    assert usage.cache_read_tokens == 0
    assert usage.cache_creation_tokens == 0
    assert usage.reasoning_tokens == 0


@pytest.mark.asyncio
async def test_a_retried_miss_keeps_its_provider_authored_price() -> None:
    # Scope guard: the withdrawal belongs to the hit path, where the published figure would
    # otherwise be an affirmative zero. A miss carries real attempt accounting and keeps it.
    rec = _Recorder()

    await _run(_body(_billed_aigw()), _MISS_HEADERS, rec, fail_first=True)

    assert rec.usages[0].cost_usd == Decimal("0.001")


def test_a_retried_hit_makes_the_whole_run_total_unpriced() -> None:
    """The consequence that makes this worth fixing, at run scope.

    `_fold_usage` latches UNPRICED on the first cost it cannot know and never unlatches, so the
    run publishes "unknown" rather than a grand total that silently omits an unknowable step
    while presenting itself as complete. A false `Decimal(0)` would instead be summed in as fact.
    """
    state = _RunState()
    span = "a" * 16
    state.map(NodeStarted(span_id=span, parent_span_id=None, node_kind="RelUrlNode", detail="m"))
    state.map(_usage(cost_usd=Decimal("0.004"), span=span))  # a real priced call earlier in the run
    state.map(_usage(cost_usd=None, span=span))  # the retried hit

    subtree = state.build_subtree()

    assert subtree.pricing_version == UNPRICED
    assert subtree.cost.total_usd == Decimal("0")


def test_an_unretried_hits_zero_still_sums_into_a_priced_run_total() -> None:
    # The scope guard at run level: a genuine zero is ADDED, and the run stays priced. If the fix
    # blanked every hit, a cache-heavy run would lose its cost total entirely.
    state = _RunState()
    span = "a" * 16
    state.map(NodeStarted(span_id=span, parent_span_id=None, node_kind="RelUrlNode", detail="m"))
    state.map(_usage(cost_usd=Decimal("0.004"), span=span))
    state.map(_usage(cost_usd=Decimal("0"), span=span))

    subtree = state.build_subtree()

    assert subtree.pricing_version == PRICING_VERSION
    assert subtree.cost.total_usd == Decimal("0.004")
