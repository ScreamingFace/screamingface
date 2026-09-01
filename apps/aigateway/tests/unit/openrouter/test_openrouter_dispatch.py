"""OpenRouter plugin surface + BYOK dispatch wiring (OME-428 Phase 2).

Pins plan decisions D1 (normal auto-discovered provider), D2 (disabled by
default fails closed), D5 (non-streaming), D8 (exactly one gateway prefix,
validated upstream ID), and the account-scoped ApiKeyStrategy lifecycle.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import patch
from uuid import UUID

import pytest
from fastapi import HTTPException

from aigateway.core.api_key_strategy import ApiKeyStrategy
from aigateway.core.oauth.store import OAuthConnectionStore, credential_key_for
from aigateway.plugins.openrouter_provider import plugin as openrouter_plugin_module
from aigateway.plugins.openrouter_provider.plugin import OpenRouterProviderPlugin
from aigateway.plugins.openrouter_provider.settings import OpenRouterPluginSettings


def _plugin(*, enabled: bool) -> OpenRouterProviderPlugin:
    return OpenRouterProviderPlugin(OpenRouterPluginSettings(enabled=enabled))


def _account_id(client) -> str:
    return client.get("/v1/auth/me").json()["id"]


def _create_openrouter_connection(client) -> dict[str, Any]:
    response = client.post(
        "/v1/oauth/connections/api-key",
        json={"provider": "openrouter", "label": "work-openrouter", "api_key": "sk-or-v1-test"},
    )
    assert response.status_code == 201, response.text
    return cast("dict[str, Any]", response.json())


async def _set_connection_auth_type(account_id: str, connection_id: str, auth_type: str) -> None:
    connection = await OAuthConnectionStore().get(account_id, UUID(connection_id))
    assert connection is not None
    connection.auth_type = auth_type
    await connection.save(update_fields=["auth_type"])


# --- D1: normal auto-discovery, no loader/registry edits ---


def test_plugin_is_autodiscovered_into_registry(client) -> None:
    assert client.app.state.providers.get("openrouter") is not None


# --- D2: disabled by default contributes nothing and fails closed ---


def test_register_models_empty_when_disabled() -> None:
    assert _plugin(enabled=False).register_models() == []


def test_register_models_seeds_when_enabled() -> None:
    entries = _plugin(enabled=True).register_models()
    assert [entry.model_name for entry in entries] == OpenRouterPluginSettings().default_models
    for entry in entries:
        assert entry.litellm_params == {"model": entry.model_name}


def test_api_key_strategy_none_when_disabled() -> None:
    assert _plugin(enabled=False).api_key_strategy_for("default") is None


def test_api_key_strategy_when_enabled_is_account_scoped() -> None:
    strategy = _plugin(enabled=True).api_key_strategy_for("work-openrouter")
    assert isinstance(strategy, ApiKeyStrategy)
    assert strategy.credential_service() == "aigateway:openrouter:work-openrouter"
    assert strategy.credential_account() == "default"


def test_disabled_provider_rejects_api_key_connection_creation(authenticated_client) -> None:
    resp = authenticated_client.post(
        "/v1/oauth/connections/api-key",
        json={"provider": "openrouter", "label": "work", "api_key": "sk-or-v1-x"},
    )
    assert resp.status_code == 400
    assert resp.json()["detail"]["code"] == "api_key_not_supported"


def test_disabled_provider_chat_fails_closed_with_404(authenticated_client) -> None:
    resp = authenticated_client.post(
        "/v1/chat/completions",
        json={
            "model": "openrouter/anthropic/claude-fable-5",
            "messages": [{"role": "user", "content": "hi"}],
        },
    )
    assert resp.status_code == 404
    assert resp.json()["detail"]["code"] == "profile_not_found"


# --- capabilities: D5 non-streaming, api-key-only, no chatless dispatch ---


def test_capability_matrix() -> None:
    plugin = _plugin(enabled=True)
    assert plugin.supports_api_key() is True
    assert plugin.supports_chat_streaming() is False
    assert plugin.allows_chatless_profile() is False
    assert plugin.oauth_config() is None


@pytest.mark.parametrize(
    ("status_code", "should_mark"),
    [
        (401, True),
        (400, False),
        (402, False),
        (403, False),
        (408, False),
        (429, False),
        (500, False),
        (503, False),
    ],
)
def test_only_401_marks_credential_errored(status_code: int, should_mark: bool) -> None:
    plugin = _plugin(enabled=True)
    assert plugin.should_mark_profile_error_on_dispatch_status(status_code) is should_mark


# --- D8: exactly one gateway prefix, validated upstream remainder ---


@pytest.mark.parametrize(
    "model",
    [
        "openrouter/anthropic/claude-fable-5",
        "openrouter/mistralai/devstral-2.1:free",  # valid unlisted + variant
        "openrouter/openrouter/auto",  # router slug is ordinary syntax in BYOK
    ],
)
def test_prepare_chat_body_accepts_valid_models_unchanged(model: str) -> None:
    plugin = _plugin(enabled=True)
    body = {"model": model, "messages": [{"role": "user", "content": "hi"}]}
    out = plugin.prepare_chat_body(body)
    assert out is not body  # copy, never mutate the caller's dict
    assert out["model"] == model  # LiteLLM strips the single gateway prefix at the wire
    assert out["messages"] == body["messages"]


@pytest.mark.parametrize(
    "model",
    [
        "anthropic/claude-fable-5",  # missing gateway prefix
        "openrouter/anthropic",  # one upstream segment
        "openrouter/a/b/c",  # extra slash
        "openrouter/ä/b",  # Unicode
        "openrouter/a/b:",  # empty variant
        "openrouter/",  # empty upstream
        None,  # non-string
        7,
    ],
)
def test_prepare_chat_body_rejects_invalid_models(model: object) -> None:
    plugin = _plugin(enabled=True)
    with pytest.raises(HTTPException) as excinfo:
        plugin.prepare_chat_body({"model": model, "messages": []})
    assert excinfo.value.status_code == 400
    detail = cast("dict[str, Any]", excinfo.value.detail)
    assert detail["code"] == "invalid_model"


# --- BYOK lifecycle end-to-end: connection create -> encrypted blob -> dispatch ---


@pytest.fixture()
def enabled_openrouter(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        openrouter_plugin_module.PLUGIN, "settings", OpenRouterPluginSettings(enabled=True)
    )


def test_chat_openrouter_byok_end_to_end(
    enabled_openrouter, credential_blobs, authenticated_client
) -> None:
    """Enabled plugin: the api-key connection route stores the key encrypted,
    and chat resolves it into body["api_key"] with the model untranslated
    (single gateway prefix) for LiteLLM's openrouter provider."""
    create = authenticated_client.post(
        "/v1/oauth/connections/api-key",
        json={"provider": "openrouter", "label": "work-openrouter", "api_key": "sk-or-v1-test"},
    )
    assert create.status_code == 201, create.text
    assert create.json()["provider"] == "openrouter"
    assert "sk-or-v1-test" not in create.text  # key is never echoed

    captured: dict = {}

    async def fake_chat_completion(_self, body):
        captured.update(body)
        return SimpleNamespace(
            model_dump=lambda: {"id": "or-1", "choices": [{"message": {"content": "ok"}}]}
        )

    with patch(
        "aigateway.plugins.openrouter_provider.plugin.OpenRouterProviderPlugin.chat_completion",
        fake_chat_completion,
    ):
        resp = authenticated_client.post(
            "/v1/chat/completions",
            json={
                "model": "openrouter/anthropic/claude-fable-5",
                "messages": [{"role": "user", "content": "hi"}],
            },
        )

    assert resp.status_code == 200, resp.text
    assert captured["model"] == "openrouter/anthropic/claude-fable-5"
    assert captured["api_key"] == "sk-or-v1-test"


