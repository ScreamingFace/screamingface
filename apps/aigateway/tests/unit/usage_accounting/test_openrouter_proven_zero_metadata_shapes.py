"""Exact nested shapes required by OpenRouter insured-zero evidence."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import httpx
import pytest

from aigateway.core.usage_accounting.hooks import _read_body
from aigateway.plugins.openrouter_provider.plugin import OpenRouterProviderPlugin
from aigateway.plugins.taxonomy import RequestAccountingCollector
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
