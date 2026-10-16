"""Provider-plugin value types and the credential port.

FEATURE: the plugin contract's nouns — what a plugin contributes
(``ModelEntry``), how it is configured (``PluginSettings``), and the auth port it
implements (``CredentialStrategy``) together with the OAuth metadata that drives
the flow.

AIDEV-NOTE: import these from the ``plugin_base`` PACKAGE, never from this module
directly — the split between files is an implementation detail.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from pydantic_settings import BaseSettings, SettingsConfigDict


class PluginSettings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore", populate_by_name=True)


@dataclass(frozen=True)
class ModelEntry:
    """Single entry contributed to LiteLLM's model_list.

    Maps directly onto the dict shape that `litellm.Router(model_list=...)`
    expects. `model_name` is the user-facing alias; `litellm_params.model`
    is the fully-qualified provider/model string.
    """

    model_name: str
    litellm_params: dict[str, Any]
    # OME-1537: per-model input-modality EVIDENCE a provider's discovery carried in
    # (e.g. a catalogue's ``architecture.input_modalities``), already mapped onto the
    # core vocabulary by the plugin. ``None`` = no evidence -> the row says text-only.
    # INVARIANT: ``compare=False`` — evidence is not identity. Two listings of the
    # same model stay equal whether or not a refresh learned its modalities.
    input_modalities: tuple[str, ...] | None = field(default=None, compare=False)


@dataclass(frozen=True)
class ModelAdmission:
    """Outcome of a dynamic model-admission attempt (OME-879).

    Think of it as the gateway's answer to "may this model join the served
    catalog right now?": either a grant carrying the ``ModelEntry`` to serve, or
    a refusal carrying a diagnostic ``code`` + ``message`` that name which knob
    to turn — all decided BEFORE any money is spent.

    INVARIANT: a grant always carries an entry; a refusal always carries a code.
    Use the two constructors, never the raw dataclass fields.
    """

    admitted: bool
    entry: ModelEntry | None = None
    code: str | None = None
    message: str | None = None

    @classmethod
    def granted(cls, entry: ModelEntry) -> ModelAdmission:
        return cls(admitted=True, entry=entry)

    @classmethod
    def refused(cls, code: str, message: str) -> ModelAdmission:
        return cls(admitted=False, code=code, message=message)


class CredentialStrategy(ABC):
    """Per-provider credential producer (the auth "port").

    Implementations own credential reads, refresh-on-401 with locking, and
    any provider-specific header construction. The auth bridge calls
    `get_authorization_header()` right before LiteLLM dispatches a request.
    Implementations may be OAuth-backed (token refresh) or API-key-backed
    (no refresh; `refresh_credentials` is a no-op).
    """

    @abstractmethod
    async def get_authorization_header(self) -> dict[str, str]:
        """Return headers to merge into the upstream request.

        Example: ``{"Authorization": "Bearer ..."}``.
        """

    async def invalidate(self) -> None:
        """Drop any cached token. Called after a 401 from upstream."""

    @abstractmethod
    async def persist_credentials(self, credentials: dict[str, Any]) -> None:
        """Persist newly exchanged provider credentials for this profile."""

    @abstractmethod
    async def delete_credentials(self) -> None:
        """Delete persisted provider credentials for this profile."""

    @abstractmethod
    async def refresh_credentials(self) -> None:
        """Refresh persisted provider credentials for this profile."""


# Back-compat alias: existing plugins/tests import the port under its original
# OAuth-specific name. New code should use CredentialStrategy.
OAuthStrategy = CredentialStrategy


@dataclass(frozen=True)
class OAuthConfig:
    """Provider-level OAuth metadata used to drive the start + callback flow."""

    authorize_url: str
    token_url: str
    client_id: str
    scopes: list[str]
    redirect_path: str  # absolute path on the gateway callback surface
    extra_authorize_params: dict[str, str] | None = None
    loopback_redirect_ports: list[int] | None = None


@dataclass(frozen=True)
class OAuthCodeExchangeRequest:
    """Provider-owned authorization-code exchange input."""

    code: str
    code_verifier: str
    redirect_uri: str
    state: str
    http_client_factory: Any | None = None
