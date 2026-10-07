"""Exact nested shapes required by OpenRouter insured-zero evidence."""

from __future__ import annotations

import copy
import json
from decimal import Decimal
from importlib.resources import files
from typing import Any

import httpx
import pytest
from jsonschema import Draft202012Validator

from aigateway.core.usage_accounting.hooks import _read_body
from aigateway.plugins.openrouter_provider.plugin import OpenRouterProviderPlugin
from aigateway.plugins.taxonomy import RequestAccountingCollector
from aigateway.plugins.taxonomy.render import render_aigw_metadata
from aigateway.routes.chat_accounting import AccountingSession, finalize_provider_evidence

_MODEL = "openrouter/google/gemini-2.0-flash-001"


def _record_for_raw(raw_response: dict[str, Any]):
    collector = RequestAccountingCollector(
        provider="openrouter", requested_model=_MODEL, transport="litellm_async_http"
    )
    collector.begin_dispatch()
    marker = object()
    collector.on_send_admitted(marker)
    collector.on_response_completed(marker, status=429, raw_evidence=raw_response)
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
        final_response=None,
    )
    return collector.records()[0]


@pytest.mark.parametrize(
    "raw_response",
    [
        pytest.param(
            {
                "id": {"amount_usd": Decimal("0.25")},
                "error": {"code": 429, "metadata": {"error_type": "rate_limit_exceeded"}},
                "openrouter_metadata": {"attempt": 1, "is_byok": False, "pipeline": []},
            },
            id="top-level-id-object",
        ),
        pytest.param(
            {
                "error": {
                    "code": 429,
                    "message": {"amount_usd": Decimal("0.25")},
                    "metadata": {"error_type": "rate_limit_exceeded"},
                },
                "openrouter_metadata": {"attempt": 1, "is_byok": False, "pipeline": []},
            },
            id="error-message-object",
        ),
        pytest.param(
            {
                "error": {"code": 429, "metadata": {"error_type": "rate_limit_exceeded"}},
                "openrouter_metadata": {
                    "attempt": 1,
                    "is_byok": False,
                    "pipeline": [],
                    "summary": {"amount_usd": Decimal("0.25")},
                },
            },
            id="router-summary-object",
        ),
        pytest.param(
            {
                "error": {"code": 429, "metadata": {"error_type": "rate_limit_exceeded"}},
                "openrouter_metadata": {"attempt": True, "is_byok": False, "pipeline": []},
            },
            id="router-attempt-bool",
        ),
        pytest.param(
            {
                "error": {"code": 429, "metadata": {"error_type": "rate_limit_exceeded"}},
                "openrouter_metadata": {
                    "attempt": 1,
                    "is_byok": False,
                    "pipeline": [{"type": "guardrail", "summary": {"amount_usd": Decimal("0.25")}}],
                },
            },
            id="pipeline-summary-object",
        ),
        pytest.param(
            {
                "error": {"code": 429, "metadata": {"error_type": "rate_limit_exceeded"}},
                "openrouter_metadata": {
                    "attempt": 1,
                    "is_byok": False,
                    "pipeline": [{"type": "guardrail", "data": {"amount_usd": Decimal("0.25")}}],
                },
            },
            id="pipeline-data-amount",
        ),
        pytest.param(
            {
                "error": {"code": 429, "metadata": {"error_type": "rate_limit_exceeded"}},
                "openrouter_metadata": {
                    "attempt": 1,
                    "is_byok": False,
                    "pipeline": [],
                    "attempts": [{"status": 429, "provider": {"amount_usd": Decimal("0.25")}}],
                },
            },
            id="attempt-provider-object",
        ),
        pytest.param(
            {
                "error": {"code": 429, "metadata": {"error_type": "rate_limit_exceeded"}},
                "openrouter_metadata": {
                    "attempt": 1,
                    "is_byok": False,
                    "pipeline": [],
                    "endpoints": {
                        "total": 1,
                        "available": [
                            {
                                "provider": "OpenAI",
                                "model": "openai/gpt-4o",
                                "selected": False,
                                "amount_usd": Decimal("0.25"),
                            }
                        ],
                    },
                },
            },
            id="endpoint-amount",
        ),
    ],
)
def test_every_accepted_metadata_field_has_an_exact_safe_shape(
    raw_response: dict[str, Any],
) -> None:
    assert _record_for_raw(raw_response).direct_cost.status == "unavailable"


