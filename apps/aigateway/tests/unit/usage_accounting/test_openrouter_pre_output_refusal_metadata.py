"""The pre-output refusal proof reads billing facts, not the reply format (spec 2026-10-26 §8).

FEATURE: cost of intelligence (OME-1287). The gateway sends `X-OpenRouter-Metadata: enabled` on
every OpenRouter call, so a prod refusal also carries `openrouter_metadata`. The first proof
accepted only known fields, so it rejected every prod refusal and the $0 rule never applied.

STORY: as a reader of the lab_bench board, I see a cost for a run of a model that refused some
questions, instead of "—".

INVARIANT under test: a new or changed field that carries no money never makes the cost unknown;
a non-zero money field anywhere does.
"""

from __future__ import annotations

import copy
import json
from decimal import Decimal
from importlib.resources import files
from typing import Any

import pytest
from jsonschema import Draft202012Validator

from aigateway.plugins.openrouter_provider.plugin import OpenRouterProviderPlugin
from aigateway.plugins.taxonomy import ProviderUsageAccountingEvidence, RequestAccountingCollector
from aigateway.plugins.taxonomy.render import render_aigw_metadata
from aigateway.routes.chat_accounting import AccountingSession, finalize_provider_evidence

_MODEL = "openrouter/anthropic/claude-opus-5.5"
_ZERO = {
    "status": "provider_guaranteed_zero",
    "amount": "0",
    "unit": "openrouter_credits",
    "source": "openrouter.pre_output_refusal",
}


def _endpoint(provider: str, *, selected: bool = False) -> dict[str, Any]:
    return {
        "provider": provider,
        "model": "anthropic/claude-opus-5.5-20260921",
        "selected": selected,
    }


# The full body of the live call with the gateway's headers (LitQA2 row 0, 2026-10-27).
_PROD_REFUSAL: dict[str, Any] = {
    "id": "gen-1793107791-i0G3CN4KOeVq0zLky3qi",
    "object": "chat.completion",
    "created": 1793107791,
    "model": "anthropic/claude-opus-5.5",
    "provider": "Claude Platform on AWS",
    "system_fingerprint": None,
    "service_tier": None,
    "choices": [
        {
            "index": 0,
            "logprobs": None,
            "finish_reason": "content_filter",
            "native_finish_reason": "refusal",
            "message": {"role": "assistant", "content": None, "refusal": None, "reasoning": None},
        }
    ],
    "openrouter_metadata": {
        "requested": "anthropic/claude-opus-5.5",
        "strategy": "direct",
        "region": "EZE",
        "summary": "available=5, selected=Claude Platform on AWS",
        "attempt": 1,
        "is_byok": False,
        "endpoints": {
            "total": 11,
            "available": [
                _endpoint("Claude Platform on AWS", selected=True),
                _endpoint("Amazon Bedrock"),
                _endpoint("Anthropic"),
                _endpoint("Google"),
                _endpoint("Azure"),
            ],
        },
        "generation_time": 2479,
    },
}


def _with_metadata(**changes: Any) -> dict[str, Any]:
    body = copy.deepcopy(_PROD_REFUSAL)
    body["openrouter_metadata"].update(changes)
    return body


def _without_metadata_field(name: str) -> dict[str, Any]:
    body = copy.deepcopy(_PROD_REFUSAL)
    del body["openrouter_metadata"][name]
    return body


def _supplement(raw_response: dict[str, Any]) -> ProviderUsageAccountingEvidence:
    return OpenRouterProviderPlugin().supplement_chat_usage_accounting(
        evidence=ProviderUsageAccountingEvidence(supported=True),
        raw_response=raw_response,
        http_status=200,
        failed=False,
        request_has_potential_auxiliary_charge=False,
    )


def _finalized(raw_response: dict[str, Any]) -> RequestAccountingCollector:
    collector = RequestAccountingCollector(
        provider="openrouter",
        requested_model=_MODEL,
        transport="litellm_async_http",
    )
    collector.begin_dispatch()
    marker = object()
    collector.on_send_admitted(marker)
    collector.on_response_completed(marker, status=200, raw_evidence=raw_response)
    finalize_provider_evidence(
        AccountingSession(
            provider="openrouter",
            supported=True,
            collector=collector,
            gateway_call_id=collector.gateway_call_id,
            inject_shared_handler=True,
        ),
        plugin=OpenRouterProviderPlugin(),
        request_body={"model": _MODEL},
        # WHY the stripped body: the plugin removes `openrouter_metadata` before the caller and
        # the cache see the reply (plugin.py), so the converted response never carries it.
        final_response={k: v for k, v in raw_response.items() if k != "openrouter_metadata"},
    )
    return collector


# ── the prod shape is certified ────────────────────────────────────────────────────────────────


