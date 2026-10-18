"""Characterization tests for /v1/chat/completions seams (OME-428 Phase 1).

These pin route behavior that is NOT already covered by test_chat_x_profile.py
or test_chat_request_cache.py, before routes/chat.py is split into
chat_credentials.py + chat_dispatch.py. Every test exercises the HTTP surface
only — no imports from aigateway.routes.chat — so the mechanical split cannot
invalidate them. They must be green before AND after the split.

Deliberately NOT pinned here: malformed (non-JSON) request bodies — today they
escape as a route-level 500 and OME-428 Phase 3 request hardening intentionally
changes that to a 400.
"""

from __future__ import annotations

import json
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from litellm.exceptions import BadRequestError, ServiceUnavailableError

from aigateway.core.credential_names import credential_name_for, profile_id_for
from aigateway.core.profile_index import ProfileIndexStore
from aigateway.core.profile_models import Profile, ProfileState
from aigateway.plugins.anthropic_provider.auth import credential_service_for


def _account_id(client) -> str:
    return client.get("/v1/auth/me").json()["id"]


def _seed_authenticated_profile(credential_blobs, account_id: str) -> None:
    credential_blobs.write(
        credential_service_for(credential_name_for(account_id, "default")),
        "default",
        json.dumps(
            {
                "access_token": "tok",
                "refresh_token": "rt",
                "expires_at_ms": int(time.time() * 1000) + 3_600_000,
                "token_type": "Bearer",
            }
        ),
    )


async def _seed_anthropic_profile(credential_blobs, account_id: str) -> None:
    _seed_authenticated_profile(credential_blobs, account_id)
    idx = ProfileIndexStore(credential_store=credential_blobs.store)
    await idx.upsert(
        Profile(
            id=profile_id_for(account_id, "anthropic", "default"),
            account_id=account_id,
            provider="anthropic",
            name="default",
            state=ProfileState.AUTHENTICATED,
        )
    )


# --- request-shape validation (raised before any credential resolution) ---


def test_chat_400_when_model_missing(authenticated_client) -> None:
    resp = authenticated_client.post(
        "/v1/chat/completions",
        json={"messages": [{"role": "user", "content": "hi"}]},
    )
    assert resp.status_code == 400
    assert resp.json()["detail"] == "model and messages are required"


def test_chat_400_when_messages_missing(authenticated_client) -> None:
    resp = authenticated_client.post(
        "/v1/chat/completions",
        json={"model": "anthropic/claude-sonnet-4-5"},
    )
    assert resp.status_code == 400
    assert resp.json()["detail"] == "model and messages are required"


def test_chat_400_when_body_is_not_an_object(authenticated_client) -> None:
    resp = authenticated_client.post(
        "/v1/chat/completions",
        json=["model", "messages"],
    )
    assert resp.status_code == 400
    assert resp.json()["detail"] == "model and messages are required"


def test_chat_400_when_model_not_provider_prefixed(authenticated_client) -> None:
    resp = authenticated_client.post(
        "/v1/chat/completions",
        json={
            "model": "claude-sonnet-4-5",
            "messages": [{"role": "user", "content": "hi"}],
        },
    )
    assert resp.status_code == 400
    assert resp.json()["detail"] == "model must be provider-prefixed"


def test_chat_400_when_provider_unknown(authenticated_client) -> None:
    resp = authenticated_client.post(
        "/v1/chat/completions",
        json={
            "model": "nosuchprovider/some-model",
            "messages": [{"role": "user", "content": "hi"}],
        },
    )
    assert resp.status_code == 400
    assert resp.json()["detail"] == "unknown provider: nosuchprovider"


# --- litellm exception → HTTP mapping through the dispatch seam ---


@pytest.mark.asyncio
async def test_chat_persistent_service_unavailable_maps_provider_unavailable(
    credential_blobs, authenticated_client
) -> None:
    """A 503 that survives every retry surfaces as provider_unavailable."""
    account_id = _account_id(authenticated_client)
    await _seed_anthropic_profile(credential_blobs, account_id)

    request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    response = httpx.Response(503, request=request)
    calls = {"n": 0}

    async def always_unavailable(_self, _body):
        calls["n"] += 1
        raise ServiceUnavailableError(
            "overloaded",
            llm_provider="anthropic",
            model="anthropic/claude-sonnet-4-5",
            response=response,
        )

    with (
        patch(
            "aigateway.plugins.anthropic_provider.plugin.AnthropicProviderPlugin.chat_completion",
            always_unavailable,
        ),
        patch("aigateway.core.retry.asyncio.sleep", new_callable=AsyncMock),
    ):
        resp = authenticated_client.post(
            "/v1/chat/completions",
            json={
                "model": "anthropic/claude-sonnet-4-5",
                "messages": [{"role": "user", "content": "hi"}],
            },
        )

    assert resp.status_code == 503
    assert resp.json()["detail"]["code"] == "provider_unavailable"
    assert calls["n"] == 4  # 1 initial + 3 retries (default AIGW_RETRY_MAX_ATTEMPTS=3)


