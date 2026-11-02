from __future__ import annotations

import httpx
import pytest

from aigateway.core.loader import load_plugins
from aigateway.core.registry import ProviderRegistry
from aigateway.plugins.gemini_provider.auth import GeminiOAuth
from aigateway.plugins.gemini_provider.chat_handler import (
    GeminiCustomLLM,
    ensure_litellm_gemini_provider_registered,
)
from aigateway.plugins.gemini_provider.oauth_config import (
    GEMINI_AUTHORIZE_URL,
    GEMINI_CLIENT_ID,
    GEMINI_REDIRECT_PATH,
    GEMINI_TOKEN_URL,
)
from aigateway.plugins.gemini_provider.plugin import GeminiProviderPlugin


def test_gemini_provider_loads_with_oauth_config_and_models() -> None:
    registry = ProviderRegistry()
    load_plugins(registry)

    plugin = registry.get("gemini-cli")

    assert plugin is not None
    assert plugin.custom_llm_provider == "gemini-cli"
    assert plugin.credential_service_provider() == "gemini"
    assert plugin.allows_chatless_credential() is True
    assert plugin.supports_chat_streaming() is False
    assert plugin.should_mark_credential_error_on_dispatch_status(401) is True
    assert plugin.should_mark_credential_error_on_dispatch_status(403) is True
    assert plugin.should_mark_credential_error_on_dispatch_status(429) is False
    cfg = plugin.oauth_config()
    assert cfg is not None
    assert cfg.authorize_url == GEMINI_AUTHORIZE_URL
    assert cfg.token_url == GEMINI_TOKEN_URL
    assert cfg.client_id == GEMINI_CLIENT_ID
    assert cfg.redirect_path == GEMINI_REDIRECT_PATH
    assert cfg.extra_authorize_params == {"access_type": "offline", "prompt": "consent"}
    assert "https://www.googleapis.com/auth/cloud-platform" in cfg.scopes
    assert "https://www.googleapis.com/auth/userinfo.email" in cfg.scopes
    assert "https://www.googleapis.com/auth/userinfo.profile" in cfg.scopes
    names = {entry.model_name for entry in plugin.register_models()}
    assert "gemini-cli/gemini-2.5-flash" in names
    assert "gemini-cli/gemini-2.5-pro" in names


def test_gemini_provider_creates_gemini_oauth_strategy() -> None:
    registry = ProviderRegistry()
    load_plugins(registry)
    plugin = registry.get("gemini-cli")
    assert plugin is not None

    strategy = plugin.oauth_strategy_for("default")

    assert isinstance(strategy, GeminiOAuth)
    assert strategy.profile_name == "default"


def test_prepare_chat_body_strips_caller_supplied_auth_headers() -> None:
    prepared = GeminiProviderPlugin().prepare_chat_body(
        {
            "model": "gemini-cli/gemini-2.5-flash",
            "messages": [{"role": "user", "content": "hi"}],
            "api_key": "client-supplied",
            "extra_headers": {
                "Authorization": "Bearer attacker",
                "X-AIGW-Gemini-Profile": "attacker-profile",
                "x-goog-api-key": "attacker-key",
                "x-goog-user-project": "attacker-project",
                "X-Trace-Id": "trace-1",
            },
        }
    )

    assert "api_key" not in prepared
    assert prepared["extra_headers"] == {"X-Trace-Id": "trace-1"}


def test_prepare_chat_body_drops_non_dict_extra_headers() -> None:
    """A non-dict extra_headers reaching the handler crashes the chatless
    path with a 500 instead of a clean 401 (audit F06)."""
    prepared = GeminiProviderPlugin().prepare_chat_body(
        {
            "model": "gemini-cli/gemini-2.5-flash",
            "messages": [{"role": "user", "content": "hi"}],
            "extra_headers": ["not", "a", "dict"],
        }
    )

    assert "extra_headers" not in prepared


def test_models_route_includes_gemini_models(authenticated_client) -> None:
    response = authenticated_client.get("/v1/models")

    assert response.status_code == 200
    models = {entry["id"]: entry for entry in response.json()["data"]}
    assert models["gemini-cli/gemini-2.5-flash"]["owned_by"] == "gemini-cli"


@pytest.mark.asyncio
async def test_chat_completion_carries_profile_api_key_into_handler(monkeypatch) -> None:
    """Exercise the REAL plugin.chat_completion: its headers=body["extra_headers"]
    line is the only conduit carrying the gateway-injected per-profile key from
    the chat body into the custom handler (audit F07)."""
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["headers"] = dict(request.headers)
        return httpx.Response(
            200,
            json={
                "candidates": [{"content": {"parts": [{"text": "pong"}], "role": "model"}}],
                "usageMetadata": {"totalTokenCount": 5},
            },
        )

    transport = httpx.MockTransport(handler)
    custom = GeminiCustomLLM(
        http_client_factory=lambda: httpx.AsyncClient(
            transport=transport, timeout=httpx.Timeout(5.0)
        )
    )
    ensure_litellm_gemini_provider_registered(custom)
    try:
        response = await GeminiProviderPlugin().chat_completion(
            {
                "model": "gemini-cli/gemini-2.5-flash",
                "messages": [{"role": "user", "content": "ping"}],
                # Post-injection body shape: the gateway merged the strategy's
                # header into extra_headers after prepare_chat_body ran.
                "extra_headers": {"x-goog-api-key": "profile-key"},
            }
        )
    finally:
        ensure_litellm_gemini_provider_registered(GeminiCustomLLM())

    assert captured["headers"]["x-goog-api-key"] == "profile-key"
    assert captured["url"].startswith(
        "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash"
    )
    assert "authorization" not in captured["headers"]
    assert response.choices[0].message.content == "pong"