@pytest.mark.asyncio
async def test_duplicate_anthropic_accounting_key_drops_last_wins_evidence() -> None:
    request = httpx.Request("POST", "https://provider.example/v1/messages")
    response = httpx.Response(
        200,
        content=(
            b'{"usage":{"input_tokens":900,"input_tokens":1,"output_tokens":2,'
            b'"cache_read_input_tokens":0,"cache_creation_input_tokens":0}}'
        ),
        request=request,
    )

    raw_evidence, body_completed, evidence_complete = await _read_body(response)

    assert raw_evidence is None
    assert body_completed is True
    assert evidence_complete is False


def test_complete_evidence_keeps_the_previous_supplement_signature_compatible() -> None:
    called = False

    class _OldSignaturePlugin(OpenRouterProviderPlugin):
        def supplement_chat_usage_accounting(
            self,
            *,
            evidence: Any,
            raw_response: Any,
            http_status: Any,
            failed: Any,
            request_has_potential_auxiliary_charge: Any,
        ) -> Any:
            nonlocal called
            called = True
            return evidence

    collector = RequestAccountingCollector(
        provider="openrouter", requested_model=_MODEL, transport="litellm_async_http"
    )
    collector.begin_dispatch()
    marker = object()
    collector.on_send_admitted(marker)
    collector.on_response_completed(marker, status=429, raw_evidence={})
    finalize_provider_evidence(
        AccountingSession(
            provider="openrouter",
            supported=True,
            collector=collector,
            gateway_call_id=collector.gateway_call_id,
            inject_shared_handler=True,
        ),
        plugin=_OldSignaturePlugin(),
        request_body={"model": _MODEL},
        final_response=None,
    )

    assert called is True


@pytest.mark.parametrize(
    "usage",
    [
        pytest.param(
            {"server_tool_use": {"web_search_requests": None}},
            id="server-tool-use-null",
        ),
        pytest.param(
            {"server_tool_use_details": {"tool_calls_executed": None}},
            id="server-tool-details-null",
        ),
    ],
)
def test_unknown_server_tool_counts_are_not_zero(usage: dict[str, Any]) -> None:
    record = _record_for_raw(
        {
            "error": {"code": 429, "metadata": {"error_type": "rate_limit_exceeded"}},
            "openrouter_metadata": {"attempt": 1, "is_byok": False, "pipeline": []},
            "usage": usage,
        }
    )

    assert record.direct_cost.status == "unavailable"


def _insured_metadata() -> dict[str, Any]:
    collector = RequestAccountingCollector(
        provider="openrouter", requested_model=_MODEL, transport="litellm_async_http"
    )
    collector.begin_dispatch()
    marker = object()
    collector.on_send_admitted(marker)
    collector.on_response_completed(
        marker,
        status=429,
        raw_evidence={
            "error": {"code": 429, "metadata": {"error_type": "rate_limit_exceeded"}},
            "openrouter_metadata": {"attempt": 1, "is_byok": False, "pipeline": []},
        },
    )
    session = AccountingSession(
        provider="openrouter",
        supported=True,
        collector=collector,
        gateway_call_id=collector.gateway_call_id,
        inject_shared_handler=True,
    )
    finalize_provider_evidence(
        session,
        plugin=OpenRouterProviderPlugin(),
        request_body={"model": _MODEL},
        final_response=None,
    )
    return render_aigw_metadata(
        collector=collector,
        supported=True,
        cache_status="miss",
        gateway_call_id=collector.gateway_call_id,
    )


