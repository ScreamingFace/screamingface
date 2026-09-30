"""Timeout responses must preserve the observed send's accounting classification."""

import asyncio
from types import SimpleNamespace

import httpx
import pytest
from fastapi import HTTPException, Request
from litellm.exceptions import Timeout

from aigateway.config import Settings
from aigateway.core.provider_access import CredentialTarget, RequestDefaults
from aigateway.plugins.taxonomy.collector import RequestAccountingCollector
from aigateway.plugins.taxonomy.session import AccountingSession
from aigateway.plugins.taxonomy.types import ProviderUsageAccountingEvidence
from aigateway.routes.chat import _dispatch_and_finalize_accounting


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["httpx", "litellm", "execution_budget"])
async def test_timeout_preserves_accounting_classification(kind):
    collector = RequestAccountingCollector("openrouter", "fake", "litellm_async_http")
    session = AccountingSession("openrouter", True, collector, collector.gateway_call_id, False)

    async def receive():
        await asyncio.Event().wait()
        return {"type": "http.disconnect"}

    settings = Settings(provider_execution_timeout_s=0.01)
    request = Request(
        {
            "type": "http",
            "headers": [],
            "app": SimpleNamespace(state=SimpleNamespace(settings=settings)),
        },
        receive,
    )

    async def fake_provider(body):
        # A real request hook records the send before dispatch. Without a response,
        # the route must finalize that evidence using the original failure category.
        collector.on_send_admitted(httpx.Request("POST", "https://fake.invalid/completions"))
        if kind == "httpx":
            raise httpx.ReadTimeout("private provider error")
        if kind == "litellm":
            raise Timeout(message="private provider error", model="fake", llm_provider="openrouter")
        await asyncio.Event().wait()

    plugin = SimpleNamespace(
        chat_completion=fake_provider,
        normalize_chat_usage_accounting=lambda **kwargs: ProviderUsageAccountingEvidence(),
    )
    with pytest.raises(HTTPException) as error:
        await _dispatch_and_finalize_accounting(
            request,
            plugin=plugin,
            provider="openrouter",
            body={"model": "fake"},
            accounting=session,
            account_id="fake",
            profile_name="fake",
            target=CredentialTarget(
                kind="stored",
                auth_type="api_key",
                credential_name="fake:default",
                context_stamp="fake",
                reauth_url=None,
                defaults=RequestDefaults(),
            ),
        )
    assert error.value.status_code == 504
    assert error.value.detail == {
        "code": "provider_execution_timeout",
        "message": "Provider execution timed out.",
    }
    (record,) = collector.records()
    assert record.outcome == "transport_error"
    assert record.failure_code == "transport_timeout"