@pytest.mark.asyncio
async def test_chat_bad_request_error_maps_bad_request_without_retry(
    credential_blobs, authenticated_client
) -> None:
    """A provider 400 is terminal: mapped to bad_request and never retried."""
    account_id = _account_id(authenticated_client)
    await _seed_anthropic_profile(credential_blobs, account_id)

    calls = {"n": 0}

    async def always_bad_request(_self, _body):
        calls["n"] += 1
        raise BadRequestError(
            "unsupported parameter combination",
            model="anthropic/claude-sonnet-4-5",
            llm_provider="anthropic",
        )

    with (
        patch(
            "aigateway.plugins.anthropic_provider.plugin.AnthropicProviderPlugin.chat_completion",
            always_bad_request,
        ),
        patch("aigateway.core.retry.asyncio.sleep", new_callable=AsyncMock),
    ):
        resp = authenticated_client.post(
            "/v1/chat/completions",
            json={
                "model": "anthropic/claude-sonnet-4-5",
                "messages": [{"role": "user", "content": "hi"}],
            },
        )

    assert resp.status_code == 400
    detail = resp.json()["detail"]
    assert detail["code"] == "bad_request"
    # OME-428 FINDING B (ratified Confidence-Gate change): the generic
    # LiteLLM-exception sanitizer no longer serializes str(exc) — raw provider
    # text must not reach clients/logs/persisted errors. The machine code is
    # preserved; the message is gateway-authored.
    assert "unsupported parameter combination" not in detail["message"]
    assert detail["message"]  # a gateway-authored, non-empty message remains
    assert calls["n"] == 1


# --- successful dispatch render path ---


@pytest.mark.asyncio
async def test_chat_success_dumps_model_and_sets_bypass_headers(
    credential_blobs, authenticated_client
) -> None:
    """Responses with model_dump are serialized via it; with the request cache
    disabled (default) every response carries bypass/disabled cache headers."""
    account_id = _account_id(authenticated_client)
    await _seed_anthropic_profile(credential_blobs, account_id)

    payload = {"id": "resp-1", "choices": [{"message": {"content": "ok"}}]}

    async def fake_chat_completion(_self, _body):
        return SimpleNamespace(model_dump=lambda: payload)

    with patch(
        "aigateway.plugins.anthropic_provider.plugin.AnthropicProviderPlugin.chat_completion",
        fake_chat_completion,
    ):
        resp = authenticated_client.post(
            "/v1/chat/completions",
            json={
                "model": "anthropic/claude-sonnet-4-5",
                "messages": [{"role": "user", "content": "hi"}],
            },
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body.pop("_aigw")["usage_accounting"]["schema"] == "aigw.chat_usage_accounting"
    assert body == payload
    assert resp.headers["x-aigw-cache"] == "bypass"
    assert resp.headers["x-aigw-cache-reason"] == "disabled"
    assert "x-aigw-cache-key" not in resp.headers


@pytest.mark.asyncio
async def test_chat_success_passes_plain_dict_response_through(
    credential_blobs, authenticated_client
) -> None:
    """Provider responses without model_dump are returned verbatim."""
    account_id = _account_id(authenticated_client)
    await _seed_anthropic_profile(credential_blobs, account_id)

    payload = {"id": "raw-1", "choices": [{"message": {"content": "raw"}}]}

    async def fake_chat_completion(_self, _body):
        return payload

    with patch(
        "aigateway.plugins.anthropic_provider.plugin.AnthropicProviderPlugin.chat_completion",
        fake_chat_completion,
    ):
        resp = authenticated_client.post(
            "/v1/chat/completions",
            json={
                "model": "anthropic/claude-sonnet-4-5",
                "messages": [{"role": "user", "content": "hi"}],
            },
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body.pop("_aigw")["usage_accounting"]["schema"] == "aigw.chat_usage_accounting"
    assert body == payload
