"""Exact-only accounting retained beside semantic Benchmark operations."""

from __future__ import annotations

from typing import Any

from screamingface_engine.operation_accounting import combine_operation_accounting
from screamingface_engine.runner.accounting import retained_operation_accounting
from screamingface_engine.runner.cache_readback import CacheOutcome, CacheStatus


def _attempt(
    *,
    provider: str = "openrouter",
    response_model: str | None = "anthropic/claude-served",
    input_tokens: int | None = 10,
    output_tokens: int | None = 4,
    latency_ms: int | None = 25,
) -> dict[str, Any]:
    return {
        "provider": provider,
        "response_model": response_model,
        "latency_ms": latency_ms,
        "usage": {
            "input": {"total": input_tokens, "cache_read": 2, "cache_write": 1},
            "output": {"total": output_tokens, "reasoning": 3},
        },
    }


def _aigw(
    *,
    capture_status: str = "complete",
    omitted_attempts: int = 0,
    attempts: list[object] | None = None,
    cost: str = "0.25",
) -> dict[str, Any]:
    rows = [_attempt()] if attempts is None else attempts
    return {
        "usage_accounting": {
            "capture_status": capture_status,
            "omitted_attempts": omitted_attempts,
            "attempts": rows,
            "cache": {"status": "miss", "reference": None},
        },
        "request_economics": {
            "direct_cost_status": "complete",
            "known_direct_cost_subtotals": [
                {"amount": cost, "unit": "openrouter_credits", "source": "provider"}
            ],
        },
    }


def _cache(status: CacheStatus | None) -> CacheOutcome:
    return CacheOutcome(status=status, reason=None, key=None, age_s=None)


def test_complete_gateway_evidence_retains_all_exact_fields() -> None:
    accounting = retained_operation_accounting(
        request_model="openrouter/anthropic/claude",
        usage=None,
        aigw=_aigw(attempts=[_attempt(), _attempt(input_tokens=20, latency_ms=35)]),
        cache=_cache("miss"),
    )

    assert accounting.model_dump() == {
        "provider": "openrouter",
        "request_model": "openrouter/anthropic/claude",
        "response_model": "anthropic/claude-served",
        "usage": {
            "input_tokens": 30,
            "output_tokens": 8,
            "cache_read_tokens": 4,
            "cache_creation_tokens": 2,
            "reasoning_tokens": 6,
            "cost_usd": "0.25",
        },
        "provider_latency_ms": 60,
        "cache": {"hits": 0, "misses": 1, "bypasses": 0, "unknown": 0},
    }


def test_partial_or_omitted_gateway_attempts_are_not_presented_as_complete() -> None:
    for aigw in (
        _aigw(capture_status="partial"),
        _aigw(omitted_attempts=1),
    ):
        accounting = retained_operation_accounting(
            request_model="model",
            usage={"prompt_tokens": 99, "completion_tokens": 10},
            aigw=aigw,
            cache=_cache("miss"),
        )

        assert accounting.usage.input_tokens is None
        assert accounting.usage.output_tokens is None
        assert accounting.usage.cache_read_tokens is None
        assert accounting.provider_latency_ms is None


def test_malformed_gateway_attempts_are_not_presented_as_complete() -> None:
    accounting = retained_operation_accounting(
        request_model="model",
        usage={"prompt_tokens": 99, "completion_tokens": 10},
        aigw=_aigw(attempts=[_attempt(), "not an attempt"]),
        cache=_cache("miss"),
    )

    assert accounting.provider is None
    assert accounting.response_model is None
    assert accounting.usage.input_tokens is None
    assert accounting.usage.output_tokens is None
    assert accounting.usage.cost_usd is None
    assert accounting.provider_latency_ms is None


def test_provider_usage_is_the_narrow_fallback_when_gateway_accounting_is_absent() -> None:
    accounting = retained_operation_accounting(
        request_model="anthropic/claude",
        usage={"prompt_tokens": 12, "completion_tokens": 7},
        aigw=None,
        cache=_cache(None),
    )

    assert accounting.provider == "anthropic"
    assert accounting.usage.input_tokens == 12
    assert accounting.usage.output_tokens == 7
    assert accounting.usage.cache_read_tokens is None
    assert accounting.usage.cost_usd is None
    assert accounting.provider_latency_ms is None
    assert accounting.cache.unknown == 1


def test_confirmed_cache_hit_is_zero_current_consumption_not_unknown() -> None:
    accounting = retained_operation_accounting(
        request_model="openrouter/anthropic/claude",
        usage={"prompt_tokens": 999, "completion_tokens": 123},
        aigw=None,
        cache=_cache("hit"),
    )

    assert accounting.usage.model_dump() == {
        "input_tokens": 0,
        "output_tokens": 0,
        "cache_read_tokens": 0,
        "cache_creation_tokens": 0,
        "reasoning_tokens": 0,
        "cost_usd": "0",
    }
    assert accounting.provider_latency_ms == 0
    assert accounting.cache.hits == 1


def test_several_rounds_sum_strictly_and_disagreeing_identity_becomes_unknown() -> None:
    first = retained_operation_accounting(
        request_model="model",
        usage=None,
        aigw=_aigw(cost="0.1"),
        cache=_cache("miss"),
    )
    second = retained_operation_accounting(
        request_model="model",
        usage=None,
        aigw=_aigw(
            cost="0.2",
            attempts=[_attempt(provider="another", response_model="served/elsewhere")],
        ),
        cache=_cache("bypass"),
    )

    combined = combine_operation_accounting([first, second])

    assert combined is not None
    assert combined.provider is None
    assert combined.response_model is None
    assert combined.request_model == "model"
    assert combined.usage.input_tokens == 20
    assert combined.usage.cost_usd == "0.3"
    assert combined.provider_latency_ms == 50
    assert combined.cache.misses == 1
    assert combined.cache.bypasses == 1


def test_unknown_part_poisons_only_its_own_field() -> None:
    known = retained_operation_accounting(
        request_model="model",
        usage=None,
        aigw=_aigw(),
        cache=_cache("miss"),
    )
    partial = retained_operation_accounting(
        request_model="model",
        usage={"prompt_tokens": 8, "completion_tokens": 2},
        aigw=None,
        cache=_cache("bypass"),
    )

    combined = combine_operation_accounting([known, partial])

    assert combined is not None
    assert combined.usage.input_tokens == 18
    assert combined.usage.cost_usd is None
    assert combined.provider_latency_ms is None
    assert combined.cache.misses == 1
    assert combined.cache.bypasses == 1


def test_empty_accounting_collection_has_no_invented_record() -> None:
    assert combine_operation_accounting([]) is None
