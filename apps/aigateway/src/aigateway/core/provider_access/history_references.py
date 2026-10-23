"""What the Connection rows address, for the history purge (OME-1138 Stage E, E5b).

# FEATURE: Stage E history cleanup — the purge keeps every blob a Connection row addresses; this
# module reads the rows of every account and resolves each one through its strategy.
# INVARIANT (C2): an address is the whole `(service, account)` pair `credential_blob_address`
# resolves, never one assembled from the locator text. A row that does not resolve (no loaded
# plugin, a malformed locator) is kept apart: it still names a blob by its locator text, and no
# physical account under that service can be ruled out for it (C4).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from aigateway.core.oauth.models import OAuthConnection
from aigateway.core.plugin_base import credential_service_provider_for

from .connection_locator import credential_blob_address, locator_credential_name

Address = tuple[str, str]


@dataclass(frozen=True)
class References:
    """What the Connection rows of every account address."""

    addressed: frozenset[Address]
    unresolved: tuple[OAuthConnection, ...]

    def unresolved_naming(self, account_id: str) -> bool:
        """An unresolvable row of this account, or of another whose locator names it."""
        return any(
            str(connection.account_id) == account_id
            or _account_in(_locator_service(connection)) == account_id
            for connection in self.unresolved
        )

    def unresolved_services(self) -> frozenset[str]:
        services = (_locator_service(connection) for connection in self.unresolved)
        return frozenset(service for service in services if service is not None)


async def read_references(app: Any, providers: Any) -> References:
    """Every Connection row of every account, resolved; `app` and `providers` as `PurgeContext`."""
    # WHY every account's rows: a locator may name another account's blob. Only the purged
    # account's own rows are fenced by its lock; after E5a no path creates a reference across
    # accounts.
    addressed: set[Address] = set()
    unresolved: list[OAuthConnection] = []
    for connection in await OAuthConnection.all():
        address = address_of(app, providers, connection)
        if address is None:
            unresolved.append(connection)
        else:
            addressed.add(address)
    return References(frozenset(addressed), tuple(unresolved))


def address_of(app: Any, providers: Any, connection: OAuthConnection) -> Address | None:
    plugin = providers.get(connection.provider)
    if plugin is None:
        return None
    namespace = credential_service_provider_for(plugin, connection.provider)
    # WHY no fallback: the runtime reads a malformed locator's UUID-derived name, but a locator that
    # names nothing proves nothing about the blob its owner meant (C4).
    name = locator_credential_name(connection.credential_locator, credential_provider=namespace)
    if name is None:
        return None
    return credential_blob_address(app, plugin, connection.provider, connection)


def _locator_service(connection: OAuthConnection) -> str | None:
    locator = connection.credential_locator
    if isinstance(locator, Mapping) and isinstance(locator.get("service"), str):
        return locator["service"]
    return None


def _account_in(service: str | None) -> str | None:
    """The account segment of `aigateway:<namespace>:<account>:<suffix>`."""
    parts = [] if service is None else service.split(":", 3)
    return parts[2] if len(parts) == 4 else None


__all__ = ["Address", "References", "address_of", "read_references"]
