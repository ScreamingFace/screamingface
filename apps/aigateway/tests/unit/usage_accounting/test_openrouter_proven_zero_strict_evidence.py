"""Ambiguous or unrecognised evidence never certifies OpenRouter insured zero cost."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import httpx
import litellm
import pytest
from litellm.llms.custom_httpx.http_handler import AsyncHTTPHandler

from aigateway.core.retry import RetryPolicy, with_overload_retry
from aigateway.core.usage_accounting.hooks import AccountingAsyncHTTPHandler, _bounded_json
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
