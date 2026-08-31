from __future__ import annotations

import os

from aigateway.core.plugin_base import ModelEntry
from aigateway.plugins.anthropic_provider.settings import AnthropicPluginSettings


def _clear_anthropic_env(monkeypatch) -> None:
    for key in list(os.environ):
        if key.startswith("AIGW_ANTHROPIC_"):
            monkeypatch.delenv(key, raising=False)


def test_anthropic_settings_defaults_preserve_current_values(monkeypatch) -> None:
    _clear_anthropic_env(monkeypatch)
    monkeypatch.setenv("USER", "alice")

    settings = AnthropicPluginSettings()

    assert settings.authorize_url == "https://claude.com/cai/oauth/authorize"
    assert settings.token_url == "https://platform.claude.com/v1/oauth/token"
    assert settings.client_id == "9d1c250a-e61b-44d9-88ed-5944d1962f5e"
    assert settings.scopes == [
        "user:profile",
        "user:inference",
        "user:sessions:claude_code",
        "user:mcp_servers",
        "user:file_upload",
    ]
    assert settings.refresh_scopes == settings.scopes
    assert settings.redirect_path == "/callback"
    assert settings.authorize_extra_params == {"code": "true"}
    assert settings.api_version == "2023-06-01"
    assert "oauth-2025-04-20" in settings.beta
    assert settings.claude_code_keychain_service == "Claude Code-credentials"
    assert settings.keychain_account == "default"
    assert settings.bootstrap_user == "alice"
    assert [model.model_name for model in settings.models] == [
        "claude-opus-5",
        "claude-opus-4-8",
        "claude-opus-4-7",
        "claude-opus-4-6",
        "claude-opus-4-5",
        "claude-fable-5",
        "claude-sonnet-5",
        "claude-sonnet-4-6",
        "claude-sonnet-4-5",
        "claude-haiku-4-5",
    ]
    # Every entry's litellm model string must be the "anthropic/"-prefixed alias
    # so the gateway routes it to the Anthropic provider.
    for model in settings.models:
        assert model.litellm_params == {"model": f"anthropic/{model.model_name}"}


def test_ome_818_direct_claude_ids_are_seeded(monkeypatch) -> None:
    _clear_anthropic_env(monkeypatch)
    settings = AnthropicPluginSettings()
    names = [model.model_name for model in settings.models]
    # OME-818: live-verified direct ids (Anthropic GET /v1/models, 2026-08-13).
    for new_id in [
        "claude-opus-5",
        "claude-fable-5",
        "claude-sonnet-5",
        "claude-opus-4-6",
        "claude-opus-4-5",
    ]:
        assert new_id in names, f"{new_id} missing from seed"
    # INVARIANT: a direct id is unprefixed + hyphenated (no dots, no 'anthropic/' on model_name);
    # the 'anthropic/' prefix lives ONLY in litellm_params so the gateway routes to the provider.
    for model in settings.models:
        assert "." not in model.model_name, model.model_name
        assert not model.model_name.startswith("anthropic/"), model.model_name
        assert model.litellm_params == {"model": f"anthropic/{model.model_name}"}


def test_anthropic_settings_env_overrides(monkeypatch) -> None:
    _clear_anthropic_env(monkeypatch)
    monkeypatch.setenv("AIGW_ANTHROPIC_AUTHORIZE_URL", "https://auth.example/authorize")
    monkeypatch.setenv("AIGW_ANTHROPIC_TOKEN_URL", "https://auth.example/token")
    monkeypatch.setenv("AIGW_ANTHROPIC_CLIENT_ID", "client-env")
    monkeypatch.setenv("AIGW_ANTHROPIC_SCOPES", '["scope:one","scope:two"]')
    monkeypatch.setenv("AIGW_ANTHROPIC_REFRESH_SCOPES", '["scope:refresh"]')
    monkeypatch.setenv("AIGW_ANTHROPIC_REDIRECT_PATH", "/env-callback")
    monkeypatch.setenv("AIGW_ANTHROPIC_AUTHORIZE_EXTRA_PARAMS", '{"code":"false"}')
    monkeypatch.setenv("AIGW_ANTHROPIC_API_VERSION", "2024-01-01")
    monkeypatch.setenv("AIGW_ANTHROPIC_BETA", "beta-env")
    monkeypatch.setenv(
        "AIGW_ANTHROPIC_MODELS",
        '[{"model_name":"claude-env","litellm_params":{"model":"anthropic/claude-env"}}]',
    )
    monkeypatch.setenv("AIGW_ANTHROPIC_CLAUDE_CODE_KEYCHAIN_SERVICE", "CC Env")
    monkeypatch.setenv("AIGW_ANTHROPIC_KEYCHAIN_ACCOUNT", "account-env")
    monkeypatch.setenv("AIGW_ANTHROPIC_BOOTSTRAP_USER", "bootstrap-env")

    settings = AnthropicPluginSettings()

    assert settings.authorize_url == "https://auth.example/authorize"
    assert settings.token_url == "https://auth.example/token"
    assert settings.client_id == "client-env"
    assert settings.scopes == ["scope:one", "scope:two"]
    assert settings.refresh_scopes == ["scope:refresh"]
    assert settings.redirect_path == "/env-callback"
    assert settings.authorize_extra_params == {"code": "false"}
    assert settings.api_version == "2024-01-01"
    assert settings.beta == "beta-env"
    assert settings.models == [
        ModelEntry(model_name="claude-env", litellm_params={"model": "anthropic/claude-env"})
    ]
    assert settings.claude_code_keychain_service == "CC Env"
    assert settings.keychain_account == "account-env"
    assert settings.bootstrap_user == "bootstrap-env"


