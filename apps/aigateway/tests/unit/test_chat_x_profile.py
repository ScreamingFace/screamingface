from __future__ import annotations

import json
import time
from functools import partial
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import UUID, uuid4

import httpx
import pytest
from litellm.exceptions import RateLimitError, ServiceUnavailableError

from aigateway.core.auth.middleware import ANONYMOUS_ACCOUNT_ID
from aigateway.core.oauth.store import OAuthConnectionStore, credential_key_for
from aigateway.core.profile_index import ProfileIndexStore
from aigateway.core.profile_models import (
    Profile,
    ProfileDefaults,
    ProfileState,
    credential_name_for,
    profile_id_for,
)
from aigateway.plugins.anthropic_provider.auth import credential_service_for
from aigateway.plugins.codex_provider.auth import (
    credential_service_for as codex_credential_service_for,
)


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


def _seed_authenticated_connection(
    credential_blobs,
    account_id: str,
    connection_id: str | UUID,
    *,
    access_token: str = "connection-tok",
) -> None:
    credential_blobs.write(
        credential_service_for(credential_key_for(account_id, connection_id)),
        "default",
        json.dumps(
            {
                "access_token": access_token,
                "refresh_token": "connection-rt",
                "expires_at_ms": int(time.time() * 1000) + 3_600_000,
                "token_type": "Bearer",
            }
        ),
    )


async def _create_active_connection(
    account_id: str,
    *,
    provider: str = "anthropic",
    label: str = "work-anthropic",
):
    store = OAuthConnectionStore()
    connection = await store.create_pending(
        account_id=account_id,
        provider=provider,
        label=label,
        connection_id=uuid4(),
    )
    return await store.complete(connection, label=label, identity=None)


def _seed_authenticated_codex_profile(credential_blobs, account_id: str) -> None:
    credential_blobs.write(
        codex_credential_service_for(credential_name_for(account_id, "default")),
        "default",
        json.dumps(
            {
                "access_token": "tok",
                "refresh_token": "rt",
                "id_token": "id",
                "expires_at_ms": int(time.time() * 1000) + 3_600_000,
                "token_type": "Bearer",
            }
        ),
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "model",
    ["anthropic/claude-haiku-4-5", "codex/gpt-5.4-mini"],
)
async def test_chat_404_when_oauth_profile_missing(authenticated_client, model: str) -> None:
    resp = authenticated_client.post(
        "/v1/chat/completions",
        headers={"X-Profile": "missing"},
        json={
            "model": model,
            "messages": [{"role": "user", "content": "hi"}],
        },
    )
    assert resp.status_code == 404
    assert resp.json()["detail"]["code"] == "profile_not_found"


@pytest.mark.asyncio
async def test_chat_404_when_codex_profile_missing(authenticated_client) -> None:
    resp = authenticated_client.post(
        "/v1/chat/completions",
        headers={"X-Profile": "missing"},
        json={
            "model": "codex/gpt-5.4-mini",
            "messages": [{"role": "user", "content": "hi"}],
        },
    )

    assert resp.status_code == 404
    assert resp.json()["detail"]["code"] == "profile_not_found"


def test_chat_uses_single_active_oauth_connection_when_profile_missing(
    credential_blobs, authenticated_client
) -> None:
    account_id = _account_id(authenticated_client)
    connection = authenticated_client.portal.call(_create_active_connection, account_id)
    _seed_authenticated_connection(credential_blobs, account_id, connection.id)
    captured: dict = {}

    async def fake_chat_completion(_self, body):
        captured.update(body)
        from types import SimpleNamespace

        return SimpleNamespace(
            model_dump=lambda: {
                "id": "x",
                "choices": [{"message": {"content": "ok"}}],
            }
        )

    with patch(
        "aigateway.plugins.anthropic_provider.plugin.AnthropicProviderPlugin.chat_completion",
        fake_chat_completion,
    ):
        resp = authenticated_client.post(
            "/v1/chat/completions",
            json={
                "model": "anthropic/claude-haiku-4-5",
                "messages": [{"role": "user", "content": "hi"}],
            },
        )

    assert resp.status_code == 200
    assert captured["api_key"] == "connection-tok"
    refreshed = authenticated_client.portal.call(
        OAuthConnectionStore().get, account_id, connection.id
    )
    assert refreshed is not None
    assert refreshed.last_used_at is not None


