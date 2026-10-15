"""Duck-typed credential resolution for plugins that predate the port.

WHY these are module-level functions rather than methods: they take ANY object
and tolerate one that implements only the legacy ``oauth_strategy_for`` hook, so
they cannot assume a ``ProviderPluginBase`` and must not require one.

AIDEV-NOTE: import these from the ``plugin_base`` PACKAGE, never from this module
directly — the split between files is an implementation detail.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from ._ports import CredentialStrategy

if TYPE_CHECKING:
    from ..credential_blob.store import CredentialBlobStore
    from ..profile_models import AuthType

_CREDENTIAL_SERVICE_PROVIDER_ALIASES = {"gemini-cli": "gemini"}


def credential_service_provider_for(plugin: Any, provider: str) -> str:
    getter = getattr(plugin, "credential_service_provider", None)
    if callable(getter):
        value = getter()
        if isinstance(value, str) and value:
            return value
    # INVARIANT: shipped aliases remain available when a plugin is disabled or retired, so a
    # stored locator can still be validated without treating its own untrusted value as authority.
    return _CREDENTIAL_SERVICE_PROVIDER_ALIASES.get(provider, provider)


def credential_strategy_from(
    plugin: Any,
    profile_name: str,
    *,
    auth_type: AuthType = "oauth",
    credential_store: CredentialBlobStore | None = None,
    http_client_factory: Any | None = None,
) -> CredentialStrategy | None:
    """Resolve a plugin's credential strategy, tolerating duck-typed plugins
    that only implement the legacy ``oauth_strategy_for`` hook (mirrors
    ``credential_service_provider_for``)."""
    resolver: Callable[..., CredentialStrategy | None] | None = getattr(
        plugin, "credential_strategy_for", None
    )
    if callable(resolver):
        return resolver(
            profile_name,
            auth_type=auth_type,
            credential_store=credential_store,
            http_client_factory=http_client_factory,
        )
    if auth_type == "api_key":
        api_resolver: Callable[..., CredentialStrategy | None] | None = getattr(
            plugin, "api_key_strategy_for", None
        )
        if callable(api_resolver):
            return api_resolver(profile_name, credential_store=credential_store)
        return None
    legacy: Callable[..., CredentialStrategy | None] | None = getattr(
        plugin, "oauth_strategy_for", None
    )
    if callable(legacy):
        return legacy(
            profile_name,
            credential_store=credential_store,
            http_client_factory=http_client_factory,
        )
    return None