def test_chat_repairs_openrouter_oauth_connection_with_api_key_blob(
    enabled_openrouter,
    authenticated_client,
) -> None:
    account_id = _account_id(authenticated_client)
    created = _create_openrouter_connection(authenticated_client)
    authenticated_client.portal.call(
        _set_connection_auth_type,
        account_id,
        created["id"],
        "oauth",
    )
    captured: dict[str, Any] = {}

    async def fake_chat_completion(_self, body):
        captured.update(body)
        return SimpleNamespace(
            model_dump=lambda: {"id": "or-1", "choices": [{"message": {"content": "ok"}}]}
        )

    with patch(
        "aigateway.plugins.openrouter_provider.plugin.OpenRouterProviderPlugin.chat_completion",
        fake_chat_completion,
    ):
        response = authenticated_client.post(
            "/v1/chat/completions",
            json={
                "model": "openrouter/anthropic/claude-fable-5",
                "messages": [{"role": "user", "content": "hi"}],
            },
        )

    assert response.status_code == 200, response.text
    assert captured["api_key"] == "sk-or-v1-test"
    repaired = authenticated_client.portal.call(
        OAuthConnectionStore().get,
        account_id,
        UUID(created["id"]),
    )
    assert repaired is not None
    assert repaired.auth_type == "api_key"


