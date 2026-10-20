"""OME-1686 — the successful attempt's cost and usage, end to end through real gateway seams.

FEATURE: cost of intelligence (spec ``docs/spec/2026-10-20-OME-1686-succeeded-attempt-cost.md``).
STORY: as an Engine maintainer I price a call from ``succeeded_attempt_direct_cost`` and take
its tokens from ``succeeded_attempt_usage``. Both must be right where the real collector, the
OpenRouter mapper, the chat route's retry loop, the request cache and frozen-copy replay meet,
not only in the pure renderer.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any
from unittest.mock import patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from litellm.exceptions import RateLimitError

from aigateway.core.usage_accounting import active_collector
from aigateway.plugins.openrouter_provider.plugin import OpenRouterProviderPlugin
from aigateway.plugins.taxonomy import RequestAccountingCollector
from aigateway.plugins.taxonomy.render import render_aigw_metadata
from aigateway.routes.chat_accounting import AccountingSession, finalize_provider_evidence
from tests.unit.test_frozen_copy_support import (
    account_id_of,
    call_key,
    chat_body,
    chat_response,
    seed_copy,
)
from tests.unit.usage_accounting.test_chat_route_accounting import (
    _ACCOUNTING_HEADERS,
    _ANTHROPIC_DISPATCH,
    _CHAT_PATH,
    _aigw,
    _arrange_account,
    _chat_body,
    _Dispatch,
    _install,
    _provider_payload,
    _Store,
)

_KEY = "succeeded_attempt_direct_cost"
_USAGE_KEY = "succeeded_attempt_usage"


@pytest.fixture
def chat_client(monkeypatch: pytest.MonkeyPatch, authenticated_client: TestClient) -> TestClient:
    # WHY: the cache must be on for the hit test; the route reads the setting per request.
    monkeypatch.setenv("AIGW_REQUEST_CACHE_ENABLED", "true")
    return authenticated_client


_MODEL = "openrouter/google/gemini-2.0-flash-001"


def _openrouter_collector(
    *attempts: tuple[int, dict[str, Any] | None],
) -> RequestAccountingCollector:
    collector = RequestAccountingCollector(
        provider="openrouter", requested_model=_MODEL, transport="litellm_async_http"
    )
    for status, raw_response in attempts:
        collector.begin_dispatch()
        marker = object()
        collector.on_send_admitted(marker)
        collector.on_response_completed(marker, status=status, raw_evidence=raw_response)
    return collector


def _finalize_and_render(
    collector: RequestAccountingCollector, final_response: dict[str, Any] | None
) -> dict[str, Any]:
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
        final_response=final_response,
    )
    return render_aigw_metadata(
        collector=collector,
        supported=True,
        cache_status="miss",
        gateway_call_id=collector.gateway_call_id,
    )


class TestOpenRouterEvidence:
    """The real OpenRouter mapper feeding the real collector, then the renderer."""

    def test_a_503_then_a_priced_200_reports_the_200s_reported_cost(self) -> None:
        successful = {"id": "gen-1", "usage": {"cost": Decimal("0.00042")}}
        collector = _openrouter_collector((503, None), (200, successful))

        metadata = _finalize_and_render(collector, successful)
        economics = metadata["request_economics"]

        assert [record.direct_cost.status for record in collector.records()] == [
            "unavailable",
            "reported",
        ]
        assert economics[_KEY] == {
            "status": "reported",
            "amount": "0.00042",
            "unit": "openrouter_credits",
            "source": "openrouter.usage.cost",
        }
        assert economics["direct_cost_status"] == "partial"
        (_failed, success) = collector.records()
        assert metadata["usage_accounting"][_USAGE_KEY] == success.usage.as_json()


class TestChatRoute:
    def test_an_overload_retry_reports_the_successful_attempts_cost(
        self, credential_blobs, chat_client: TestClient
    ) -> None:
        _arrange_account(chat_client, credential_blobs)
        _install(chat_client, _Store())

        class _OverloadedOnce:
            def __init__(self) -> None:
                self.attempts = 0
                self.markers: list[object] = []

            async def __call__(self, body: dict[str, Any]) -> Any:
                self.attempts += 1
                collector = active_collector()
                assert collector is not None
                marker = object()
                self.markers.append(marker)
                collector.on_send_admitted(marker)
                if self.attempts == 1:
                    collector.on_response_completed(marker, status=529, raw_evidence=None)
                    raise RateLimitError(
                        message="overloaded", llm_provider="anthropic", model="claude-haiku-4-5"
                    )
                collector.on_response_completed(
                    marker, status=200, raw_evidence=_provider_payload()
                )
                return _provider_payload()

        dispatch = _OverloadedOnce()
        with patch(_ANTHROPIC_DISPATCH, dispatch):
            response = chat_client.post(_CHAT_PATH, json=_chat_body(), headers=_ACCOUNTING_HEADERS)

        assert response.status_code == 200, response.text
        assert dispatch.attempts == 2, "the overload retry never happened"
        metadata = _aigw(response)
        succeeded = metadata["usage_accounting"]["attempts"][1]
        assert succeeded["outcome"] == "succeeded"
        assert metadata["request_economics"][_KEY] == succeeded["direct_cost"]
        assert metadata["usage_accounting"][_USAGE_KEY] == succeeded["usage"]

    def test_a_cache_hit_carries_null(self, credential_blobs, chat_client: TestClient) -> None:
        _arrange_account(chat_client, credential_blobs)
        _install(chat_client, _Store())
        with patch(_ANTHROPIC_DISPATCH, _Dispatch()):
            chat_client.post(_CHAT_PATH, json=_chat_body())
            hit = chat_client.post(_CHAT_PATH, json=_chat_body(), headers=_ACCOUNTING_HEADERS)
        assert hit.headers["X-AIGW-Cache"] == "hit"
        assert _aigw(hit)["request_economics"][_KEY] is None
        assert _aigw(hit)["usage_accounting"][_USAGE_KEY] is None

    def test_a_failure_after_a_200_send_carries_null(
        self, credential_blobs, chat_client: TestClient
    ) -> None:
        # WHY (spec D4): the collector downgrades a success the gateway then rejects, so the
        # error body names no successful attempt and the key is null.
        _arrange_account(chat_client, credential_blobs)
        _install(chat_client, _Store())

        class _GatewayLocalError(HTTPException):
            aigw_non_retryable = True

        async def dispatch(_plugin: Any, _body: dict[str, Any]) -> Any:
            collector = active_collector()
            assert collector is not None
            marker = object()
            collector.on_send_admitted(marker)
            collector.on_response_completed(marker, status=200, raw_evidence={})
            raise _GatewayLocalError(503, detail={"code": "gateway_local"})

        with patch(_ANTHROPIC_DISPATCH, dispatch):
            response = chat_client.post(_CHAT_PATH, json=_chat_body(), headers=_ACCOUNTING_HEADERS)

        assert response.status_code == 503, response.text
        metadata = response.json()["_aigw"]
        (attempt,) = metadata["usage_accounting"]["attempts"]
        assert attempt["outcome"] == "indeterminate"
        assert metadata["request_economics"][_KEY] is None
        assert metadata["usage_accounting"][_USAGE_KEY] is None


def test_a_frozen_copy_replay_carries_null(authenticated_client: TestClient) -> None:
    copy_id = seed_copy(
        authenticated_client,
        account_id_of(authenticated_client),
        [("chat", chat_body(), chat_response("paid"), 200)],
    )
    replay = authenticated_client.post(
        f"/v1/frozen-copies/{copy_id}/chat/completions", json=chat_body(), headers=call_key()
    )
    assert replay.status_code == 200, replay.text
    assert replay.json()["_aigw"]["request_economics"][_KEY] is None
    assert replay.json()["_aigw"]["usage_accounting"][_USAGE_KEY] is None
