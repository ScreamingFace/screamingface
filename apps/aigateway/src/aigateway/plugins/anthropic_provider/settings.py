from __future__ import annotations

from pydantic import Field
from pydantic_settings import SettingsConfigDict

from aigateway.core.plugin_base import ModelEntry, PluginSettings


def _default_scopes() -> list[str]:
    return [
        "user:profile",
        "user:inference",
        "user:sessions:claude_code",
        "user:mcp_servers",
        "user:file_upload",
    ]


def _default_models() -> list[ModelEntry]:
    """Claude models the gateway routes by default.

    Single source of truth for the SF Settings model dropdown: the
    aigw-claude-backend plugin derives its suggestions from this list via
    ``GET /v1/models`` (SF-284), so it must NOT be copied SF-side.

    Ordered newest-first within each tier (opus, fable, sonnet, haiku). Older
    snapshots are kept alongside the latest so existing configs pinned to
    them (e.g. the ``claude-sonnet-4-5`` default) keep routing.

    OME-818: the 5.x line (opus-5 / fable-5 / sonnet-5) and the opus 4.5/4.6
    snapshots were verified live against Anthropic ``GET /v1/models`` on
    2026-08-13. Ids are the bare aliases (matching the existing 4-5 tier
    convention); the ``anthropic/`` prefix lives only in ``litellm_params``.
    """
    names = [
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
    return [
        ModelEntry(model_name=name, litellm_params={"model": f"anthropic/{name}"}) for name in names
    ]


class AnthropicPluginSettings(PluginSettings):
    model_config = SettingsConfigDict(
        env_prefix="AIGW_ANTHROPIC_",
        extra="ignore",
        populate_by_name=True,
    )

    # Claude subscription login, not the platform/console API-key OAuth entrypoint.
    authorize_url: str = "https://claude.com/cai/oauth/authorize"
    # Verified from Claude Code's public OAuth client flow.
    token_url: str = "https://platform.claude.com/v1/oauth/token"
    client_id: str = "9d1c250a-e61b-44d9-88ed-5944d1962f5e"
    # Claude subscription tokens carry user scopes; org:create_api_key routes to Console billing.
    scopes: list[str] = Field(default_factory=_default_scopes)
    refresh_scopes: list[str] = Field(default_factory=_default_scopes)
    redirect_path: str = "/callback"
    # Required by the Claude Code OAuth app to show the user-consent screen.
    authorize_extra_params: dict[str, str] = Field(default_factory=lambda: {"code": "true"})

    api_version: str = "2023-06-01"
    beta: str = ",".join(
        [
            "claude-code-20250219",
            "oauth-2025-04-20",
            "interleaved-thinking-2025-05-14",
            "prompt-caching-scope-2026-01-05",
        ]
    )

    models: list[ModelEntry] = Field(default_factory=_default_models)
    validation_model: str | None = None

    keychain_account: str = "default"