def test_chat_corrupted_openrouter_oauth_connection_without_key_does_not_dispatch(
    enabled_openrouter,
    credential_blobs,
    authenticated_client,
) -> None:
    account_id = _account_id(authenticated_client)
    created = _create_openrouter_connection(authenticated_client)
    authenticated_client.portal.call(
        _set_connection_auth_type,
        account_id,
        created["id"],
        "oauth",
    )
    credential_blobs.delete(
        f"aigateway:openrouter:{credential_key_for(account_id, created['id'])}",
        "default",
    )

    with patch(
        "aigateway.plugins.openrouter_provider.plugin.OpenRouterProviderPlugin.chat_completion",
    ) as dispatched:
        response = authenticated_client.post(
            "/v1/chat/completions",
            json={
                "model": "openrouter/anthropic/claude-fable-5",
                "messages": [{"role": "user", "content": "hi"}],
            },
        )

    assert response.status_code == 401
    detail = response.json()["detail"]
    assert detail["code"] == "auth_required"
    assert detail["reauth_url"] == f"/v1/oauth/connections/{created['id']}/api-key"
    dispatched.assert_not_called()
    connection = authenticated_client.portal.call(
        OAuthConnectionStore().get,
        account_id,
        UUID(created["id"]),
    )
    assert connection is not None
    assert connection.auth_type == "api_key"
    assert connection.status == "error"


def test_chat_openrouter_stream_rejected_before_dispatch(
    enabled_openrouter, credential_blobs, authenticated_client
) -> None:
    """D5: stream:true fails with streaming_not_supported and never dispatches."""
    create = authenticated_client.post(
        "/v1/oauth/connections/api-key",
        json={"provider": "openrouter", "label": "work-openrouter", "api_key": "sk-or-v1-test"},
    )
    assert create.status_code == 201, create.text

    with patch(
        "aigateway.plugins.openrouter_provider.plugin.OpenRouterProviderPlugin.chat_completion",
    ) as dispatched:
        resp = authenticated_client.post(
            "/v1/chat/completions",
            json={
                "model": "openrouter/anthropic/claude-fable-5",
                "messages": [{"role": "user", "content": "hi"}],
                "stream": True,
            },
        )

    assert resp.status_code == 400
    detail = resp.json()["detail"]
    assert detail["code"] == "streaming_not_supported"
    assert detail["provider"] == "openrouter"
    dispatched.assert_not_called()


@pytest.mark.asyncio
async def test_plugin_model_dump_failure_is_marked_as_local_conversion_error() -> None:
    class _BrokenResponse:
        def model_dump(self) -> dict[str, Any]:
            raise ValueError("provider-controlled secret")

    async def acompletion(**_kwargs: Any) -> _BrokenResponse:
        return _BrokenResponse()

    with patch("litellm.acompletion", acompletion), pytest.raises(HTTPException) as excinfo:
        await _plugin(enabled=True).chat_completion(
            {"model": "openrouter/anthropic/claude-fable-5", "api_key": "sk-test"}
        )
    assert excinfo.value.status_code == 502
    assert getattr(excinfo.value, "aigw_response_conversion_error", False) is True
    assert "provider-controlled secret" not in str(excinfo.value.detail)