def test_chat_requires_profile_label_when_multiple_oauth_connections_exist(
    credential_blobs, authenticated_client
) -> None:
    account_id = _account_id(authenticated_client)
    first = authenticated_client.portal.call(
        partial(_create_active_connection, account_id, label="work-anthropic")
    )
    second = authenticated_client.portal.call(
        partial(_create_active_connection, account_id, label="personal-anthropic")
    )
    _seed_authenticated_connection(credential_blobs, account_id, first.id, access_token="work-tok")
    _seed_authenticated_connection(
        credential_blobs, account_id, second.id, access_token="personal-tok"
    )

    ambiguous = authenticated_client.post(
        "/v1/chat/completions",
        json={
            "model": "anthropic/claude-haiku-4-5",
            "messages": [{"role": "user", "content": "hi"}],
        },
    )
    assert ambiguous.status_code == 409
    assert ambiguous.json()["detail"]["code"] == "connection_ambiguous"

    captured: dict = {}

    async def fake_chat_completion(_self, body):
        captured.update(body)
        from types import SimpleNamespace

        return SimpleNamespace(
            model_dump=lambda: {
                "id": "x",
                "choices": [{"message": {"content": "ok"}}],
            }
        )

    with patch(
        "aigateway.plugins.anthropic_provider.plugin.AnthropicProviderPlugin.chat_completion",
        fake_chat_completion,
    ):
        resp = authenticated_client.post(
            "/v1/chat/completions",
            headers={"X-Profile": "personal-anthropic"},
            json={
                "model": "anthropic/claude-haiku-4-5",
                "messages": [{"role": "user", "content": "hi"}],
            },
        )

    assert resp.status_code == 200
    assert captured["api_key"] == "personal-tok"


def test_chat_wrong_connection_label_returns_valid_labels(authenticated_client) -> None:
    account_id = _account_id(authenticated_client)
    authenticated_client.portal.call(
        partial(_create_active_connection, account_id, label="work-anthropic")
    )
    authenticated_client.portal.call(
        partial(_create_active_connection, account_id, label="personal-anthropic")
    )

    resp = authenticated_client.post(
        "/v1/chat/completions",
        headers={"X-Profile": "missing-anthropic"},
        json={
            "model": "anthropic/claude-haiku-4-5",
            "messages": [{"role": "user", "content": "hi"}],
        },
    )

    assert resp.status_code == 404
    assert resp.json()["detail"] == {
        "code": "connection_not_found",
        "provider": "anthropic",
        "requested_label": "missing-anthropic",
        "valid_labels": ["personal-anthropic", "work-anthropic"],
    }


def test_chat_never_advertises_literal_default_as_an_explicit_connection_label(
    authenticated_client,
) -> None:
    """INVARIANT: ``default`` stays implicit and is never offered as a dead-end fix."""
    account_id = _account_id(authenticated_client)
    authenticated_client.portal.call(
        partial(_create_active_connection, account_id, label="default")
    )
    authenticated_client.portal.call(partial(_create_active_connection, account_id, label="other"))
    body = {
        "model": "anthropic/claude-haiku-4-5",
        "messages": [{"role": "user", "content": "hi"}],
    }

    ambiguous = authenticated_client.post(
        "/v1/chat/completions", headers={"X-Profile": "default"}, json=body
    )
    unknown = authenticated_client.post(
        "/v1/chat/completions", headers={"X-Profile": "missing"}, json=body
    )

    assert ambiguous.status_code == 409
    ambiguous_detail = ambiguous.json()["detail"]
    assert ambiguous_detail["code"] == "connection_ambiguous"
    assert ambiguous_detail["valid_labels"] == ["other"]
    assert "non-default" in ambiguous_detail["message"]
    assert unknown.status_code == 404
    assert unknown.json()["detail"]["valid_labels"] == ["other"]


def test_chat_empty_x_profile_header_uses_default_ambiguity(
    credential_blobs, authenticated_client
) -> None:
    account_id = _account_id(authenticated_client)
    authenticated_client.portal.call(
        partial(_create_active_connection, account_id, label="work-anthropic")
    )
    authenticated_client.portal.call(
        partial(_create_active_connection, account_id, label="personal-anthropic")
    )

    resp = authenticated_client.post(
        "/v1/chat/completions",
        headers={"X-Profile": ""},
        json={
            "model": "anthropic/claude-haiku-4-5",
            "messages": [{"role": "user", "content": "hi"}],
        },
    )

    assert resp.status_code == 409
    assert resp.json()["detail"]["code"] == "connection_ambiguous"


def test_chat_cannot_use_other_accounts_oauth_connection(
    credential_blobs, authenticated_client, provisioned_user_factory
) -> None:
    admin_account_id = _account_id(authenticated_client)
    connection = authenticated_client.portal.call(_create_active_connection, admin_account_id)
    _seed_authenticated_connection(credential_blobs, admin_account_id, connection.id)

    provisioned_user_factory("bob", "bob-pass1")
    login = authenticated_client.post(
        "/v1/auth/login",
        json={"username": "bob", "password": "bob-pass1"},
    )
    authenticated_client.headers.update({"Authorization": f"Bearer {login.json()['token']}"})

    resp = authenticated_client.post(
        "/v1/chat/completions",
        json={
            "model": "anthropic/claude-haiku-4-5",
            "messages": [{"role": "user", "content": "hi"}],
        },
    )

    assert resp.status_code == 404


