from __future__ import annotations

import json
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from fastapi import HTTPException

from aigateway.core.credential_names import credential_name_for, profile_id_for
from aigateway.core.oauth.store import OAuthConnectionStore
from aigateway.core.profile_index import ProfileIndexStore
from aigateway.core.profile_models import Profile, ProfileState
from aigateway.plugins.gemini_provider.auth import credential_service_for
from tests.unit.migrated_pair_seed import seed_migrated_pair


def _account_id(client) -> str:
    return client.get("/v1/auth/me").json()["id"]


def _connection_status(client, account_id: str, connection_id) -> str | None:
    connection = client.portal.call(OAuthConnectionStore().get, account_id, connection_id)
    return None if connection is None else connection.status


def _seed_authenticated_gemini_profile(credential_blobs, account_id: str, **extra) -> None:
    creds = {
        "access_token": "ya29.oauth",
        "refresh_token": "refresh-1",
        "expires_at_ms": int(time.time() * 1000) + 3_600_000,
        "token_type": "Bearer",
    }
    creds.update(extra)
    credential_blobs.write(
        credential_service_for(credential_name_for(account_id, "default")),
        "default",
        json.dumps(creds),
    )


@pytest.mark.asyncio
async def test_gemini_chat_allows_no_profile_when_env_key_exists(
    monkeypatch, authenticated_client
) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "env-key")
    captured: dict = {}

    async def fake_chat_completion(_self, body):
        captured.update(body)
        return SimpleNamespace(
            model_dump=lambda: {"id": "x", "choices": [{"message": {"content": "ok"}}]}
        )

    with patch(
        "aigateway.plugins.gemini_provider.plugin.GeminiProviderPlugin.chat_completion",
        fake_chat_completion,
    ):
        resp = authenticated_client.post(
            "/v1/chat/completions",
            json={
                "model": "gemini-cli/gemini-2.5-flash",
                "messages": [{"role": "user", "content": "hi"}],
            },
        )

    assert resp.status_code == 200
    assert captured["model"] == "gemini-cli/gemini-2.5-flash"
    assert "api_key" not in captured


@pytest.mark.asyncio
async def test_gemini_chat_without_profile_and_without_env_key_returns_401(
    monkeypatch, authenticated_client
) -> None:
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)

    resp = authenticated_client.post(
        "/v1/chat/completions",
        json={
            "model": "gemini-cli/gemini-2.5-flash",
            "messages": [{"role": "user", "content": "hi"}],
        },
    )

    assert resp.status_code == 401
    assert resp.json()["detail"]["code"] == "auth_required"


@pytest.mark.asyncio
async def test_gemini_streaming_rejected_before_dispatch(monkeypatch, authenticated_client) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "env-key")

    with patch(
        "aigateway.plugins.gemini_provider.plugin.GeminiProviderPlugin.chat_completion_stream"
    ) as fake_stream:
        resp = authenticated_client.post(
            "/v1/chat/completions",
            json={
                "model": "gemini-cli/gemini-2.5-flash",
                "messages": [{"role": "user", "content": "hi"}],
                "stream": True,
            },
        )

    assert resp.status_code == 400
    assert resp.json()["detail"]["code"] == "streaming_not_supported"
    fake_stream.assert_not_called()


@pytest.mark.asyncio
async def test_gemini_authenticated_profile_uses_oauth_not_env_key_or_client_key(
    monkeypatch, credential_blobs, authenticated_client
) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "env-key")
    account_id = _account_id(authenticated_client)
    _seed_authenticated_gemini_profile(credential_blobs, account_id)
    idx = ProfileIndexStore(credential_store=credential_blobs.store)
    await idx.upsert(
        Profile(
            id=profile_id_for(account_id, "gemini-cli", "default"),
            account_id=account_id,
            provider="gemini-cli",
            name="default",
            state=ProfileState.AUTHENTICATED,
        )
    )
    # WHY: resolve reads the pair's authority, not the document (OME-1209 E4a).
    seed_migrated_pair(authenticated_client, account_id, "gemini-cli")
    captured: dict = {}

    async def fake_chat_completion(_self, body):
        captured.update(body)
        return SimpleNamespace(
            model_dump=lambda: {"id": "x", "choices": [{"message": {"content": "ok"}}]}
        )

    with patch(
        "aigateway.plugins.gemini_provider.plugin.GeminiProviderPlugin.chat_completion",
        fake_chat_completion,
    ):
        resp = authenticated_client.post(
            "/v1/chat/completions",
            json={
                "model": "gemini-cli/gemini-2.5-flash",
                "messages": [{"role": "user", "content": "hi"}],
                "api_key": "client-supplied",
            },
        )

    assert resp.status_code == 200
    assert captured["api_key"] == "ya29.oauth"
    assert captured["extra_headers"]["X-AIGW-Gemini-Profile"] == credential_name_for(
        account_id, "default"
    )


