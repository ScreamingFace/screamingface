"""Saved cost across a real run: revalidation and run cost (PRD tests 17/18, E4/E6).

FEATURE: run-level saved cost (ans:Q2). The connector derives a hit's avoided cost from the
`_aigw` block of the round trip whose outcome it reports, and the executor folds it into the run's
counters.
STORY: as an operator I can trust the saved-cost total across a run whose cache policy forces a
re-issue, and I can see the run's own `cost_usd` is untouched by any of it.

WHY test 17 matters: `_fetch_completion` may refuse a hit and re-issue with `use-cache: false`,
returning the SECOND trip's outcome. Deriving saved cost from that same returned pair is the whole
protection against counting the discarded hit — this file pins it against a real run, not a mock
of the connector.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import httpx
import pytest

from screamingface_engine.request_scope import RequestScope, request_scope
from screamingface_engine.runner.cache_counters import (
    CACHE_HITS,
    SAVED_COST_ARCHIVE_USD,
    SAVED_COST_REPORTED_HITS,
    SAVED_COST_USD,
    RunCacheCounters,
    SavedCostTotals,
)
from screamingface_engine.runner.executor import Url4Executor
from screamingface_engine.runner.summary import RunSummary
from screamingface_engine.world.config import ModelSpec
from screamingface_engine.world.connector import AigatewayConfig, build_aigateway_world
from url4.streaming.protocol import CachePolicy

_MODEL = "anthropic/claude-haiku-4-5"
_CREDIT = "openrouter_credits"


def _aigw(amount: str | None, *, status: str = "reported", unit: str = _CREDIT) -> dict[str, Any]:
    """A hit's `_aigw`. `amount=None` means no reference cost at all (a legacy-looking row)."""
    reference: dict[str, Any] | None = None
    if amount is not None:
        reference = {
            "kind": "cached_final_response",
            "coverage": "final_successful_response_only",
            "incurred_in_current_request": False,
            "usage": {"status": "complete", "source": "cached_converted_response"},
            "direct_cost": {"status": status, "amount": amount, "unit": unit, "source": "s"},
        }
    return {
        "usage_accounting": {
            "schema": "aigw.chat_usage_accounting",
            "capture_status": "complete",
            "cache": {"status": "hit", "reference": reference},
            "observed_attempts": 0,
            "rendered_attempts": 0,
            "omitted_attempts": 0,
            "attempts": [],
        },
        "request_economics": {
            "schema": "aigw.request_economics",
            "observed_new_attempts": 0,
            "direct_cost_status": "not_applicable",
            "known_direct_cost_subtotals": [],
        },
    }


def _body(amount: str | None, *, status: str = "reported", unit: str = _CREDIT) -> dict[str, Any]:
    return {
        "choices": [{"message": {"role": "assistant", "content": "an answer"}}],
        "usage": {"prompt_tokens": 1, "completion_tokens": 1},
        "_aigw": _aigw(amount, status=status, unit=unit),
    }


def _hit(
    amount: str | None, *, reason: str = "fresh", status: str = "reported", unit: str = _CREDIT
) -> httpx.Response:
    return httpx.Response(
        200,
        headers={"X-AIGW-Cache": "hit", "X-AIGW-Cache-Reason": reason},
        json=_body(amount, status=status, unit=unit),
    )


def _uncached() -> httpx.Response:
    # No cache header at all: neither a hit nor a counted miss. The round trip the re-issue
    # produced reported no cached outcome, and only its outcome may be counted.
    return httpx.Response(200, headers={}, json=_body(None))


async def _run(responses: list[httpx.Response]) -> tuple[RunSummary | None, int]:
    seen = 0

    def handle(request: httpx.Request) -> httpx.Response:
        nonlocal seen
        response = responses[min(seen, len(responses) - 1)]
        seen += 1
        return response

    client = httpx.AsyncClient(
        transport=httpx.MockTransport(handle), base_url="http://aigateway.test"
    )
    cfg = AigatewayConfig(models=(ModelSpec(id=_MODEL),), default_model=_MODEL)
    async with client:
        world = await build_aigateway_world(cfg, client=client)
        executor = Url4Executor(world.node)
        # F2: the policy travels in the request scope; the executor inherits it from this task.
        with request_scope(
            RequestScope(origin="run", cache=CachePolicy(participate=True, max_age=0))
        ):
            async for _frame in executor.execute(f"/{_MODEL}(ctx)!go"):
                pass
        return executor.last_summary(), seen