def test_chat_uses_oauth_connection_for_anonymous_local_mode(credential_blobs, client) -> None:
    client.app.state.settings.auth_mode = "disabled"
    account_id = str(ANONYMOUS_ACCOUNT_ID)
    connection = client.portal.call(_create_active_connection, account_id)
    _seed_authenticated_connection(credential_blobs, account_id, connection.id)
    captured: dict = {}

    async def fake_chat_completion(_self, body):
        captured.update(body)
        from types import SimpleNamespace

        return SimpleNamespace(
            model_dump=lambda: {
                "id": "x",
                "choices": [{"message": {"content": "ok"}}],
            }
        )

    with patch(
        "aigateway.plugins.anthropic_provider.plugin.AnthropicProviderPlugin.chat_completion",
        fake_chat_completion,
    ):
        resp = client.post(
            "/v1/chat/completions",
            json={
                "model": "anthropic/claude-haiku-4-5",
                "messages": [{"role": "user", "content": "hi"}],
            },
        )

    assert resp.status_code == 200
    assert captured["api_key"] == "connection-tok"


@pytest.mark.asyncio
async def test_chat_409_when_profile_pending(credential_blobs, authenticated_client) -> None:
    account_id = _account_id(authenticated_client)
    idx = ProfileIndexStore(credential_store=credential_blobs.store)
    await idx.upsert(
        Profile(
            id=profile_id_for(account_id, "anthropic", "default"),
            account_id=account_id,
            provider="anthropic",
            name="default",
            state=ProfileState.PENDING,
        )
    )
    resp = authenticated_client.post(
        "/v1/chat/completions",
        json={
            "model": "anthropic/claude-haiku-4-5",
            "messages": [{"role": "user", "content": "hi"}],
        },
    )
    assert resp.status_code == 409
    assert resp.json()["detail"]["code"] == "profile_pending_auth"


@pytest.mark.asyncio
async def test_chat_merges_profile_defaults(credential_blobs, authenticated_client) -> None:
    account_id = _account_id(authenticated_client)
    _seed_authenticated_profile(credential_blobs, account_id)

    idx = ProfileIndexStore(credential_store=credential_blobs.store)
    await idx.upsert(
        Profile(
            id=profile_id_for(account_id, "anthropic", "default"),
            account_id=account_id,
            provider="anthropic",
            name="default",
            state=ProfileState.AUTHENTICATED,
            # AIDEV-NOTE: 8192 is deliberate headroom, not an arbitrary number.
            # This test is about default MERGING, but reasoning_effort="high"
            # below becomes a 4096-token thinking budget on this model and
            # Anthropic requires max_tokens to exceed it (OME-640). The original
            # 4096 sat exactly on that boundary and made a merge test depend on a
            # provider constraint it never meant to exercise. The boundary itself
            # is asserted in tests/unit/anthropic/test_anthropic_thinking_conflict.py.
            defaults=ProfileDefaults(max_tokens=8192, reasoning_effort="medium"),
        )
    )

    captured: dict = {}

    async def fake_chat_completion(_self, body):
        captured.update(body)
        from types import SimpleNamespace

        return SimpleNamespace(
            model_dump=lambda: {
                "id": "x",
                "choices": [{"message": {"content": "ok"}}],
            }
        )

    with patch(
        "aigateway.plugins.anthropic_provider.plugin.AnthropicProviderPlugin.chat_completion",
        fake_chat_completion,
    ):
        resp = authenticated_client.post(
            "/v1/chat/completions",
            json={
                "model": "anthropic/claude-haiku-4-5",
                "messages": [{"role": "user", "content": "hi"}],
                "reasoning_effort": "high",  # body wins
                # max_tokens omitted — profile default fills in
            },
        )
        assert resp.status_code == 200
        assert captured["max_tokens"] == 8192
        assert captured["reasoning_effort"] == "high"
    assert captured["api_key"] == "tok"


