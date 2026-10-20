"""A call's price and tokens come from the successful attempt's evidence (OME-1687, Phase B).

FEATURE: cost of intelligence (OME-1687). The gateway (OME-1686) sends the successful attempt's
own cost and usage beside the all-attempt figures:

- `_aigw.request_economics.succeeded_attempt_direct_cost` — that attempt's `direct_cost`, or null;
- `_aigw.usage_accounting.succeeded_attempt_usage` — that attempt's `usage`, or null.

STORY: as a reader of the leaderboard, I see what the model's successful answer cost and how many
tokens it used, also when the gateway retried a 503 before that answer.

INVARIANT under test (D1, mirrored for tokens): a mapping is used as the only evidence; a malformed
value is unknown and never mixed with the all-attempt figures; an absent or null key keeps today's
rule, so responses from an older gateway, old frozen copies and cache hits read exactly as before.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import httpx
import pytest

from screamingface_engine.runner.executor import _RunState
from screamingface_engine.world.accounting import (
    OPENROUTER_CREDIT_UNIT,
    PRICING_VERSION,
    read_aigw,
    retained_operation_accounting,
    usd_from_aigw,
)
from screamingface_engine.world.cache_readback import CacheOutcome, CacheStatus
from screamingface_engine.world.config import ModelSpec
from screamingface_engine.world.connector import AigatewayConfig, build_aigateway_world
from url4.dag import run as url4_run
from url4.observe import NodeStarted, ObservationEvent, Usage

_MODEL = "openrouter/anthropic/claude-x"
_MISS_HEADERS = {"X-AIGW-Cache": "miss", "X-AIGW-Cache-Reason": "absent"}
_ABSENT = object()


def _usage(
    *, input_total: int, output_total: int, cache_read: int, cache_write: int, reasoning: int
) -> dict[str, Any]:
    return {
        "input": {"total": input_total, "cache_read": cache_read, "cache_write": cache_write},
        "output": {"total": output_total, "reasoning": reasoning},
    }


_FAILED_USAGE = _usage(input_total=100, output_total=0, cache_read=40, cache_write=20, reasoning=0)
_SUCCEEDED_USAGE = _usage(input_total=12, output_total=7, cache_read=4, cache_write=2, reasoning=3)


def _reported(amount: str = "0.00042", unit: str = OPENROUTER_CREDIT_UNIT) -> dict[str, Any]:
    return {"status": "reported", "amount": amount, "unit": unit, "source": "openrouter.usage.cost"}


def _retried_aigw(
    *,
    direct_cost: object = _ABSENT,
    usage: object = _ABSENT,
    capture_status: str = "complete",
    omitted_attempts: int = 0,
) -> dict[str, Any]:
    """A gateway response after a 503 → 200 retry inside one HTTP call.

    `direct_cost` and `usage` are the two OME-1686 keys; `_ABSENT` leaves a key out (an older
    gateway). The failed 503 attempt carries usage on purpose, so a sum is visibly not the answer.
    """
    accounting: dict[str, Any] = {
        "capture_status": capture_status,
        "omitted_attempts": omitted_attempts,
        "cache": {"status": "miss", "reference": None},
        "attempts": [
            {
                "provider": "openrouter",
                "response_model": "anthropic/claude-x-20260801",
                "outcome": "provider_error",
                "http_status": 503,
                "usage": _FAILED_USAGE,
                "direct_cost": {"status": "unavailable", "amount": None},
            },
            {
                "provider": "openrouter",
                "response_model": "anthropic/claude-x-20260801",
                "outcome": "succeeded",
                "http_status": 200,
                "usage": _SUCCEEDED_USAGE,
                "direct_cost": _reported(),
            },
        ],
    }
    economics: dict[str, Any] = {
        "direct_cost_status": "partial",
        "known_direct_cost_subtotals": [_reported()],
    }
    if direct_cost is not _ABSENT:
        economics["succeeded_attempt_direct_cost"] = direct_cost
    if usage is not _ABSENT:
        accounting["succeeded_attempt_usage"] = usage
    return {"usage_accounting": accounting, "request_economics": economics}


def _complete_aigw(*, direct_cost: object = _ABSENT, subtotal: str = "0.001") -> dict[str, Any]:
    """A one-attempt priced miss: `direct_cost_status: complete`."""
    economics: dict[str, Any] = {
        "direct_cost_status": "complete",
        "known_direct_cost_subtotals": [
            {"amount": subtotal, "unit": OPENROUTER_CREDIT_UNIT, "source": "openrouter"}
        ],
    }
    if direct_cost is not _ABSENT:
        economics["succeeded_attempt_direct_cost"] = direct_cost
    return {
        "usage_accounting": {
            "capture_status": "complete",
            "omitted_attempts": 0,
            "cache": {"status": "miss", "reference": None},
            "attempts": [{"provider": "openrouter", "outcome": "succeeded"}],
        },
        "request_economics": economics,
    }


def _hit_aigw(*, direct_cost: object) -> dict[str, Any]:
    return {
        "usage_accounting": {
            "capture_status": "complete",
            "omitted_attempts": 0,
            "cache": {"status": "hit", "reference": None},
            "attempts": [],
            "succeeded_attempt_usage": None,
        },
        "request_economics": {
            "direct_cost_status": "not_applicable",
            "known_direct_cost_subtotals": [],
            "succeeded_attempt_direct_cost": direct_cost,
        },
    }


def _tokens(aigw: object) -> tuple[int | None, ...]:
    call = read_aigw(aigw)
    assert call is not None
    return (
        call.input_tokens,
        call.output_tokens,
        call.cache_read_tokens,
        call.cache_creation_tokens,
        call.reasoning_tokens,
    )


def _cache(status: CacheStatus) -> CacheOutcome:
    return CacheOutcome(status=status, reason=None, key=None, age_s=None)


# ── price: `request_economics.succeeded_attempt_direct_cost` ───────────────────────────────────


def test_a_gateway_retried_call_is_priced_from_its_successful_attempt() -> None:
    assert usd_from_aigw(_retried_aigw(direct_cost=_reported())) == Decimal("0.00042")


def test_the_successful_attempt_cost_wins_over_a_disagreeing_complete_subtotal() -> None:
    aigw = _complete_aigw(direct_cost=_reported("0.0007"), subtotal="0.001")

    assert usd_from_aigw(aigw) == Decimal("0.0007")


@pytest.mark.parametrize(
    "direct_cost",
    [
        {"status": "unavailable", "amount": None, "unit": None},
        {"status": "invalid", "amount": "0.1", "unit": OPENROUTER_CREDIT_UNIT},
        {"status": "provider_guaranteed_zero", "amount": "0", "unit": OPENROUTER_CREDIT_UNIT},
        _reported(unit="usd_cents"),
        _reported(amount="0.10"),  # not canonical: a trailing zero
        _reported(amount="-1"),
    ],
    ids=["unavailable", "invalid", "guaranteed_zero", "unknown_unit", "trailing_zero", "negative"],
)
def test_a_successful_attempt_without_a_reported_credit_price_is_unpriced(
    direct_cost: dict[str, Any],
) -> None:
    # R3: a real unknown is not a retry effect. The complete subtotal beside it is not consulted.
    assert usd_from_aigw(_complete_aigw(direct_cost=direct_cost)) is None


@pytest.mark.parametrize("malformed", ["0.00042", ["0.00042"], 0.00042, True])
def test_a_malformed_successful_attempt_cost_is_unpriced_and_never_raises(
    malformed: object,
) -> None:
    assert usd_from_aigw(_complete_aigw(direct_cost=malformed)) is None


def test_a_null_successful_attempt_cost_on_a_cache_hit_keeps_the_exact_zero() -> None:
    assert usd_from_aigw(_hit_aigw(direct_cost=None)) == Decimal(0)


def test_a_null_successful_attempt_cost_on_a_miss_keeps_todays_rule() -> None:
    assert usd_from_aigw(_complete_aigw(direct_cost=None)) == Decimal("0.001")
    assert usd_from_aigw(_retried_aigw(direct_cost=None)) is None


def test_an_older_gateway_without_the_key_keeps_todays_rule() -> None:
    assert usd_from_aigw(_complete_aigw()) == Decimal("0.001")
    assert usd_from_aigw(_retried_aigw()) is None


# ── tokens: `usage_accounting.succeeded_attempt_usage` ─────────────────────────────────────────


def test_tokens_come_only_from_the_successful_attempt_usage() -> None:
    assert _tokens(_retried_aigw(usage=_SUCCEEDED_USAGE)) == (12, 7, 4, 2, 3)


@pytest.mark.parametrize("malformed", ["12", [12], 12, True])
def test_a_malformed_successful_attempt_usage_makes_every_token_class_unknown(
    malformed: object,
) -> None:
    # Never a mix with the all-attempt sums, which would count the failed attempt's tokens.
    assert _tokens(_retried_aigw(usage=malformed)) == (None,) * 5


def test_an_unreported_class_in_the_successful_attempt_usage_stays_unknown() -> None:
    usage = {"input": {"total": 12, "cache_read": None}, "output": {"total": 7}}

    assert _tokens(_retried_aigw(usage=usage)) == (12, 7, None, None, None)


@pytest.mark.parametrize("usage", [_ABSENT, None], ids=["absent", "null"])
def test_without_the_successful_attempt_usage_tokens_keep_todays_all_attempt_sum(
    usage: object,
) -> None:
    assert _tokens(_retried_aigw(usage=usage)) == (112, 7, 44, 22, 3)


def test_the_retained_operation_takes_tokens_from_the_successful_attempt() -> None:
    retained = retained_operation_accounting(
        request_model=_MODEL,
        usage={"prompt_tokens": 999, "completion_tokens": 999},
        aigw=_retried_aigw(direct_cost=_reported(), usage=_SUCCEEDED_USAGE),
        cache=_cache("miss"),
    )

    usage = retained.usage
    assert (usage.input_tokens, usage.output_tokens) == (12, 7)
    assert (usage.cache_read_tokens, usage.cache_creation_tokens, usage.reasoning_tokens) == (
        4,
        2,
        3,
    )
    assert usage.cost_usd == "0.00042"


def test_the_retained_operation_keeps_successful_attempt_tokens_after_degradation() -> None:
    # The key survives the gateway's truncation and size degradation, which set the capture to
    # `partial`; the tokens are still that one attempt's exact counts.
    retained = retained_operation_accounting(
        request_model=_MODEL,
        usage=None,
        aigw=_retried_aigw(usage=_SUCCEEDED_USAGE, capture_status="partial", omitted_attempts=1),
        cache=_cache("miss"),
    )

    usage = retained.usage
    assert (usage.input_tokens, usage.output_tokens, usage.reasoning_tokens) == (12, 7, 3)


def test_a_malformed_usage_key_makes_the_retained_tokens_unknown() -> None:
    retained = retained_operation_accounting(
        request_model=_MODEL,
        usage={"prompt_tokens": 999, "completion_tokens": 999},
        aigw=_retried_aigw(usage="malformed"),
        cache=_cache("miss"),
    )

    usage = retained.usage
    assert (usage.input_tokens, usage.output_tokens, usage.cache_read_tokens) == (None, None, None)


# ── end to end through the connector ───────────────────────────────────────────────────────────


class _Recorder:
    def __init__(self) -> None:
        self.events: list[ObservationEvent] = []

    def on_event(self, event: ObservationEvent) -> None:
        self.events.append(event)

    @property
    def usages(self) -> list[Usage]:
        return [e for e in self.events if isinstance(e, Usage)]


async def _live_usage(aigw: dict[str, Any]) -> Usage:
    body = {
        "choices": [
            {"message": {"role": "assistant", "content": "an answer"}, "finish_reason": "stop"}
        ],
        "usage": {"prompt_tokens": 12, "completion_tokens": 7},
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
        assert await url4_run(f"/{_MODEL}(ctx)!go", io=world.node, observer=rec) == "an answer"
    (usage,) = rec.usages
    return usage


@pytest.mark.asyncio
async def test_a_gateway_503_then_200_is_priced_and_counted_from_the_200() -> None:
    usage = await _live_usage(_retried_aigw(direct_cost=_reported(), usage=_SUCCEEDED_USAGE))

    assert usage.cost_usd == Decimal("0.00042")
    assert (usage.input_tokens, usage.output_tokens) == (12, 7)
    assert (usage.cache_read_tokens, usage.cache_creation_tokens, usage.reasoning_tokens) == (
        4,
        2,
        3,
    )


@pytest.mark.asyncio
async def test_a_run_with_a_gateway_retried_call_is_priced() -> None:
    usage = await _live_usage(_retried_aigw(direct_cost=_reported(), usage=_SUCCEEDED_USAGE))
    state = _RunState()
    span = usage.span_id or "a" * 16
    state.map(NodeStarted(span_id=span, parent_span_id=None, node_kind="RelUrlNode", detail="m"))
    state.map(usage)

    subtree = state.build_subtree()

    assert subtree.pricing_version == PRICING_VERSION
    assert subtree.cost.total_usd == Decimal("0.00042")
