"""Locator-authoritative credential addressing for Connections (OME-1208, Stage B S1).

# FEATURE: "reads without re-entry" (card: Stage B Target) — a migrated Connection reads and writes
# the blob its stored `credential_locator` names, which the migration tool points at the blob the
# legacy Profile already addresses; a new Connection keeps its UUID locator and addresses exactly
# what it addresses today.
# INVARIANT: the locator decides the credential NAME a strategy is built from — and, through the
# plugin's `credential_service_for`, the blob — never the Connection id. A malformed locator falls
# back to today's UUID-derived name, which addresses a blob unique to that Connection, so no other
# pair's secret can ever be served through it.
# AIDEV-NOTE: the address format `aigateway:<credential-provider>:<credential-name>` is owned by
# each plugin's `credential_service_for` and mirrored by `core.oauth.store.credential_locator_for`;
# the core never imports a plugin, so the format is inverted here from that same literal shape.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any
from uuid import UUID

from ..oauth.models import OAuthConnection
from ..oauth.store import DEFAULT_CREDENTIAL_ACCOUNT, credential_key_for
from ..plugin_base import (
    CredentialStrategy,
    credential_service_provider_for,
    credential_strategy_from,
)
from .auth_mode import auth_type_of

_SERVICE_NAMESPACE = "aigateway"


def credential_name_from_locator(
    locator: object,
    *,
    credential_provider: str,
    account_id: str,
    connection_id: UUID | str,
) -> str:
    """The credential name the locator addresses, or today's UUID-derived name when malformed."""
    fallback = credential_key_for(account_id, connection_id)
    if not isinstance(locator, Mapping):
        return fallback
    # WHY: every strategy reads the `default` slot of its service; another slot cannot be honoured,
    # and silently reading `default` instead would serve a blob the locator did not name.
    if locator.get("account", DEFAULT_CREDENTIAL_ACCOUNT) != DEFAULT_CREDENTIAL_ACCOUNT:
        return fallback
    service = locator.get("service")
    prefix = f"{_SERVICE_NAMESPACE}:{credential_provider}:"
    if not isinstance(service, str) or not service.startswith(prefix):
        return fallback
    return service[len(prefix) :] or fallback


def credential_strategy_for_connection(
    app: Any,
    plugin: Any,
    provider: str,
    connection: OAuthConnection,
    *,
    account_id: str,
) -> CredentialStrategy | None:
    """The strategy that reads and writes the blob this Connection's locator names.

    Built fresh, like the admin write path; the read path (S2') caches it under the same
    locator-derived name, so one eviction covers the legacy Profile and the migrated Connection.
    """
    name = credential_name_from_locator(
        connection.credential_locator,
        credential_provider=credential_service_provider_for(plugin, provider),
        account_id=account_id,
        connection_id=connection.id,
    )
    return credential_strategy_from(
        plugin,
        name,
        # INVARIANT: the auth type is never caller-declared — it is the stored Connection's.
        auth_type=auth_type_of(None, connection),
        credential_store=app.state.credential_store,
        http_client_factory=getattr(app.state, f"{provider}_http_factory", None),
    )


__all__ = ["credential_name_from_locator", "credential_strategy_for_connection"]
