"""Route composition for OpenRouter request-side zero-cost evidence."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast

import pytest
from fastapi import HTTPException, Request
from litellm.exceptions import RateLimitError

from aigateway.plugins.openrouter_provider.plugin import OpenRouterProviderPlugin
from aigateway.plugins.taxonomy import RequestAccountingCollector
from aigateway.routes.chat import _dispatch_and_finalize_accounting
from aigateway.routes.chat_accounting import AccountingSession

_MODEL = "openrouter/google/gemini-2.0-flash-001"


@pytest.mark.asyncio
@pytest.mark.parametrize("raise_rate_limit", [False, True], ids=["success-branch", "429-branch"])
async def test_prepared_web_search_reaches_finalizer_as_auxiliary_charge_risk(
    monkeypatch: pytest.MonkeyPatch,
    raise_rate_limit: bool,
) -> None:
    captured_request_views: list[dict[str, Any]] = []

    class _RecordingOpenRouter(OpenRouterProviderPlugin):
        def normalize_chat_usage_accounting(self, **kwargs: Any):
            captured_request_views.append(dict(kwargs["request_body"]))
            return super().normalize_chat_usage_accounting(**kwargs)

    plugin = _RecordingOpenRouter()
    body = plugin.prepare_chat_body(
        {
            "model": _MODEL,
            "messages": [{"role": "user", "content": "latest news"}],
            "web_search": True,
        }
    )
    body["api_key"] = "must-not-reach-mapper"
    collector = RequestAccountingCollector(
        provider="openrouter", requested_model=_MODEL, transport="litellm_async_http"
    )
    session = AccountingSession(
        provider="openrouter",
        supported=True,
        collector=collector,
        gateway_call_id=collector.gateway_call_id,
        inject_shared_handler=True,
    )
    insured_error = {
        "error": {"code": 429, "metadata": {"error_type": "rate_limit_exceeded"}},
        "openrouter_metadata": {"attempt": 1, "is_byok": False, "pipeline": []},
    }

    async def _fake_dispatch(
        _request: Request,
        _plugin: Any,
        _provider: str,
        _body: dict[str, Any],
        *,
        on_dispatch: Any = None,
    ) -> dict[str, Any]:
        on_dispatch()
        marker = object()
        collector.on_send_admitted(marker)
        collector.on_response_completed(marker, status=429, raw_evidence=insured_error)
        if raise_rate_limit:
            raise RateLimitError("limited", "openrouter", _MODEL)
        return {"id": "converted-response"}

    async def _safe_failure(_request: Request, exc: HTTPException, **_kwargs: Any) -> HTTPException:
        return exc

    monkeypatch.setattr("aigateway.routes.chat._dispatch_with_backpressure", _fake_dispatch)
    monkeypatch.setattr("aigateway.routes.chat._safe_dispatch_failure_response", _safe_failure)
    request = Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/v1/chat/completions",
            "headers": [],
            "app": SimpleNamespace(state=SimpleNamespace()),
        }
    )

    call = _dispatch_and_finalize_accounting(
        request,
        plugin=plugin,
        provider="openrouter",
        body=body,
        accounting=session,
        account_id="account",
        profile_name="default",
        target=cast(Any, object()),
    )

    if raise_rate_limit:
        with pytest.raises(HTTPException, match="rate_limit"):
            await call
    else:
        assert await call == {"id": "converted-response"}
    assert captured_request_views == [{"model": _MODEL, "api_base": "https://openrouter.ai/api/v1"}]
    assert collector.records()[0].direct_cost.status == "unavailable"
