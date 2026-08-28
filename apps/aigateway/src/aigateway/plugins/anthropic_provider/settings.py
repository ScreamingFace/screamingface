from __future__ import annotations

import os

from pydantic import Field, SecretStr, field_validator
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

    Provider-owned source of truth for the compiled fallback listing. The historical
    SF-284 ``aigw-claude-backend`` derived its suggestions from ``GET /v1/models``
    rather than copying this list, but that consumer was removed before this baseline.

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

    # OME-1026 (D2): the DEDICATED operator secret that opts this deployment into live
    # Anthropic model-LIST discovery. Deployment configuration in the AIGATEWAY_SECRET_KEY
    # sense — NEVER a ``credential_blobs`` credential, never used for chat, never logged,
    # never part of the discovery cache identity, and attached to no origin but the
    # allowlisted Anthropic one.
    # INVARIANT: None (the default) means ZERO Anthropic catalog egress and exactly the
    # compiled seed listing below. A DECLARED-but-blank value normalizes to None too — see
    # ``_blank_discovery_key_is_absent``. Account API keys and Claude-subscription OAuth
    # tokens are off limits for discovery, so this is the ONLY credential that can ever
    # reach it.
    discovery_api_key: SecretStr | None = None
    # OME-1026 (D3): gates LIVE catalog discovery for the /v1/models LISTING (never
    # dispatch), mirroring AIGW_OPENROUTER_LIVE_MODELS. The KEY is the real opt-in — a
    # source is declared iff ``live_models and discovery_api_key is not None`` — so this is
    # the fast off-switch that silences discovery WITHOUT unconfiguring the credential.
    live_models: bool = True
    models: list[ModelEntry] = Field(default_factory=_default_models)
    validation_model: str | None = None

    claude_code_keychain_service: str = "Claude Code-credentials"
    keychain_account: str = "default"
    bootstrap_user: str = Field(default_factory=lambda: os.environ.get("USER", ""))

    @field_validator("discovery_api_key", mode="after")
    @classmethod
    def _blank_discovery_key_is_absent(cls, value: SecretStr | None) -> SecretStr | None:
        """An empty or whitespace-only key is NOT a credential — read it as absent.

        # WHY at the field and not at the two D3 gates: an environment variable that exists
        # but holds an empty string is a real deployment shape, not a typo — compose
        # interpolating ``${VAR}`` for an unset host var, an existing-but-empty Kubernetes
        # Secret key, or a chart that emits every key so an operator's explicit opt-out
        # stays visible in the manifest. Left raw, ``SecretStr('')`` is not ``None``, so
        # D3's ``discovery_api_key is not None`` predicate would declare a discovery source
        # and dial Anthropic with an empty ``x-api-key`` — egress on a deployment that
        # configured no key, contradicting the opt-in guarantee and DEPLOYMENT.md's
        # documented rollback.
        # INVARIANT: normalizing HERE keeps that predicate literally true and gives every
        # reader of this field the same answer, instead of a blank-check repeated per gate.
        # AIDEV-NOTE: ``strip()`` only DECIDES; a surviving key is returned untouched, never
        # trimmed — a credential's exact bytes are the credential.
        """
        if value is not None and not value.get_secret_value().strip():
            return None
        return value