def test_the_prod_refusal_with_router_metadata_is_a_certified_zero() -> None:
    assert _supplement(copy.deepcopy(_PROD_REFUSAL)).direct_cost.as_json() == _ZERO


def test_the_prod_refusal_is_certified_end_to_end_and_the_metadata_is_schema_valid() -> None:
    collector = _finalized(copy.deepcopy(_PROD_REFUSAL))

    (attempt,) = collector.records()
    assert attempt.direct_cost.as_json() == _ZERO
    metadata = render_aigw_metadata(
        collector=collector,
        supported=True,
        cache_status="miss",
        gateway_call_id=collector.gateway_call_id,
    )
    assert metadata["request_economics"]["succeeded_attempt_direct_cost"] == _ZERO
    schema = json.loads(
        files("aigateway.plugins.taxonomy")
        .joinpath("usage_accounting.schema.json")
        .read_text(encoding="utf-8")
    )
    Draft202012Validator(schema).validate(metadata)


@pytest.mark.parametrize(
    "optional",
    ["requested", "strategy", "region", "summary", "attempt", "endpoints", "generation_time"],
)
def test_each_informational_metadata_field_may_be_absent(optional: str) -> None:
    assert _supplement(_without_metadata_field(optional)).direct_cost.as_json() == _ZERO


# ── the reply format does not matter (owner decision 2026-10-27) ──────────────────────────────


def _with_top_level(**changes: Any) -> dict[str, Any]:
    return {**copy.deepcopy(_PROD_REFUSAL), **changes}


@pytest.mark.parametrize(
    "raw_response",
    [
        pytest.param(_with_metadata(is_byok=True), id="byok"),
        pytest.param(_without_metadata_field("is_byok"), id="byok-absent"),
        pytest.param(_with_metadata(is_byok=None), id="byok-null"),
        pytest.param(_with_metadata(is_byok="false"), id="byok-not-bool"),
        pytest.param(
            _with_metadata(pipeline=[{"type": "guardrail", "name": "pii"}]), id="pipeline"
        ),
        pytest.param(
            _with_metadata(attempts=[{"provider": "Anthropic", "status": 200}]), id="attempts"
        ),
        pytest.param(_with_metadata(some_new_field=1), id="unknown-metadata-field"),
        pytest.param(_with_metadata(attempt=-1), id="negative-attempt"),
        pytest.param(_with_metadata(generation_time="2479"), id="string-generation-time"),
        pytest.param(_with_metadata(summary=3), id="summary-not-string"),
        pytest.param(_with_metadata(endpoints={"total": 1}), id="endpoints-incomplete"),
        pytest.param(_with_top_level(openrouter_metadata="enabled"), id="metadata-not-object"),
        pytest.param(_with_top_level(openrouter_metadata=None), id="metadata-null"),
        # The two cases that the OME-1738 tests kept unknown before this decision.
        pytest.param(_with_top_level(openrouter_metadata={"pipeline": []}), id="pipeline-only"),
        pytest.param(_with_top_level(created="yesterday"), id="bad-created"),
        pytest.param(_with_top_level(some_new_top_level_field={"x": 1}), id="unknown-top-field"),
    ],
)
def test_a_field_that_carries_no_money_does_not_change_the_certified_zero(
    raw_response: dict[str, Any],
) -> None:
    assert _supplement(raw_response).direct_cost.as_json() == _ZERO


# ── billing facts still keep the cost unknown ───────────────────────────────────────────────────


@pytest.mark.parametrize(
    "raw_response",
    [
        pytest.param(
            _with_metadata(pipeline=[{"type": "guardrail", "cost_usd": Decimal("0.01")}]),
            id="pipeline-stage-cost",
        ),
        pytest.param(
            _with_metadata(pipeline=[{"type": "guardrail", "cost_usd": "0.01"}]),
            id="pipeline-stage-cost-as-text",
        ),
        pytest.param(_with_metadata(cost_usd=Decimal("0.25")), id="metadata-cost"),
        pytest.param(
            _with_top_level(billing={"amount_usd": Decimal("0.25")}), id="unknown-amount-field"
        ),
        pytest.param(_with_top_level(usage={"prompt_tokens": 120}), id="usage"),
        pytest.param(_with_top_level(error={"code": 400}), id="error"),
    ],
)
def test_a_money_fact_anywhere_in_the_reply_keeps_the_cost_unknown(
    raw_response: dict[str, Any],
) -> None:
    assert _supplement(raw_response).direct_cost.status == "unavailable"


def test_a_zero_money_field_does_not_block_the_certified_zero() -> None:
    body = _with_metadata(pipeline=[{"type": "guardrail", "cost_usd": Decimal("0")}])

    assert _supplement(body).direct_cost.as_json() == _ZERO