@pytest.mark.asyncio
async def test_chat_skips_anthropic_profile_reasoning_default(
    credential_blobs, authenticated_client
) -> None:
    account_id = _account_id(authenticated_client)
    _seed_authenticated_profile(credential_blobs, account_id)

    idx = ProfileIndexStore(credential_store=credential_blobs.store)
    await idx.upsert(
        Profile(
            id=profile_id_for(account_id, "anthropic", "default"),
            account_id=account_id,
            provider="anthropic",
            name="default",
            state=ProfileState.AUTHENTICATED,
            defaults=ProfileDefaults(reasoning_effort="medium"),
        )
    )
    captured: dict = {}

    async def fake_chat_completion(_self, body):
        captured.update(body)
        from types import SimpleNamespace

        return SimpleNamespace(
            model_dump=lambda: {
                "id": "x",
                "choices": [{"message": {"content": "ok"}}],
            }
        )

    with patch(
        "aigateway.plugins.anthropic_provider.plugin.AnthropicProviderPlugin.chat_completion",
        fake_chat_completion,
    ):
        resp = authenticated_client.post(
            "/v1/chat/completions",
            json={
                "model": "anthropic/claude-haiku-4-5",
                "messages": [{"role": "user", "content": "hi"}],
            },
        )

    assert resp.status_code == 200
    assert "reasoning_effort" not in captured


@pytest.mark.asyncio
async def test_chat_removes_anthropic_reasoning_none(
    credential_blobs, authenticated_client
) -> None:
    account_id = _account_id(authenticated_client)
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
    captured: dict = {}

    async def fake_chat_completion(_self, body):
        captured.update(body)
        from types import SimpleNamespace

        return SimpleNamespace(
            model_dump=lambda: {
                "id": "x",
                "choices": [{"message": {"content": "ok"}}],
            }
        )

    with patch(
        "aigateway.plugins.anthropic_provider.plugin.AnthropicProviderPlugin.chat_completion",
        fake_chat_completion,
    ):
        resp = authenticated_client.post(
            "/v1/chat/completions",
            json={
                "model": "anthropic/claude-haiku-4-5",
                "messages": [{"role": "user", "content": "hi"}],
                "reasoning_effort": "none",
            },
        )

    assert resp.status_code == 200
    assert "reasoning_effort" not in captured


@pytest.mark.asyncio
async def test_chat_cannot_use_other_accounts_profile(
    credential_blobs, authenticated_client, provisioned_user_factory
) -> None:
    admin_account_id = _account_id(authenticated_client)
    _seed_authenticated_profile(credential_blobs, admin_account_id)
    idx = ProfileIndexStore(credential_store=credential_blobs.store)
    await idx.upsert(
        Profile(
            id=profile_id_for(admin_account_id, "anthropic", "shared"),
            account_id=admin_account_id,
            provider="anthropic",
            name="shared",
            state=ProfileState.AUTHENTICATED,
        )
    )

    provisioned_user_factory("bob", "bob-pass1")
    login = authenticated_client.post(
        "/v1/auth/login",
        json={"username": "bob", "password": "bob-pass1"},
    )
    authenticated_client.headers.update({"Authorization": f"Bearer {login.json()['token']}"})

    resp = authenticated_client.post(
        "/v1/chat/completions",
        headers={"X-Profile": "shared"},
        json={
            "model": "anthropic/claude-haiku-4-5",
            "messages": [{"role": "user", "content": "hi"}],
        },
    )
    assert resp.status_code == 404


