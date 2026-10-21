"""Golden handoff tests for the evolving OME-303 accounting contract."""

from __future__ import annotations

from typing import Any

from aigateway.plugins.anthropic_provider.usage_accounting import (
    normalize_anthropic_usage_accounting,
)
from aigateway.plugins.taxonomy import (
    CacheReference,
    DirectCost,
    InputTokenUsage,
    OutputTokenUsage,
    PricingContext,
    ProviderAttemptRecord,
    TokenUsage,
)
from aigateway.plugins.taxonomy.render import render_aigw_metadata

_ATTEMPT_ID = "attempt_" + "1" * 32
_CALL_ID = "call_" + "1" * 32


class _Collector:
    def __init__(self, records: tuple[ProviderAttemptRecord, ...]) -> None:
        self._records = records

    def records(self) -> tuple[ProviderAttemptRecord, ...]:
        return self._records

    def status(self) -> str:
        return "complete"


def _attempt(**overrides: Any) -> ProviderAttemptRecord:
    values: dict[str, Any] = {
        "attempt_id": _ATTEMPT_ID,
        "sequence": 1,
        "dispatch_index": 1,
        "attempt_index": 1,
        "provider": "openrouter",
        "transport": "litellm_async_http",
        "outcome": "succeeded",
        "usage": TokenUsage(
            status="complete",
            source="provider_raw_response",
            input=InputTokenUsage(total=12, uncached=10, cache_read=2),
            output=OutputTokenUsage(total=5, reasoning=1),
        ),
        "pricing_context": PricingContext(),
        "direct_cost": DirectCost.reported(
            amount="0.0012",
            unit="openrouter_credits",
            source="openrouter.usage.cost",
        ),
    }
    values.update(overrides)
    return ProviderAttemptRecord(**values)


def test_wire_uses_attempt_semantics_and_separate_evidence_statuses() -> None:
    metadata = render_aigw_metadata(
        collector=_Collector((_attempt(),)),
        supported=True,
        cache_status="miss",
        gateway_call_id=_CALL_ID,
    )

    accounting = metadata["usage_accounting"]
    assert "provider_calls" not in accounting
    assert accounting["capture_status"] == "complete"
    assert accounting["observed_attempts"] == 1
    assert accounting["omitted_attempts"] == 0
    attempt = accounting["attempts"][0]
    assert attempt["attempt_id"] == _ATTEMPT_ID
    assert attempt["attempt_index"] == 1
    assert attempt["usage"]["input"] == {
        "total": 12,
        "uncached": 10,
        "cache_read": 2,
        "cache_write": None,
        "cache_write_by_ttl": [],
    }
    assert attempt["usage"]["output"] == {"total": 5, "reasoning": 1}
    assert attempt["direct_cost"]["status"] == "reported"
    assert "evidence_complete" not in attempt

    economics = metadata["request_economics"]
    assert economics == {
        "schema": "aigw.request_economics",
        "observed_new_attempts": 1,
        "direct_cost_status": "complete",
        "known_direct_cost_subtotals": [
            {
                "amount": "0.0012",
                "unit": "openrouter_credits",
                "source": "openrouter.usage.cost",
            }
        ],
        "succeeded_attempt_direct_cost": {
            "status": "reported",
            "amount": "0.0012",
            "unit": "openrouter_credits",
            "source": "openrouter.usage.cost",
        },
    }


def test_anthropic_raw_usage_is_inclusive_and_pricing_context_is_canonical() -> None:
    evidence = normalize_anthropic_usage_accounting(
        request_body={"model": "anthropic/claude"},
        raw_response={
            "id": "msg_1",
            "model": "claude-haiku-4-5",
            "usage": {
                "input_tokens": 100,
                "output_tokens": 25,
                "cache_creation_input_tokens": 10,
                "cache_read_input_tokens": 20,
                "cache_creation": {
                    "ephemeral_5m_input_tokens": 7,
                    "ephemeral_1h_input_tokens": 3,
                },
                "output_tokens_details": {"thinking_tokens": 7},
                "service_tier": "standard",
            },
        },
        final_response=None,
    )

    assert evidence.usage.input.total == 130
    assert evidence.usage.input.uncached == 100
    assert evidence.usage.input.cache_read == 20
    assert evidence.usage.input.cache_write == 10
    assert [row.as_json() for row in evidence.usage.input.cache_write_by_ttl] == [
        {"ttl_seconds": 300, "tokens": 7},
        {"ttl_seconds": 3600, "tokens": 3},
    ]
    assert evidence.usage.output.total == 25
    assert evidence.usage.output.reasoning == 7
    assert evidence.usage.status == "complete"
    assert evidence.pricing_context.service_tier == "standard"
    assert evidence.direct_cost.status == "absent"


def test_cache_hit_is_reference_evidence_not_counterfactual_savings() -> None:
    reference = CacheReference(
        usage=TokenUsage(
            status="partial",
            source="cached_converted_response",
            input=InputTokenUsage(total=12),
            output=OutputTokenUsage(total=5),
        ),
        direct_cost=DirectCost.reported(
            amount="0.0012",
            unit="openrouter_credits",
            source="cached_response.usage.cost",
        ),
    )
    metadata = render_aigw_metadata(
        collector=None,
        supported=True,
        cache_status="hit",
        gateway_call_id=_CALL_ID,
        cache_reference=reference,
    )

    accounting = metadata["usage_accounting"]
    assert accounting["attempts"] == []
    assert accounting["cache"]["reference"]["coverage"] == "final_successful_response_only"
    assert accounting["cache"]["reference"]["incurred_in_current_request"] is False
    assert "avoided_cost" not in str(metadata)
    assert metadata["request_economics"]["observed_new_attempts"] == 0
    assert metadata["request_economics"]["direct_cost_status"] == "not_applicable"
