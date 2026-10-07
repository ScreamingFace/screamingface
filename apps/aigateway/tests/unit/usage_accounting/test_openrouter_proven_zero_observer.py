"""Installed transport path for OpenRouter zero-completion insurance evidence."""

from __future__ import annotations

from typing import Any

import httpx
import litellm
import pytest
from litellm.llms.custom_httpx.http_handler import AsyncHTTPHandler

from aigateway.core.retry import RetryPolicy, with_overload_retry
from aigateway.core.usage_accounting.hooks import AccountingAsyncHTTPHandler
from aigateway.core.usage_accounting.signals import bound_collector
from aigateway.plugins.openrouter_provider.plugin import OpenRouterProviderPlugin
from aigateway.plugins.taxonomy import RequestAccountingCollector
from aigateway.plugins.taxonomy.render import render_aigw_metadata
from aigateway.routes.chat_accounting import AccountingSession, finalize_provider_evidence

_MODEL = "openrouter/google/gemini-2.0-flash-001"


@pytest.mark.asyncio
async def test_observer_retry_and_renderer_preserve_only_the_reported_subtotal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    insured_error = {
        "error": {
            "code": 429,
            "metadata": {"error_type": "rate_limit_exceeded"},
        },
        "openrouter_metadata": {"attempt": 1, "is_byok": False, "pipeline": []},
    }
    success = {
        "id": "gen-success",
        "model": "google/gemini-2.0-flash-001",
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": "ok"},
                "finish_reason": "stop",
            }
        ],
        "usage": {
            "prompt_tokens": 5,
            "completion_tokens": 2,
            "total_tokens": 7,
            "cost": 0.02,
        },
    }
    responses = [(429, insured_error), (200, success)]
    seen_headers: list[httpx.Headers] = []

    def _transport(
        ssl_context: Any = None,
        ssl_verify: Any = None,
        shared_session: Any = None,
    ) -> httpx.MockTransport:
        del ssl_context, ssl_verify, shared_session

        async def _respond(request: httpx.Request) -> httpx.Response:
            seen_headers.append(request.headers)
            status, payload = responses[len(seen_headers) - 1]
            return httpx.Response(status, json=payload)

        return httpx.MockTransport(_respond)

    monkeypatch.setattr(AsyncHTTPHandler, "_create_async_transport", staticmethod(_transport))
    handler = AccountingAsyncHTTPHandler()
    collector = RequestAccountingCollector(
        provider="openrouter",
        requested_model=_MODEL,
        transport="litellm_async_http",
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

    assert len(seen_headers) == 2
    assert all(headers["x-openrouter-metadata"] == "enabled" for headers in seen_headers)
    first_raw_response = collector.open_records()[0][1]
    assert first_raw_response is not None
    assert first_raw_response["openrouter_metadata"] == insured_error["openrouter_metadata"]
    attempts = collector.records()
    assert [attempt.http_status for attempt in attempts] == [429, 200]
    assert [attempt.outcome for attempt in attempts] == ["provider_error", "succeeded"]
    assert [attempt.direct_cost.status for attempt in attempts] == [
        "provider_guaranteed_zero",
        "reported",
    ]
    assert attempts[1].direct_cost.amount == "0.02"

    economics = render_aigw_metadata(
        collector=collector,
        supported=True,
        cache_status="miss",
        gateway_call_id=collector.gateway_call_id,
    )["request_economics"]
    assert economics["direct_cost_status"] == "complete"
    assert economics["known_direct_cost_subtotals"] == [
        {
            "amount": "0.02",
            "unit": "openrouter_credits",
            "source": "openrouter.usage.cost",
        }
    ]