def test_anthropic_settings_constructor_overrides_env(monkeypatch) -> None:
    _clear_anthropic_env(monkeypatch)
    monkeypatch.setenv("AIGW_ANTHROPIC_TOKEN_URL", "https://env.example/token")
    monkeypatch.setenv(
        "AIGW_ANTHROPIC_MODELS",
        '[{"model_name":"claude-env","litellm_params":{"model":"anthropic/claude-env"}}]',
    )
    explicit_model = ModelEntry(
        model_name="claude-explicit",
        litellm_params={"model": "anthropic/claude-explicit"},
    )

    settings = AnthropicPluginSettings(
        token_url="https://explicit.example/token",
        models=[explicit_model],
    )

    assert settings.token_url == "https://explicit.example/token"
    assert settings.models == [explicit_model]


def test_anthropic_provider_uses_injected_settings() -> None:
    from aigateway.plugins.anthropic_provider.auth import AnthropicOAuth
    from aigateway.plugins.anthropic_provider.plugin import AnthropicProviderPlugin

    model = ModelEntry(
        model_name="claude-custom",
        litellm_params={"model": "anthropic/claude-custom"},
    )
    settings = AnthropicPluginSettings(
        authorize_url="https://custom.example/authorize",
        token_url="https://custom.example/token",
        client_id="client-custom",
        scopes=["scope:custom"],
        redirect_path="/custom-callback",
        authorize_extra_params={"code": "custom"},
        keychain_account="account-custom",
        models=[model],
    )

    plugin = AnthropicProviderPlugin(settings=settings)

    assert plugin.register_models() == [model]
    cfg = plugin.oauth_config()
    assert cfg.authorize_url == "https://custom.example/authorize"
    assert cfg.token_url == "https://custom.example/token"
    assert cfg.client_id == "client-custom"
    assert cfg.scopes == ["scope:custom"]
    assert cfg.redirect_path == "/custom-callback"
    assert cfg.extra_authorize_params == {"code": "custom"}
    strategy = plugin.oauth_strategy_for("work")
    assert isinstance(strategy, AnthropicOAuth)
    assert strategy.credential_account() == "account-custom"


def test_there_is_no_deployment_discovery_credential(monkeypatch) -> None:
    """OME-1026 rework — the dedicated deployment discovery key was REMOVED.

    # WHY this test replaces the three that previously specified that key: the owner
    # decision is that Anthropic discovery is PRIVATE and profile-scoped. A
    # deployment-wide credential would make one key's entitlements the whole
    # deployment's listing and would answer "whose models are these?" with "the
    # operator's", which is the design that was rejected.
    # INVARIANT: absence is asserted structurally (the field does not exist) AND
    # operationally (setting the old env var changes nothing), so a well-meaning
    # re-introduction fails here rather than silently restoring global egress.
    """
    _clear_anthropic_env(monkeypatch)

    assert "discovery_api_key" not in AnthropicPluginSettings.model_fields

    monkeypatch.setenv("AIGW_ANTHROPIC_DISCOVERY_API_KEY", "sk-ant-not-a-real-key-0123456789")
    settings = AnthropicPluginSettings()

    assert not hasattr(settings, "discovery_api_key")
    # ``extra="ignore"``: the stale variable is dropped, not stored under another name.
    assert "not-a-real-key" not in repr(settings)
    assert "not-a-real-key" not in str(settings.model_dump())


def test_live_models_defaults_true_and_env_overrides(monkeypatch) -> None:
    """OME-1026 rework — the off-switch for Anthropic's live catalog.

    # WHY default True is safe with no credential in sight: the flag only decides
    # whether the provider DECLARES a discovery scope. Egress still requires an
    # authenticated api-key profile whose owner asks for its own model list, so a
    # deployment that stores no key performs zero catalog egress with the flag on.
    """
    _clear_anthropic_env(monkeypatch)

    assert AnthropicPluginSettings().live_models is True

    monkeypatch.setenv("AIGW_ANTHROPIC_LIVE_MODELS", "false")
    assert AnthropicPluginSettings().live_models is False