def test_every_direct_cost_status_requires_its_matching_attempt_marker() -> None:
    schema = json.loads(
        files("aigateway.plugins.taxonomy")
        .joinpath("usage_accounting.schema.json")
        .read_text(encoding="utf-8")
    )
    validator = Draft202012Validator(schema)
    direct_costs = {
        "reported": {"status": "reported", "amount": "0", "unit": "credits", "source": "s"},
        "provider_guaranteed_zero": {
            "status": "provider_guaranteed_zero",
            "amount": "0",
            "unit": "credits",
            "source": "s",
        },
        "absent": {"status": "absent", "amount": None, "unit": None, "source": None},
        "unavailable": {
            "status": "unavailable",
            "amount": None,
            "unit": None,
            "source": None,
        },
        "invalid": {"status": "invalid", "amount": None, "unit": None, "source": None},
        "unit_unknown": {
            "status": "unit_unknown",
            "amount": "0",
            "unit": None,
            "source": "s",
        },
        "archive_matched": {
            "status": "archive_matched",
            "amount": "0",
            "unit": "credits",
            "source": "s",
        },
    }

    for status, direct_cost in direct_costs.items():
        for marker in ("aigw.provider_attempt", "aigw.provider_attempt.v2"):
            metadata = copy.deepcopy(_insured_metadata())
            attempt = metadata["usage_accounting"]["attempts"][0]
            attempt["schema"] = marker
            attempt["direct_cost"] = direct_cost
            is_valid = not list(validator.iter_errors(metadata))
            expected = marker.endswith(".v2") == (status == "provider_guaranteed_zero")

            assert is_valid is expected, (status, marker)


def test_metadata_rich_insured_error_remains_certifiable() -> None:
    record = _record_for_raw(
        {
            "id": "gen-rate-limit",
            "model": "google/gemini-2.0-flash-001",
            "object": "chat.completion",
            "created": 1,
            "service_tier": "default",
            "system_fingerprint": None,
            "error": {
                "code": 429,
                "message": "rate limited",
                "metadata": {"error_type": "rate_limit_exceeded"},
            },
            "openrouter_metadata": {
                "requested": _MODEL,
                "strategy": "direct",
                "region": "iad",
                "summary": "available=1",
                "attempt": 1,
                "is_byok": False,
                "endpoints": {
                    "total": 1,
                    "available": [
                        {
                            "provider": "Google",
                            "model": "google/gemini-2.0-flash-001",
                            "selected": False,
                        }
                    ],
                },
                "pipeline": [
                    {
                        "type": "guardrail",
                        "name": "safe-guardrail",
                        "guardrail_id": "grd_test",
                        "guardrail_scope": "api-key",
                        "summary": "passed",
                        "cost_usd": Decimal("0"),
                    }
                ],
                "attempts": [
                    {"provider": "Google", "model": "gemini-2.0-flash-001", "status": 429}
                ],
            },
            "usage": {
                "prompt_tokens": 12,
                "completion_tokens": 0,
                "total_tokens": 12,
                "output_tokens": 0,
                "prompt_tokens_details": {
                    "audio_tokens": 0,
                    "cache_write_tokens": 0,
                    "cached_tokens": 0,
                    "video_tokens": 0,
                },
                "completion_tokens_details": {
                    "accepted_prediction_tokens": 0,
                    "audio_tokens": 0,
                    "reasoning_tokens": 0,
                    "rejected_prediction_tokens": 0,
                },
                "is_byok": False,
                "cost_details": {
                    "server_tool_cost": Decimal("0"),
                    "upstream_inference_cost": None,
                    "upstream_inference_input_cost": Decimal("0"),
                    "upstream_inference_output_cost": Decimal("0"),
                    "upstream_inference_prompt_cost": Decimal("0"),
                    "upstream_inference_completions_cost": Decimal("0"),
                },
                "server_tool_use": {"web_search_requests": 0},
                "server_tool_use_details": {
                    "tool_calls_executed": 0,
                    "tool_calls_requested": 0,
                },
            },
        }
    )

    assert record.direct_cost.status == "provider_guaranteed_zero"
