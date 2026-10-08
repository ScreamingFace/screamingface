"""Ambiguous or unrecognised evidence never certifies OpenRouter insured zero cost."""

from __future__ import annotations

import json
from decimal import Decimal
from importlib.resources import files
from typing import Any, cast

import httpx
import litellm
import pytest
from jsonschema import Draft202012Validator
from litellm.llms.custom_httpx.http_handler import AsyncHTTPHandler

from aigateway.core.retry import RetryPolicy, with_overload_retry
from aigateway.core.usage_accounting.hooks import (
    AccountingAsyncHTTPHandler,
    _bounded_json,
    _read_body,
)
from aigateway.core.usage_accounting.signals import bound_collector
from aigateway.plugins.openrouter_provider.plugin import OpenRouterProviderPlugin
from aigateway.plugins.taxonomy import RequestAccountingCollector
from aigateway.plugins.taxonomy.render import render_aigw_metadata
from aigateway.routes.chat_accounting import AccountingSession, finalize_provider_evidence

_MODEL = "openrouter/google/gemini-2.0-flash-001"

# WHY raw bytes: a dict literal cannot carry a duplicate key, and the defect is that the
# last occurrence silently wins — hiding `is_byok: true` and a reported cost here.
_DUPLICATE_KEY_INSURED_ERROR = (
    b'{"error": {"code": 429, "metadata": {"error_type": "rate_limit_exceeded"}},'
    b' "openrouter_metadata": {"attempt": 1, "is_byok": true, "is_byok": false,'
    b' "pipeline": []},'
    b' "usage": {"cost": 0.4}, "usage": {}}'
)


@pytest.mark.parametrize(
    "payload",
    [
        pytest.param(b'{"a": 1, "a": 2}', id="top-level"),
        pytest.param(b'{"a": {"b": 1, "b": 2}}', id="nested-object"),
        pytest.param(b'{"a": [{"b": 1, "b": 2}]}', id="object-in-array"),
        pytest.param(_DUPLICATE_KEY_INSURED_ERROR, id="insured-error"),
    ],
)
def test_duplicate_json_keys_at_any_depth_are_not_raw_evidence(payload: bytes) -> None:
    # INVARIANT: an ambiguous body is not evidence; last-key-wins must never pick for us.
    assert _bounded_json(payload) is None


def test_distinct_keys_still_parse_with_exact_decimals() -> None:
    assert _bounded_json(b'{"a": {"b": 1}, "c": [{"b": 0.4}]}') == {
        "a": {"b": 1},
        "c": [{"b": Decimal("0.4")}],
    }


@pytest.mark.asyncio
async def test_duplicate_key_insured_error_does_not_complete_the_retried_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    success = {
        "id": "gen-success",
        "model": "google/gemini-2.0-flash-001",
        "choices": [
            {"index": 0, "message": {"role": "assistant", "content": "ok"}, "finish_reason": "stop"}
        ],
        "usage": {"prompt_tokens": 5, "completion_tokens": 2, "total_tokens": 7, "cost": 0.02},
    }
    calls: list[int] = []

    def _transport(
        ssl_context: Any = None, ssl_verify: Any = None, shared_session: Any = None
    ) -> httpx.MockTransport:
        del ssl_context, ssl_verify, shared_session

        async def _respond(_request: httpx.Request) -> httpx.Response:
            calls.append(1)
            if len(calls) == 1:
                return httpx.Response(
                    429,
                    content=_DUPLICATE_KEY_INSURED_ERROR,
                    headers={"content-type": "application/json"},
                )
            return httpx.Response(200, json=success)

        return httpx.MockTransport(_respond)

    monkeypatch.setattr(AsyncHTTPHandler, "_create_async_transport", staticmethod(_transport))
    handler = AccountingAsyncHTTPHandler()
    collector = RequestAccountingCollector(
        provider="openrouter", requested_model=_MODEL, transport="litellm_async_http"
    )

    async def _dispatch() -> Any:
        collector.begin_dispatch()
        with bound_collector(collector):
            return await litellm.acompletion(
                model=_MODEL,
                api_key="test-key",
                api_base="https://provider.example/v1",
                extra_headers={"X-OpenRouter-Metadata": "enabled"},
                client=handler,
                num_retries=0,
                max_retries=0,
                caching=False,
                cache={"no-cache": True, "no-store": True},
            )

    try:
        result = await with_overload_retry(
            _dispatch,
            policy=RetryPolicy(
                max_retries=1,
                backoff_base_seconds=0,
                backoff_max_seconds=0,
                max_total_wait_seconds=1,
                jitter_seconds=0,
            ),
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
            final_response=result.model_dump(),
        )
    finally:
        await handler.close()

    attempts = collector.records()
    assert [attempt.direct_cost.status for attempt in attempts] == ["unavailable", "reported"]
    economics = render_aigw_metadata(
        collector=collector,
        supported=True,
        cache_status="miss",
        gateway_call_id=collector.gateway_call_id,
    )["request_economics"]
    assert economics["direct_cost_status"] != "complete"


