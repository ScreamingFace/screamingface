"""A round trip retried after a reply that may have been billed reports an unknown cost (OME-1220).

FEATURE: per-run cost reporting (OME-849) under the connector's one-shot transport retry.
STORY: as an operator reading a run's cost, I never see a figure lower than what was spent; when
a lost reply makes the spend unknowable, the run says "unknown" instead of a confident undercount.

WHY a retry can hide spend: `_post_completion` retries once after a transport failure. If the
failure came after the request left the Engine, the gateway may already have dispatched it, and a
non-streaming provider call is billed in full even when the caller goes away (the gateway cancels
its provider call on disconnect, so it never learns that price either). The retry's own figure is
then only part of the spend; a hit that follows may be the very row the lost attempt paid for.

INVARIANT under test: the price is withdrawn only on evidence the request MAY have been sent.
`ConnectError`, `ConnectTimeout` and `PoolTimeout` are raised before httpcore writes a byte
(connection setup or the wait for a pooled connection), so a retry after one keeps the exact
price. Every other transport failure is ambiguous: httpcore swallows a mid-request `WriteError`
and surfaces the outcome as a read-side error, so "write vs read" cannot separate the cases;
only "connect phase vs everything else" can.

INVARIANT: only the PRICE becomes unknown. Token counts keep their meaning (a lower bound for a
miss, definite zeros for a hit); the wire has no "unknown" token count.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any
from unittest import mock

import httpx
import pytest

from screamingface_engine.world.accounting import (
    OPENROUTER_CREDIT_UNIT,
    retained_operation_accounting,
)
from screamingface_engine.world.cache_readback import CacheOutcome, CacheStatus
from screamingface_engine.world.config import ModelSpec
from screamingface_engine.world.connector import (
    AigatewayConfig,
    _fetch_completion,
    _post_completion,
    build_aigateway_world,
)
from url4.dag import run as url4_run
from url4.observe import ObservationEvent, Usage
from url4.streaming.protocol import CachePolicy

_MODEL = "openrouter/anthropic/claude-x"
_HIT_HEADERS = {"X-AIGW-Cache": "hit", "X-AIGW-Cache-Reason": "fresh"}
_MISS_HEADERS = {"X-AIGW-Cache": "miss", "X-AIGW-Cache-Reason": "absent"}

_AMBIGUOUS = [
    httpx.ReadError(""),
    httpx.ReadTimeout(""),
    httpx.RemoteProtocolError(""),
    httpx.WriteError(""),
    httpx.WriteTimeout(""),
]
_NEVER_SENT = [httpx.ConnectError(""), httpx.ConnectTimeout(""), httpx.PoolTimeout("")]


class _Recorder:
    def __init__(self) -> None:
        self.events: list[ObservationEvent] = []

    def on_event(self, event: ObservationEvent) -> None:
        self.events.append(event)

    @property
    def usages(self) -> list[Usage]:
        return [e for e in self.events if isinstance(e, Usage)]


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
    """A HIT: no attempts, cost `not_applicable`."""
    return {
        "usage_accounting": {
            "capture_status": "complete",
            "omitted_attempts": 0,
            "cache": {"status": "hit", "reference": None},
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
) -> Usage:
    """One model call whose FIRST attempt fails with `first_failure` (if any); returns its Usage."""
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
    (usage,) = rec.usages
    return usage


# ── call level: the Usage a span and the run total are built from ──────────────────────────────


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", _AMBIGUOUS, ids=lambda e: type(e).__name__)
async def test_a_miss_retried_after_a_possibly_billed_failure_is_unpriced(
    failure: Exception,
) -> None:
    usage = await _run(_body(_billed_aigw()), _MISS_HEADERS, failure)

    assert usage.cost_usd is None


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", _AMBIGUOUS, ids=lambda e: type(e).__name__)
async def test_an_unpriced_retried_miss_keeps_its_token_counts(failure: Exception) -> None:
    # Only the price is unknown. The tokens are the retry's own — a lower bound, still reported.
    usage = await _run(_body(_billed_aigw()), _MISS_HEADERS, failure)

    assert (usage.input_tokens, usage.output_tokens) == (11, 7)


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", _NEVER_SENT, ids=lambda e: type(e).__name__)
async def test_a_miss_retried_after_a_connect_phase_failure_keeps_its_exact_price(
    failure: Exception,
) -> None:
    # Nothing left the Engine on the first attempt, so the second is the only one billed.
    usage = await _run(_body(_billed_aigw()), _MISS_HEADERS, failure)

    assert usage.cost_usd == Decimal("0.001")


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", _NEVER_SENT, ids=lambda e: type(e).__name__)
async def test_a_hit_retried_after_a_connect_phase_failure_keeps_its_zero(
    failure: Exception,
) -> None:
    usage = await _run(_body(_served_aigw()), _HIT_HEADERS, failure)

    assert usage.cost_usd == Decimal("0")


@pytest.mark.asyncio
async def test_an_unretried_miss_keeps_its_price() -> None:
    usage = await _run(_body(_billed_aigw()), _MISS_HEADERS, None)

    assert usage.cost_usd == Decimal("0.001")


# ── the seam itself: every consumer (price, retained cost, saved cost) reads this one flag ────


async def _post_flag(failures: list[Exception]) -> bool:
    posts = 0

    def handle(request: httpx.Request) -> httpx.Response:
        nonlocal posts
        posts += 1
        if posts <= len(failures):
            raise failures[posts - 1]
        return httpx.Response(200, headers=_MISS_HEADERS, json=_body(_billed_aigw()))

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handle), base_url="http://aigateway.test"
    ) as client:
        with _no_backoff():
            _, possibly_billed = await _post_completion(
                client, headers={}, body={"model": _MODEL, "messages": []}
            )
    return possibly_billed


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", _NEVER_SENT, ids=lambda e: type(e).__name__)
async def test_a_connect_phase_failure_does_not_mark_the_retry_possibly_billed(
    failure: Exception,
) -> None:
    # This flag also withdraws a hit's SAVED cost (`avoided_usd_for_outcome`), so a hit after a
    # connect-phase failure keeps its saving as well as its zero price.
    assert await _post_flag([failure]) is False


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", _AMBIGUOUS, ids=lambda e: type(e).__name__)
async def test_an_ambiguous_failure_marks_the_retry_possibly_billed(failure: Exception) -> None:
    assert await _post_flag([failure]) is True


@pytest.mark.asyncio
async def test_no_failure_is_not_possibly_billed() -> None:
    assert await _post_flag([]) is False


# ── the re-issue path: a hit refused for age is fetched again without the cache ───────────────


@pytest.mark.asyncio
async def test_a_reissue_keeps_the_first_round_trips_possibly_billed_retry() -> None:
    # Round trip 1 loses its first reply, then is served a hit the run's `max-age` refuses; the
    # re-issue then succeeds cleanly. The lost attempt may still have been billed, so the outcome
    # of the response the call consumes must carry that, not just the re-issue's clean history.
    posts = 0

    def handle(request: httpx.Request) -> httpx.Response:
        nonlocal posts
        posts += 1
        if posts == 1:
            raise httpx.ReadError("")
        if posts == 2:
            return httpx.Response(200, headers=_HIT_HEADERS, json=_body(_served_aigw()))
        return httpx.Response(200, headers=_MISS_HEADERS, json=_body(_billed_aigw()))

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handle), base_url="http://aigateway.test"
    ) as client:
        with _no_backoff():
            _, outcome = await _fetch_completion(
                client,
                headers={},
                body={"model": _MODEL, "messages": []},
                cache=CachePolicy(participate=True, max_age=0),
            )

    assert posts == 3
    assert outcome.status == "miss"
    assert outcome.retried is True


# ── operation level: the retained accounting a run artifact keeps ─────────────────────────────


def _outcome(status: CacheStatus, *, retried: bool) -> CacheOutcome:
    return CacheOutcome(status=status, reason=None, key=None, age_s=None, retried=retried)


@pytest.mark.parametrize(
    ("aigw", "status"), [(_billed_aigw(), "miss"), (_served_aigw(), "hit")], ids=["miss", "hit"]
)
def test_a_possibly_billed_retry_is_unpriced_in_the_retained_operation(
    aigw: dict[str, Any], status: CacheStatus
) -> None:
    retained = retained_operation_accounting(
        request_model=_MODEL,
        usage={"prompt_tokens": 11, "completion_tokens": 7},
        aigw=aigw,
        cache=_outcome(status, retried=True),
    )

    assert retained.usage.cost_usd is None


@pytest.mark.parametrize(
    ("aigw", "status", "cost"),
    [(_billed_aigw(), "miss", "0.001"), (_served_aigw(), "hit", "0")],
    ids=["miss", "hit"],
)
def test_an_unretried_operation_keeps_its_price(
    aigw: dict[str, Any], status: CacheStatus, cost: str
) -> None:
    retained = retained_operation_accounting(
        request_model=_MODEL,
        usage={"prompt_tokens": 11, "completion_tokens": 7},
        aigw=aigw,
        cache=_outcome(status, retried=False),
    )

    assert retained.usage.cost_usd == cost


def test_a_retried_operation_keeps_its_token_counts() -> None:
    retained = retained_operation_accounting(
        request_model=_MODEL,
        usage={"prompt_tokens": 11, "completion_tokens": 7},
        aigw=_billed_aigw(),
        cache=_outcome("miss", retried=True),
    )

    assert (retained.usage.input_tokens, retained.usage.output_tokens) == (11, 7)