def test_chat_requires_auth(client) -> None:
    resp = client.post(
        "/v1/chat/completions",
        json={"model": "anthropic/claude-haiku-4-5", "messages": []},
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_chat_rejects_codex_stream_before_litellm(
    credential_blobs, authenticated_client
) -> None:
    account_id = _account_id(authenticated_client)
    _seed_authenticated_codex_profile(credential_blobs, account_id)
    idx = ProfileIndexStore(credential_store=credential_blobs.store)
    await idx.upsert(
        Profile(
            id=profile_id_for(account_id, "codex", "default"),
            account_id=account_id,
            provider="codex",
            name="default",
            state=ProfileState.AUTHENTICATED,
        )
    )
    fake_stream = AsyncMock()

    with patch(
        "aigateway.plugins.codex_provider.plugin.CodexProviderPlugin.chat_completion_stream",
        fake_stream,
    ):
        resp = authenticated_client.post(
            "/v1/chat/completions",
            json={
                "model": "codex/gpt-5.4-mini",
                "messages": [{"role": "user", "content": "hi"}],
                "stream": True,
            },
        )

    assert resp.status_code == 400
    assert resp.json()["detail"]["code"] == "streaming_not_supported"
    fake_stream.assert_not_called()


@pytest.mark.asyncio
async def test_chat_streams_through_provider_plugin_boundary(
    credential_blobs, authenticated_client
) -> None:
    account_id = _account_id(authenticated_client)
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
    captured: dict = {}

    async def fake_stream_completion(_self, body):
        captured.update(body)

        from types import SimpleNamespace

        yield SimpleNamespace(model_dump=lambda: {"choices": [{"delta": {"content": "hi"}}]})

    with patch(
        "aigateway.plugins.anthropic_provider.plugin.AnthropicProviderPlugin.chat_completion_stream",
        fake_stream_completion,
    ):
        resp = authenticated_client.post(
            "/v1/chat/completions",
            json={
                "model": "anthropic/claude-haiku-4-5",
                "messages": [{"role": "user", "content": "hi"}],
                "stream": True,
            },
        )

    assert resp.status_code == 200
    assert 'data: {"choices": [{"delta": {"content": "hi"}}]}' in resp.text
    assert "data: [DONE]" in resp.text
    assert captured["api_key"] == "tok"


@pytest.mark.asyncio
async def test_chat_overwrites_client_api_key_for_codex_oauth(
    credential_blobs, authenticated_client
) -> None:
    account_id = _account_id(authenticated_client)
    _seed_authenticated_codex_profile(credential_blobs, account_id)
    idx = ProfileIndexStore(credential_store=credential_blobs.store)
    await idx.upsert(
        Profile(
            id=profile_id_for(account_id, "codex", "default"),
            account_id=account_id,
            provider="codex",
            name="default",
            state=ProfileState.AUTHENTICATED,
        )
    )
    captured: dict = {}

    async def fake_acompletion(_self, body):
        captured.update(body)
        from types import SimpleNamespace

        return SimpleNamespace(
            model_dump=lambda: {
                "id": "x",
                "choices": [{"message": {"content": "ok"}}],
            }
        )

    with patch(
        "aigateway.plugins.codex_provider.plugin.CodexProviderPlugin.chat_completion",
        fake_acompletion,
    ):
        resp = authenticated_client.post(
            "/v1/chat/completions",
            json={
                "model": "codex/gpt-5.4-mini",
                "messages": [{"role": "user", "content": "hi"}],
                "api_key": "client-supplied-token",
            },
        )

    assert resp.status_code == 200
    assert captured["api_key"] == "tok"


@pytest.mark.asyncio
async def test_chat_maps_codex_reasoning_effort_to_reasoning(
    credential_blobs, authenticated_client
) -> None:
    account_id = _account_id(authenticated_client)
    _seed_authenticated_codex_profile(credential_blobs, account_id)
    idx = ProfileIndexStore(credential_store=credential_blobs.store)
    await idx.upsert(
        Profile(
            id=profile_id_for(account_id, "codex", "default"),
            account_id=account_id,
            provider="codex",
            name="default",
            state=ProfileState.AUTHENTICATED,
            defaults=ProfileDefaults(reasoning_effort="medium"),
        )
    )
    captured: dict = {}

    async def fake_acompletion(_self, body):
        captured.update(body)
        from types import SimpleNamespace

        return SimpleNamespace(
            model_dump=lambda: {
                "id": "x",
                "choices": [{"message": {"content": "ok"}}],
            }
        )

    with patch(
        "aigateway.plugins.codex_provider.plugin.CodexProviderPlugin.chat_completion",
        fake_acompletion,
    ):
        resp = authenticated_client.post(
            "/v1/chat/completions",
            json={
                "model": "codex/gpt-5.4-mini",
                "messages": [{"role": "user", "content": "hi"}],
            },
        )

    assert resp.status_code == 200
    assert captured["reasoning"] == {"effort": "medium"}
    assert "reasoning_effort" not in captured


@pytest.mark.asyncio
async def test_chat_maps_litellm_rate_limit_to_429(credential_blobs, authenticated_client) -> None:
    account_id = _account_id(authenticated_client)
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
    request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    response = httpx.Response(429, headers={"retry-after": "7"}, request=request)

    calls = {"n": 0}

    async def fake_chat_completion(_self, _body):
        calls["n"] += 1
        raise RateLimitError(
            "limited",
            llm_provider="anthropic",
            model="anthropic/claude-sonnet-4-5",
            response=response,
        )

    with (
        patch(
            "aigateway.plugins.anthropic_provider.plugin.AnthropicProviderPlugin.chat_completion",
            fake_chat_completion,
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

    assert resp.status_code == 429
    assert resp.headers["retry-after"] == "7"
    assert resp.json()["detail"]["code"] == "rate_limited"
    assert calls["n"] == 4  # 1 initial + 3 retries (default AIGW_RETRY_MAX_ATTEMPTS=3)


def _seed_anthropic_profile(credential_blobs, account_id: str):
    _seed_authenticated_profile(credential_blobs, account_id)
    idx = ProfileIndexStore(credential_store=credential_blobs.store)
    return idx.upsert(
        Profile(
            id=profile_id_for(account_id, "anthropic", "default"),
            account_id=account_id,
            provider="anthropic",
            name="default",
            state=ProfileState.AUTHENTICATED,
        )
    )


@pytest.mark.asyncio
async def test_chat_retries_rate_limit_then_succeeds(
    credential_blobs, authenticated_client
) -> None:
    account_id = _account_id(authenticated_client)
    await _seed_anthropic_profile(credential_blobs, account_id)

    request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    response = httpx.Response(429, headers={"retry-after": "1"}, request=request)
    calls = {"n": 0}

    async def flaky_chat_completion(_self, _body):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RateLimitError(
                "limited",
                llm_provider="anthropic",
                model="anthropic/claude-sonnet-4-5",
                response=response,
            )
        return SimpleNamespace(
            model_dump=lambda: {"id": "x", "choices": [{"message": {"content": "ok"}}]}
        )

    with (
        patch(
            "aigateway.plugins.anthropic_provider.plugin.AnthropicProviderPlugin.chat_completion",
            flaky_chat_completion,
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

    assert resp.status_code == 200
    assert calls["n"] == 2  # gateway absorbed the 429


@pytest.mark.asyncio
async def test_chat_retries_service_unavailable_then_succeeds(
    credential_blobs, authenticated_client
) -> None:
    account_id = _account_id(authenticated_client)
    await _seed_anthropic_profile(credential_blobs, account_id)

    request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    response = httpx.Response(503, request=request)
    calls = {"n": 0}

    async def flaky_chat_completion(_self, _body):
        calls["n"] += 1
        if calls["n"] == 1:
            raise ServiceUnavailableError(
                "overloaded",
                llm_provider="anthropic",
                model="anthropic/claude-sonnet-4-5",
                response=response,
            )
        return SimpleNamespace(
            model_dump=lambda: {"id": "x", "choices": [{"message": {"content": "ok"}}]}
        )

    with (
        patch(
            "aigateway.plugins.anthropic_provider.plugin.AnthropicProviderPlugin.chat_completion",
            flaky_chat_completion,
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

    assert resp.status_code == 200
    assert calls["n"] == 2


@pytest.mark.asyncio
async def test_chat_persistent_rate_limit_still_returns_429(
    credential_blobs, authenticated_client
) -> None:
    account_id = _account_id(authenticated_client)
    await _seed_anthropic_profile(credential_blobs, account_id)

    request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    response = httpx.Response(429, headers={"retry-after": "1"}, request=request)
    calls = {"n": 0}

    async def always_limited(_self, _body):
        calls["n"] += 1
        raise RateLimitError(
            "limited",
            llm_provider="anthropic",
            model="anthropic/claude-sonnet-4-5",
            response=response,
        )

    with (
        patch(
            "aigateway.plugins.anthropic_provider.plugin.AnthropicProviderPlugin.chat_completion",
            always_limited,
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

    assert resp.status_code == 429
    assert resp.headers["retry-after"] == "1"
    assert resp.json()["detail"]["code"] == "rate_limited"
    assert calls["n"] == 4  # 1 initial + 3 retries (default AIGW_RETRY_MAX_ATTEMPTS=3)


async def _seed_api_key_profile(
    credential_blobs,
    account_id: str,
    *,
    provider: str,
    service: str,
    api_key: str,
) -> None:
    credential_blobs.write(
        service,
        "default",
        json.dumps({"auth_type": "api_key", "api_key": api_key}),
    )
    idx = ProfileIndexStore(credential_store=credential_blobs.store)
    await idx.upsert(
        Profile(
            id=profile_id_for(account_id, provider, "default"),
            account_id=account_id,
            provider=provider,
            name="default",
            state=ProfileState.AUTHENTICATED,
            auth_type="api_key",
        )
    )


@pytest.mark.asyncio
async def test_chat_api_key_profile_passes_raw_anthropic_key(
    credential_blobs, authenticated_client
) -> None:
    """An api_key profile dispatches with the raw key in body["api_key"]
    (LiteLLM sends non-OAuth keys as x-api-key upstream) and injects no
    OAuth-specific extra headers (anthropic-version/-beta)."""
    account_id = _account_id(authenticated_client)
    await _seed_api_key_profile(
        credential_blobs,
        account_id,
        provider="anthropic",
        service=credential_service_for(credential_name_for(account_id, "default")),
        api_key="sk-ant-api03-raw-key",
    )
    captured: dict = {}

    async def fake_chat_completion(_self, body):
        captured.update(body)
        return SimpleNamespace(
            model_dump=lambda: {"id": "x", "choices": [{"message": {"content": "ok"}}]}
        )

    with patch(
        "aigateway.plugins.anthropic_provider.plugin.AnthropicProviderPlugin.chat_completion",
        fake_chat_completion,
    ):
        resp = authenticated_client.post(
            "/v1/chat/completions",
            json={
                "model": "anthropic/claude-haiku-4-5",
                "messages": [{"role": "user", "content": "hi"}],
            },
        )

    assert resp.status_code == 200
    assert captured["api_key"] == "sk-ant-api03-raw-key"
    assert "extra_headers" not in captured


@pytest.mark.asyncio
async def test_chat_api_key_profile_injects_gemini_header(
    credential_blobs, authenticated_client
) -> None:
    from aigateway.plugins.gemini_provider.auth import (
        credential_service_for as gemini_service_for,
    )

    account_id = _account_id(authenticated_client)
    await _seed_api_key_profile(
        credential_blobs,
        account_id,
        provider="gemini-cli",
        service=gemini_service_for(credential_name_for(account_id, "default")),
        api_key="AIzaSyChatKey",
    )
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
    assert captured["extra_headers"]["x-goog-api-key"] == "AIzaSyChatKey"
    assert "api_key" not in captured


@pytest.mark.asyncio
async def test_chat_api_key_profile_missing_blob_returns_401(
    credential_blobs, authenticated_client
) -> None:
    account_id = _account_id(authenticated_client)
    idx = ProfileIndexStore(credential_store=credential_blobs.store)
    await idx.upsert(
        Profile(
            id=profile_id_for(account_id, "anthropic", "default"),
            account_id=account_id,
            provider="anthropic",
            name="default",
            state=ProfileState.AUTHENTICATED,
            auth_type="api_key",
        )
    )

    resp = authenticated_client.post(
        "/v1/chat/completions",
        json={
            "model": "anthropic/claude-haiku-4-5",
            "messages": [{"role": "user", "content": "hi"}],
        },
    )

    assert resp.status_code == 401
    detail = resp.json()["detail"]
    assert detail["code"] == "auth_required"
    # The message is the actionable guidance the desktop surfaces (audit F26),
    # and the reauth_url must point at the api-key endpoint, not OAuth.
    assert "No API key stored" in detail["message"]
    assert detail["reauth_url"] == "/v1/auth/anthropic/profiles/default/api-key"


@pytest.mark.asyncio
async def test_chat_strips_caller_supplied_api_base(credential_blobs, authenticated_client) -> None:
    """A caller-chosen api_base would make LiteLLM send the injected
    credential to an arbitrary host — exfiltration (audit F03)."""
    account_id = _account_id(authenticated_client)
    await _seed_api_key_profile(
        credential_blobs,
        account_id,
        provider="anthropic",
        service=credential_service_for(credential_name_for(account_id, "default")),
        api_key="sk-ant-api03-raw-key",
    )
    captured: dict = {}

    async def fake_chat_completion(_self, body):
        captured.update(body)
        return SimpleNamespace(
            model_dump=lambda: {"id": "x", "choices": [{"message": {"content": "ok"}}]}
        )

    with patch(
        "aigateway.plugins.anthropic_provider.plugin.AnthropicProviderPlugin.chat_completion",
        fake_chat_completion,
    ):
        resp = authenticated_client.post(
            "/v1/chat/completions",
            json={
                "model": "anthropic/claude-haiku-4-5",
                "messages": [{"role": "user", "content": "hi"}],
                "api_base": "https://attacker.example.com/v1",
            },
        )

    assert resp.status_code == 200
    assert "api_base" not in captured
    assert captured["api_key"] == "sk-ant-api03-raw-key"


@pytest.mark.asyncio
async def test_chat_bad_anthropic_api_key_marks_profile_error(
    credential_blobs, authenticated_client
) -> None:
    """Plan D6: a bad key surfaces as 401 on first chat AND flips the profile
    to ERROR — including via the LiteLLM exception path (audit F14)."""
    from litellm.exceptions import AuthenticationError

    account_id = _account_id(authenticated_client)
    await _seed_api_key_profile(
        credential_blobs,
        account_id,
        provider="anthropic",
        service=credential_service_for(credential_name_for(account_id, "default")),
        api_key="sk-ant-api03-revoked-key",
    )

    async def rejecting_chat_completion(_self, _body):
        raise AuthenticationError(
            "invalid x-api-key",
            llm_provider="anthropic",
            model="anthropic/claude-haiku-4-5",
        )

    with patch(
        "aigateway.plugins.anthropic_provider.plugin.AnthropicProviderPlugin.chat_completion",
        rejecting_chat_completion,
    ):
        resp = authenticated_client.post(
            "/v1/chat/completions",
            json={
                "model": "anthropic/claude-haiku-4-5",
                "messages": [{"role": "user", "content": "hi"}],
            },
        )

    assert resp.status_code == 401
    assert resp.json()["detail"]["code"] == "auth_required"
    assert resp.json()["detail"]["reauth_url"] == ("/v1/auth/anthropic/profiles/default/api-key")
    status = authenticated_client.get("/v1/auth/anthropic/profiles/default/status")
    assert status.json()["state"] == "error"


@pytest.mark.asyncio
async def test_chat_api_key_auth_type_without_strategy_returns_400(
    credential_blobs, authenticated_client
) -> None:
    """A target claiming api_key for a provider without API-key support must
    fail clean, never dispatch unauthenticated (audit F15)."""
    account_id = _account_id(authenticated_client)
    idx = ProfileIndexStore(credential_store=credential_blobs.store)
    await idx.upsert(
        Profile(
            id=profile_id_for(account_id, "codex", "default"),
            account_id=account_id,
            provider="codex",
            name="default",
            state=ProfileState.AUTHENTICATED,
            auth_type="api_key",
        )
    )
    dispatched = AsyncMock()

    with patch(
        "aigateway.plugins.codex_provider.plugin.CodexProviderPlugin.chat_completion",
        dispatched,
    ):
        resp = authenticated_client.post(
            "/v1/chat/completions",
            json={
                "model": "codex/gpt-5.4-mini",
                "messages": [{"role": "user", "content": "hi"}],
            },
        )

    assert resp.status_code == 400
    assert resp.json()["detail"]["code"] == "api_key_not_supported"
    dispatched.assert_not_called()


def test_chat_api_key_connection_resolves_api_key_strategy(
    credential_blobs, authenticated_client
) -> None:
    """The oauth_connections auth_type column drives dispatch: a connection
    row flagged api_key must resolve ApiKeyStrategy against the connection's
    credential slot (audit F16 — pins the branch for the deferred creation
    endpoint)."""
    account_id = _account_id(authenticated_client)
    connection = authenticated_client.portal.call(_create_active_connection, account_id)

    async def _flag_api_key() -> None:
        connection.auth_type = "api_key"
        await connection.save(update_fields=["auth_type"])

    authenticated_client.portal.call(_flag_api_key)
    credential_blobs.write(
        credential_service_for(credential_key_for(account_id, connection.id)),
        "default",
        json.dumps({"auth_type": "api_key", "api_key": "sk-ant-api03-conn-key"}),
    )
    captured: dict = {}

    async def fake_chat_completion(_self, body):
        captured.update(body)
        return SimpleNamespace(
            model_dump=lambda: {"id": "x", "choices": [{"message": {"content": "ok"}}]}
        )

    with patch(
        "aigateway.plugins.anthropic_provider.plugin.AnthropicProviderPlugin.chat_completion",
        fake_chat_completion,
    ):
        resp = authenticated_client.post(
            "/v1/chat/completions",
            json={
                "model": "anthropic/claude-haiku-4-5",
                "messages": [{"role": "user", "content": "hi"}],
            },
        )

    assert resp.status_code == 200
    assert captured["api_key"] == "sk-ant-api03-conn-key"


def test_chat_api_key_connection_missing_blob_reauth_url_is_connection_native(
    credential_blobs, authenticated_client
) -> None:
    """When an api-key CONNECTION has no/blank credential, the 401 reauth_url
    must point at the connection's replace-key route, not the legacy profile
    api-key endpoint (review F3 — avoid reintroducing profile shadowing)."""
    account_id = _account_id(authenticated_client)
    connection = authenticated_client.portal.call(_create_active_connection, account_id)

    async def _flag_api_key() -> None:
        connection.auth_type = "api_key"
        await connection.save(update_fields=["auth_type"])

    authenticated_client.portal.call(_flag_api_key)
    # Intentionally write NO credential blob -> CredentialNotFoundError on dispatch.
    resp = authenticated_client.post(
        "/v1/chat/completions",
        json={
            "model": "anthropic/claude-haiku-4-5",
            "messages": [{"role": "user", "content": "hi"}],
        },
    )

    assert resp.status_code == 401
    detail = resp.json()["detail"]
    assert detail["code"] == "auth_required"
    assert detail["reauth_url"] == f"/v1/oauth/connections/{connection.id}/api-key"
    assert "/profiles/" not in detail["reauth_url"]


def test_chat_multiple_active_api_key_connections_is_ambiguous(authenticated_client) -> None:
    """Two active api-key connections + X-Profile=default -> 409 connection_ambiguous.
    The ambiguity guard is auth-type-agnostic (mirrors the OAuth case)."""
    account_id = _account_id(authenticated_client)

    async def _two_api_key_connections() -> None:
        store = OAuthConnectionStore()
        await store.create_api_key(
            account_id=account_id, provider="anthropic", label="work-key", connection_id=uuid4()
        )
        await store.create_api_key(
            account_id=account_id, provider="anthropic", label="home-key", connection_id=uuid4()
        )

    authenticated_client.portal.call(_two_api_key_connections)
    resp = authenticated_client.post(
        "/v1/chat/completions",
        json={
            "model": "anthropic/claude-haiku-4-5",
            "messages": [{"role": "user", "content": "hi"}],
        },
    )
    assert resp.status_code == 409
    assert resp.json()["detail"]["code"] == "connection_ambiguous"