def _record_for(usage: dict[str, Any]):
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
            "usage": usage,
        },
    )
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
    "usage",
    [
        # WHY: the documented home of server_tool_cost is usage.cost_details; one found
        # anywhere else is a shape we do not understand, not a shape we may ignore.
        pytest.param({"server_tool_cost": Decimal("0.25")}, id="misplaced-server-tool-cost"),
        pytest.param({"future_auxiliary_cost": Decimal("1")}, id="unknown-cost-field"),
        pytest.param({"future_auxiliary_cost": Decimal("0")}, id="unknown-zero-cost-field"),
        pytest.param({"image_generation_requests": 1}, id="unknown-tool-field"),
        pytest.param({"cost": None}, id="null-cost"),
    ],
)
def test_unrecognised_usage_fields_prevent_zero_certification(usage: dict[str, Any]) -> None:
    # INVARIANT: zero certification is an allowlist argument — anything outside the known
    # ChatUsage shape fails closed instead of being skipped.
    assert _record_for(usage).direct_cost.status == "unavailable"


def test_known_zero_usage_shape_still_certifies() -> None:
    record = _record_for(
        {
            "prompt_tokens": 12,
            "completion_tokens": 0,
            "total_tokens": 12,
            "is_byok": False,
            "prompt_tokens_details": {"cached_tokens": 0},
            "completion_tokens_details": {"reasoning_tokens": 0},
            "server_tool_use_details": {"tool_calls_executed": 0, "tool_calls_requested": 0},
            "cost_details": {"server_tool_cost": Decimal("0")},
        }
    )

    assert record.direct_cost.status == "provider_guaranteed_zero"


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
                "error": {"code": 429, "metadata": {"error_type": "rate_limit_exceeded"}},
                "openrouter_metadata": {"attempt": 1, "is_byok": False, "pipeline": []},
                "usage": {"prompt_tokens_details": {"server_tool_cost": Decimal("0.25")}},
            },
            id="nested-prompt-detail-cost",
        ),
        pytest.param(
            {
                "error": {"code": 429, "metadata": {"error_type": "rate_limit_exceeded"}},
                "openrouter_metadata": {"attempt": 1, "is_byok": False, "pipeline": []},
                "usage": {"prompt_tokens": True},
            },
            id="boolean-prompt-tokens",
        ),
        pytest.param(
            {
                "error": {"code": 429, "metadata": {"error_type": "rate_limit_exceeded"}},
                "openrouter_metadata": {"attempt": 1, "is_byok": False, "pipeline": []},
                "usage": {"total_tokens": {"cost": Decimal("0.25")}},
            },
            id="malformed-total-tokens",
        ),
        pytest.param(
            {
                "error": {"code": 429, "metadata": {"error_type": "rate_limit_exceeded"}},
                "openrouter_metadata": {
                    "attempt": 1,
                    "is_byok": False,
                    "pipeline": [{"type": "guardrail", "server_tool_cost": Decimal("0.25")}],
                },
            },
            id="pipeline-extra-cost",
        ),
        pytest.param(
            {
                "error": {"code": 429, "metadata": {"error_type": "rate_limit_exceeded"}},
                "openrouter_metadata": {
                    "attempt": 1,
                    "is_byok": False,
                    "pipeline": [],
                    "attempts": [{"status": 429, "cost_usd": Decimal("0.25")}],
                },
            },
            id="attempt-extra-cost",
        ),
        pytest.param(
            {
                "error": {"code": 429, "metadata": {"error_type": "rate_limit_exceeded"}},
                "openrouter_metadata": {
                    "attempt": 1,
                    "is_byok": False,
                    "pipeline": [],
                    "cost_usd": Decimal("0.25"),
                },
            },
            id="router-metadata-cost",
        ),
        pytest.param(
            {
                "error": {
                    "code": 429,
                    "metadata": {
                        "error_type": "rate_limit_exceeded",
                        "server_tool_cost": Decimal("0.25"),
                    },
                },
                "openrouter_metadata": {"attempt": 1, "is_byok": False, "pipeline": []},
            },
            id="error-metadata-cost",
        ),
    ],
)
def test_nested_or_metadata_charge_evidence_prevents_zero_certification(
    raw_response: dict[str, Any],
) -> None:
    assert _record_for_raw(raw_response).direct_cost.status == "unavailable"