# ── test 17: the discarded hit is never counted ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_a_discarded_hit_does_not_count_its_saved_cost() -> None:
    # The first response is a hit worth 9.99. `max_age=0` forces the re-issue; the second response
    # reports no cache outcome. Nothing was avoided in the round trip the run actually consumed.
    summary, requests = await _run([_hit("9.99"), _uncached()])

    assert requests == 2, "the bounded policy re-issued the call"
    attributes = summary.cache_attributes if summary is not None else None
    assert attributes is not None
    assert SAVED_COST_USD not in attributes
    assert SAVED_COST_REPORTED_HITS not in attributes


@pytest.mark.asyncio
async def test_the_reissued_trips_own_saved_cost_is_the_one_counted() -> None:
    # Both responses are hits, with different amounts. The run must report the SECOND one: the
    # outcome `_report_usage` uses, so the two cannot disagree.
    summary, requests = await _run([_hit("9.99", reason="stale"), _hit("0.25", reason="fresh")])

    assert requests == 2
    attributes = summary.cache_attributes if summary is not None else None
    assert attributes is not None
    assert attributes[SAVED_COST_REPORTED_HITS] == 1
    assert attributes[SAVED_COST_USD] == "0.25"
    assert "9.99" not in str(attributes)


# ── test 18: the run's own cost is unchanged by the feature ────────────────────────────────────


@pytest.mark.asyncio
async def test_a_hits_saved_cost_never_enters_the_runs_cost_usd() -> None:
    # I1: a hit costs 0 in the run's own total. The avoided amount is a counterfactual and stays
    # on its own field; adding it would report spend that never happened.
    summary, _ = await _run([_hit("9.99")])

    assert summary is not None
    assert summary.cost_usd == Decimal("0")
    assert summary.cache_attributes is not None
    assert summary.cache_attributes[SAVED_COST_USD] == "9.99"


@pytest.mark.asyncio
async def test_the_run_cost_is_identical_with_and_without_a_saved_cost() -> None:
    # The feature adds no term to `cost_usd`: the same hit, priced and unpriced, yields the same
    # run cost and the same pricing version. Only the new cache attributes differ.
    priced, _ = await _run([_hit("9.99")])
    unpriced, _ = await _run([_hit(None)])

    assert priced is not None and unpriced is not None
    assert priced.cost_usd == unpriced.cost_usd == Decimal("0")
    assert priced.pricing_version == unpriced.pricing_version
    assert priced.cache_attributes is not None and unpriced.cache_attributes is not None
    assert priced.cache_attributes[CACHE_HITS] == unpriced.cache_attributes[CACHE_HITS] == 1
    assert SAVED_COST_USD in priced.cache_attributes
    assert SAVED_COST_USD not in unpriced.cache_attributes


@pytest.mark.asyncio
async def test_an_archive_matched_hit_lands_in_its_own_total_not_the_provider_ones() -> None:
    # ans:Q5: a paired seed row is reported as `archive_matched` money, never as provider-authored
    # money, and never summed with it.
    summary, _ = await _run([_hit("0.25", status="archive_matched", unit="usd")])
    assert summary is not None and summary.cache_attributes is not None

    assert summary.cache_attributes[SAVED_COST_ARCHIVE_USD] == "0.25"
    assert SAVED_COST_USD not in summary.cache_attributes


def test_accumulating_two_maximum_precision_amounts_rounds_nothing() -> None:
    """Money is exact or it is not money.

    `avoided_usd_from_aigw` converts a single amount at `AMOUNT_PRECISION`, so an amount at the
    producer's published bound survives conversion. It must survive ADDITION too, or the run
    publishes a total that silently disagrees with the hits behind it.
    """
    bound = Decimal("999999999999999999.000000000000000000000000000000001")
    counters = RunCacheCounters()
    counters.record_saved_cost(bound, "reported")
    counters.record_saved_cost(bound, "reported")

    # The expected value is a LITERAL, never `bound + bound`: recomputing it here would run the
    # same ambient-context addition this test exists to catch, and the assertion would pass
    # against a rounded total by agreeing with the defect.
    assert counters.saved_cost_usd == Decimal(
        "1999999999999999998.000000000000000000000000000000002"
    )


def test_the_span_and_run_totals_agree_at_maximum_precision() -> None:
    """The two scopes share one accumulator helper, so they must agree on the EXACT value.

    They already agreed while both were wrong — which is why this asserts the literal rather
    than only comparing the two to each other.
    """
    bound = Decimal("999999999999999999.000000000000000000000000000000001")
    run = RunCacheCounters()
    span = SavedCostTotals()
    for totals in (run, span):
        totals.add_saved_cost(bound, "reported")
        totals.add_saved_cost(bound, "reported")

    assert run.saved_cost_usd == span.saved_cost_usd
    assert span.saved_cost_usd == Decimal("1999999999999999998.000000000000000000000000000000002")
