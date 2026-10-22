from __future__ import annotations

from aigateway.core.loader import load_plugins
from aigateway.core.registry import ProviderRegistry
from aigateway.plugins.codex_provider.auth import CodexOAuth
from aigateway.plugins.codex_provider.oauth_config import (
    CODEX_AUTHORIZE_URL,
    CODEX_CLIENT_ID,
    CODEX_REDIRECT_PATH,
    CODEX_TOKEN_URL,
)


def test_codex_provider_loads_with_oauth_config_and_models() -> None:
    registry = ProviderRegistry()
    load_plugins(registry)

    plugin = registry.get("codex")

    assert plugin is not None
    assert plugin.custom_llm_provider == "codex"
    assert plugin.supports_chat_streaming() is False
    cfg = plugin.oauth_config()
    assert cfg is not None
    assert cfg.authorize_url == CODEX_AUTHORIZE_URL
    assert cfg.token_url == CODEX_TOKEN_URL
    assert cfg.client_id == CODEX_CLIENT_ID
    assert cfg.redirect_path == CODEX_REDIRECT_PATH
    assert "offline_access" in cfg.scopes
    names = {entry.model_name for entry in plugin.register_models()}
    assert names == {
        "codex/gpt-6-astra",
        "codex/gpt-5.6-sol",
        "codex/gpt-5.6-terra",
        "codex/gpt-5.6-luna",
    }


def test_codex_provider_creates_codex_oauth_strategy() -> None:
    registry = ProviderRegistry()
    load_plugins(registry)
    plugin = registry.get("codex")
    assert plugin is not None

    strategy = plugin.oauth_strategy_for("default")

    assert isinstance(strategy, CodexOAuth)
    assert strategy.profile_name == "default"


def test_models_route_includes_codex_models(authenticated_client) -> None:
    response = authenticated_client.get("/v1/models")

    assert response.status_code == 200
    models = {entry["id"]: entry for entry in response.json()["data"]}
    assert models["codex/gpt-6-astra"]["owned_by"] == "codex"
    assert "codex/codex-auto-review" not in models