@pytest.mark.asyncio
async def test_unrelated_duplicate_key_preserves_measured_cost_but_not_completeness(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = (
        b'{"id":"gen-duplicate","model":"google/gemini-2.0-flash-001",'
        b'"choices":[{"index":0,"message":{"role":"assistant","content":"ok"},'
        b'"finish_reason":"stop"}],"meta":{"x":1,"x":1},'
        b'"usage":{"prompt_tokens":1,"completion_tokens":1,"total_tokens":2,"cost":0.02}}'
    )

    def _transport(
        ssl_context: Any = None, ssl_verify: Any = None, shared_session: Any = None
    ) -> httpx.MockTransport:
        del ssl_context, ssl_verify, shared_session

        async def _respond(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200, content=payload, headers={"content-type": "application/json"}
            )

        return httpx.MockTransport(_respond)

    monkeypatch.setattr(AsyncHTTPHandler, "_create_async_transport", staticmethod(_transport))
    handler = AccountingAsyncHTTPHandler()
    collector = RequestAccountingCollector(
        provider="openrouter", requested_model=_MODEL, transport="litellm_async_http"
    )
    try:
        collector.begin_dispatch()
        with bound_collector(collector):
            response = await litellm.acompletion(
                model=_MODEL,
                api_key="test-key",
                api_base="https://provider.example/v1",
                client=handler,
                num_retries=0,
                max_retries=0,
                caching=False,
                cache={"no-cache": True, "no-store": True},
            )
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
            final_response=cast(Any, response).model_dump(),
        )
    finally:
        await handler.close()

    (attempt,) = collector.records()
    assert attempt.direct_cost.status == "reported"
    assert attempt.direct_cost.amount == "0.02"
    economics = render_aigw_metadata(
        collector=collector,
        supported=True,
        cache_status="miss",
        gateway_call_id=collector.gateway_call_id,
    )["request_economics"]
    assert economics["direct_cost_status"] == "partial"
    assert economics["known_direct_cost_subtotals"] == []


def test_guaranteed_zero_uses_a_versioned_attempt_schema() -> None:
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
    metadata = render_aigw_metadata(
        collector=collector,
        supported=True,
        cache_status="miss",
        gateway_call_id=collector.gateway_call_id,
    )
    schema = json.loads(
        files("aigateway.plugins.taxonomy")
        .joinpath("usage_accounting.schema.json")
        .read_text(encoding="utf-8")
    )

    assert schema["$id"].endswith("aigw-usage-accounting.v2.json")
    assert metadata["usage_accounting"]["attempts"][0]["schema"] == "aigw.provider_attempt.v2"
    Draft202012Validator(schema).validate(metadata)


@pytest.mark.asyncio
async def test_duplicate_cost_key_drops_ambiguous_raw_money() -> None:
    request = httpx.Request("POST", "https://provider.example/v1/chat/completions")
    response = httpx.Response(
        200,
        content=b'{"usage":{"cost":0.4,"cost":0.2}}',
        request=request,
    )

    raw_evidence, body_completed, evidence_complete = await _read_body(response)

    assert raw_evidence is None
    assert body_completed is True
    assert evidence_complete is False