@pytest.mark.asyncio
async def test_gemini_refresh_error_marks_profile_error(
    monkeypatch, credential_blobs, authenticated_client
) -> None:
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    account_id = _account_id(authenticated_client)
    _seed_authenticated_gemini_profile(
        credential_blobs,
        account_id,
        expires_at_ms=int((time.time() - 60) * 1000),
    )
    idx = ProfileIndexStore(credential_store=credential_blobs.store)
    await idx.upsert(
        Profile(
            id=profile_id_for(account_id, "gemini-cli", "default"),
            account_id=account_id,
            provider="gemini-cli",
            name="default",
            state=ProfileState.AUTHENTICATED,
        )
    )
    connection_id = seed_migrated_pair(authenticated_client, account_id, "gemini-cli")

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": "invalid_grant"})

    setattr(
        authenticated_client.app.state,
        "gemini-cli_http_factory",
        lambda: httpx.AsyncClient(
            transport=httpx.MockTransport(handler), timeout=httpx.Timeout(5.0)
        ),
    )

    resp = authenticated_client.post(
        "/v1/chat/completions",
        json={
            "model": "gemini-cli/gemini-2.5-flash",
            "messages": [{"role": "user", "content": "hi"}],
        },
    )

    assert resp.status_code == 401
    assert resp.json()["detail"]["code"] == "auth_required"
    # WHY the Connection: the pair's effective Connection is the authority a refusal marks;
    # no runtime path writes the legacy document's state (OME-1209 E4a).
    assert _connection_status(authenticated_client, account_id, connection_id) == "error"


@pytest.mark.asyncio
async def test_gemini_dispatch_401_marks_profile_error_and_reauth_url(
    monkeypatch, credential_blobs, authenticated_client
) -> None:
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    account_id = _account_id(authenticated_client)
    credential_name = credential_name_for(account_id, "default")
    _seed_authenticated_gemini_profile(credential_blobs, account_id)
    idx = ProfileIndexStore(credential_store=credential_blobs.store)
    await idx.upsert(
        Profile(
            id=profile_id_for(account_id, "gemini-cli", "default"),
            account_id=account_id,
            provider="gemini-cli",
            name="default",
            state=ProfileState.AUTHENTICATED,
        )
    )
    connection_id = seed_migrated_pair(authenticated_client, account_id, "gemini-cli")
    invalidated: list[str] = []

    async def fake_chat_completion(_self, _body):
        raise HTTPException(
            status_code=401,
            detail={"code": "auth_required", "message": "Gemini Code Assist rejected token"},
        )

    def fake_invalidate(_self, profile_name: str) -> None:
        invalidated.append(profile_name)

    with (
        patch(
            "aigateway.plugins.gemini_provider.plugin.GeminiProviderPlugin.chat_completion",
            fake_chat_completion,
        ),
        patch(
            "aigateway.plugins.gemini_provider.plugin.GeminiProviderPlugin.invalidate_profile_session",
            fake_invalidate,
        ),
    ):
        resp = authenticated_client.post(
            "/v1/chat/completions",
            json={
                "model": "gemini-cli/gemini-2.5-flash",
                "messages": [{"role": "user", "content": "hi"}],
            },
        )

    assert resp.status_code == 401
    detail = resp.json()["detail"]
    assert detail["code"] == "auth_required"
    assert detail["message"] == "Gemini Code Assist rejected token"
    assert detail["reauth_url"] == "/v1/oauth/connections"
    assert invalidated == [credential_name]
    # WHY the Connection: as for a refresh failure, a dispatch 401 marks the effective Connection.
    assert _connection_status(authenticated_client, account_id, connection_id) == "error"


@pytest.mark.asyncio
async def test_error_profile_is_rejected_before_dispatch(
    credential_blobs, authenticated_client
) -> None:
    account_id = _account_id(authenticated_client)
    idx = ProfileIndexStore(credential_store=credential_blobs.store)
    await idx.upsert(
        Profile(
            id=profile_id_for(account_id, "gemini-cli", "default"),
            account_id=account_id,
            provider="gemini-cli",
            name="default",
            state=ProfileState.ERROR,
        )
    )
    seed_migrated_pair(authenticated_client, account_id, "gemini-cli", state=ProfileState.ERROR)
    fake_chat = AsyncMock()

    with patch(
        "aigateway.plugins.gemini_provider.plugin.GeminiProviderPlugin.chat_completion",
        fake_chat,
    ):
        resp = authenticated_client.post(
            "/v1/chat/completions",
            json={
                "model": "gemini-cli/gemini-2.5-flash",
                "messages": [{"role": "user", "content": "hi"}],
            },
        )

    assert resp.status_code == 401
    detail = resp.json()["detail"]
    assert detail["code"] == "auth_required"
    assert detail["reauth_url"] == "/v1/oauth/connections"
    fake_chat.assert_not_called()
