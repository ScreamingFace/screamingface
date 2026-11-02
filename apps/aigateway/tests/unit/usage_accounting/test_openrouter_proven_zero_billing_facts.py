"""The 429 zero-insurance proof reads billing facts, not the reply format (OME-1746).

FEATURE: cost of intelligence (OME-1287). Spec: `docs/spec/2026-10-06-OME-1446-proven-zero-retry-
accounting.md`, amendment 2026-10-27.

STORY: as a reader of a board, I see a priced run when a retry was rate limited, even when
OpenRouter changes a field of its error reply.

INVARIANT under test: a field that carries no money (BYOK flags, error codes, the attempt chain,
an absent or odd pipeline, flags and nulls) never makes the cost unknown. A non-zero money value
or billed work, in any field and in any format, does.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest

from aigateway.plugins.openrouter_provider.plugin import OpenRouterProviderPlugin
from aigateway.plugins.taxonomy import ProviderUsageAccountingEvidence

_ZERO = {
    "status": "provider_guaranteed_zero",
    "amount": "0",
    "unit": "openrouter_credits",
    "source": "openrouter.zero_completion_insurance",
}


def _rate_limited(**changes: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "error": {"code": 429, "metadata": {"error_type": "rate_limit_exceeded"}},
        "openrouter_metadata": {"attempt": 1, "is_byok": False, "pipeline": []},
    }
    body.update(changes)
    return body


def _with_router(**changes: Any) -> dict[str, Any]:
    body = _rate_limited()
    body["openrouter_metadata"].update(changes)
    return body


def _supplement(raw_response: dict[str, Any]) -> ProviderUsageAccountingEvidence:
    return OpenRouterProviderPlugin().supplement_chat_usage_accounting(
        evidence=ProviderUsageAccountingEvidence(supported=True),
        raw_response=raw_response,
        http_status=429,
        failed=True,
        request_has_potential_auxiliary_charge=False,
    )


# ── the reply format does not matter (owner decision 2026-10-27) ───────────────────────────────
# Each case below was kept unknown by the OME-1446 tests before this decision.


@pytest.mark.parametrize(
    "raw_response",
    [
        pytest.param(_rate_limited(openrouter_metadata=None), id="no-router-metadata"),
        pytest.param(_with_router(pipeline=None), id="pipeline-null"),
        pytest.param(_with_router(pipeline={}), id="pipeline-not-list"),
        pytest.param(_with_router(pipeline=[{"type": "future_stage"}]), id="unknown-stage"),
        pytest.param(
            _with_router(pipeline=[{"type": "guardrail", "cost_usd": None}]), id="stage-cost-null"
        ),
        pytest.param(
            _with_router(pipeline=[{"type": "guardrail", "cost_usd": {}}]), id="stage-cost-empty"
        ),
        pytest.param(_with_router(attempts=[{"status": 502}, {"status": 429}]), id="mixed-chain"),
        pytest.param(_with_router(attempts=[{"status": "429"}]), id="string-status"),
        pytest.param(_with_router(attempts=[{}]), id="missing-status"),
        pytest.param(_with_router(attempts={}), id="chain-not-list"),
        pytest.param(_with_router(is_byok=None), id="byok-null"),
        pytest.param(_with_router(is_byok="false"), id="byok-text"),
        pytest.param(_with_router(attempt=True), id="attempt-flag"),
        pytest.param(_rate_limited(error={"metadata": {"error_type": "x"}}), id="no-error-code"),
        pytest.param(_rate_limited(error={"code": 500}), id="other-error-code"),
        pytest.param(_rate_limited(error={"code": Decimal("429")}), id="decimal-error-code"),
        pytest.param(
            _rate_limited(error={"code": 429, "metadata": {"error_type": "provider_overloaded"}}),
            id="other-error-type",
        ),
        pytest.param(_rate_limited(usage={"is_byok": True}), id="usage-byok"),
        pytest.param(_rate_limited(usage={"is_byok": None}), id="usage-byok-null"),
        pytest.param(_rate_limited(usage={"is_byok": "false"}), id="usage-byok-text"),
        pytest.param(_rate_limited(usage={"cost": None}), id="usage-cost-null"),
        pytest.param(
            _rate_limited(usage={"future_auxiliary_cost": Decimal("0")}), id="new-zero-cost"
        ),
        pytest.param(_rate_limited(usage={"prompt_tokens": True}), id="prompt-tokens-flag"),
        pytest.param(_rate_limited(usage={"prompt_tokens": 900}), id="prompt-read"),
        pytest.param(_rate_limited(usage={"completion_tokens_details": []}), id="details-empty"),
        pytest.param(_rate_limited(usage={"server_tool_use_details": []}), id="tools-empty"),
        pytest.param(
            _rate_limited(usage={"server_tool_use": {"web_search_requests": None}}),
            id="tool-count-null",
        ),
        pytest.param(
            _rate_limited(usage={"cost_details": {"upstream_inference_cost": {}}}),
            id="cost-detail-empty",
        ),
        pytest.param(_rate_limited(some_new_field={"x": "y"}), id="unknown-top-field"),
    ],
)
def test_a_field_that_carries_no_money_does_not_block_the_insured_zero(
    raw_response: dict[str, Any],
) -> None:
    assert _supplement(raw_response).direct_cost.as_json() == _ZERO


# ── billing facts still keep the cost unknown ───────────────────────────────────────────────────


@pytest.mark.parametrize(
    "raw_response",
    [
        pytest.param(_rate_limited(usage={"completion_tokens": "50"}), id="output-as-text"),
        pytest.param(_rate_limited(usage={"image_generation_requests": 1}), id="new-work-count"),
        pytest.param(_rate_limited(usage={"future_auxiliary_cost": "0.25"}), id="new-cost-text"),
        pytest.param(_rate_limited(usage="free"), id="usage-not-object"),
        pytest.param(
            _with_router(pipeline=[{"type": "plugin", "name": "web"}]), id="paid-stage-type"
        ),
        pytest.param(
            _with_router(region_fees={"amount_usd": Decimal("0.01")}), id="new-amount-field"
        ),
        pytest.param(_rate_limited(choices=[{"message": {"content": "x"}}]), id="output"),
    ],
)
def test_a_money_fact_in_any_field_keeps_the_cost_unknown(raw_response: dict[str, Any]) -> None:
    assert _supplement(raw_response).direct_cost.status == "unavailable"


def test_a_request_with_a_potential_auxiliary_charge_is_still_not_certified() -> None:
    evidence = OpenRouterProviderPlugin().supplement_chat_usage_accounting(
        evidence=ProviderUsageAccountingEvidence(supported=True),
        raw_response=_rate_limited(),
        http_status=429,
        failed=True,
        request_has_potential_auxiliary_charge=True,
    )

    assert evidence.direct_cost.status == "unavailable"
