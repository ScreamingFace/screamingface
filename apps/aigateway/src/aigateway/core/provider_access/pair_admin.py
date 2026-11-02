"""The ordered pair disposition behind the D18 successor (OME-1497, G1; contract §4, §5).

# FEATURE: OME-1138 D18 — an admin addresses the ONE effective credential of an
# `(account, provider)` pair. `classify_pair` reads a pair's marker and live Connections top to
# bottom through the §5 table; `pair_inventory` projects every pair of an account into a neutral
# credential, a per-provider conflict, or nothing.
# INVARIANT (OME-1209 E4a, spec §9 Q8): no legacy Profile document takes part — rows 8 and 10,
# the document half of row 3 and the row-11 identity proof are gone, so a Profile-only pair is
# the empty pair (row 7) and a Profile beside one Connection is that Connection's row (9).
# INVARIANT: read-only — no write, no marker advance, no refresh, and no provider credential is
# read or decrypted. The first matching row decides.
# INVARIANT: unknown or inconsistent stored state raises `CredentialAuthorityUnavailable`; it is
# never rendered as a credential or as its absence. Only expected storage failures become
# `CredentialStoreReadUnavailable`; a programming error propagates.
# NOTE: the G1 mutations (PUT/DELETE through the bridge) reuse `classify_pair`; its `row` is the
# §5 row number, so a mutation dispatches on the same table.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

from pydantic import ValidationError

from ..auth_types import AuthType
from ..oauth.models import OAuthConnection
from ..oauth.store import DEFAULT_CREDENTIAL_ACCOUNT, OAuthConnectionStore
from ..plugin_base import credential_service_provider_for
from ..secrets.mixin import SecretDecryptionError
from ..storage_outages import STORAGE_OUTAGES
from .pair_authority import PairAuthority, PairAuthorityDataError, PairAuthorityStore
from .types import CredentialAuthorityUnavailable, CredentialStoreReadUnavailable

CredentialState = Literal["active", "pending", "error"]
PairConflictKind = Literal["ambiguous", "unresolved"]

# WHY maps, not sets: a stored column is a plain string; the lookup both checks and types it.
_STATE_FOR_STATUS: dict[str, CredentialState] = {
    "active": "active",
    "pending": "pending",
    "error": "error",
}
_AUTH_TYPES: dict[str, AuthType] = {"api_key": "api_key", "oauth": "oauth"}
# WHY these and no others: an unreachable database, a failed query or an undecodable or invalid
# metadata index is an outage of the store; anything else is a bug and must not read as "empty".
_STORE_READ_FAILURES = (*STORAGE_OUTAGES, SecretDecryptionError, ValidationError)
_INVENTORY_READ_ATTEMPTS = 2


@dataclass(frozen=True)
class PairCredential:
    """The neutral view of a pair's one credential — no name, id, locator or secret."""

    provider: str
    auth_type: AuthType
    credential_state: CredentialState
    last_refreshed_at: datetime | None


@dataclass(frozen=True)
class PairConflict:
    """A pair that cannot be addressed (`ambiguous`, row 3) or managed safely (`unresolved`)."""

    provider: str
    kind: PairConflictKind


@dataclass(frozen=True)
class PairInventory:
    """Every pair of an account, each in exactly one array, both sorted by provider."""

    credentials: tuple[PairCredential, ...]
    conflicts: tuple[PairConflict, ...]


@dataclass(frozen=True)
class PairDisposition:
    """The §5 row a pair matched, with the owner that row names (if any)."""

    row: int
    marker: PairAuthority
    connection: OAuthConnection | None = None


# --- the table ----------------------------------------------------------------------------------


def classify_pair(
    marker: PairAuthority,
    connections: Sequence[OAuthConnection],
    *,
    credential_provider: str | None,
) -> PairDisposition:
    """The first matching §5 row for one pair (rows 2, 3, 5-7, 9, 11; row 1 is the caller's read).

    # WHY no row 4 (OME-1138 close-out, L4a): it served a marker state no writer produces since
    # E5c, and the store now refuses that state on read, before any row is matched.

    `connections` are the pair's non-revoked rows; `credential_provider` is None for a provider
    no plugin serves, which LIST renders as an explicit unresolved result.
    """
    provider = marker.provider
    if marker.effective_connection_id is not None and marker.migration_state != "migrated":
        raise CredentialAuthorityUnavailable(provider)
    locator_provider = credential_provider or credential_service_provider_for(None, provider)
    for connection in connections:
        _require_known(connection, provider, locator_provider, marker.account_id)
    if len(connections) > 1:
        return PairDisposition(3, marker)
    connection = connections[0] if connections else None
    if marker.migration_state == "migrated":
        migrated = _migrated(marker, connection)
        if credential_provider is None and migrated.row != 6:
            return PairDisposition(11, marker, connection=connection)
        return migrated
    if connection is None:
        return PairDisposition(7, marker)
    if credential_provider is None:
        # WHY after rows 2-3 and migrated validation: an unknown plugin cannot make an
        # inconsistency disappear. Only a structurally valid candidate becomes unresolved.
        return PairDisposition(11, marker, connection=connection)
    return PairDisposition(9, marker, connection=connection)


def _migrated(marker: PairAuthority, connection: OAuthConnection | None) -> PairDisposition:
    if marker.effective_connection_id is None:
        if connection is None:
            # Row 6: a disconnected pair.
            return PairDisposition(6, marker)
        # WHY unresolved: a live row beside a null reference is no row of the table — no
        # effective owner to show and no safe one to pick (row 11, "any other combination").
        return PairDisposition(11, marker, connection=connection)
    if connection is None or connection.id != marker.effective_connection_id:
        # INVARIANT: a referenced row that is missing or revoked is an inconsistency, not a
        # normal post-delete state — a normal delete clears the reference.
        raise CredentialAuthorityUnavailable(marker.provider)
    return PairDisposition(5, marker, connection=connection)


def _require_known(
    connection: OAuthConnection, provider: str, credential_provider: str, account_id: str
) -> None:
    if connection.status not in _STATE_FOR_STATUS or connection.auth_type not in _AUTH_TYPES:
        raise CredentialAuthorityUnavailable(provider)
    if not _in_scope(connection.credential_locator, credential_provider, account_id):
        raise CredentialAuthorityUnavailable(provider)


def _in_scope(locator: object, credential_provider: str, account_id: str) -> bool:
    """Whether a locator names a slot in this account/provider credential namespace.

    # INVARIANT (§5): a malformed or out-of-scope locator is never re-addressed by a fallback —
    # unlike the read path's UUID fallback, which would point the successor at another blob.
    """
    if not isinstance(locator, Mapping):
        return False
    if locator.get("account") != DEFAULT_CREDENTIAL_ACCOUNT:
        return False
    service = locator.get("service")
    prefix = f"aigateway:{credential_provider}:{account_id}:"
    return isinstance(service, str) and service.startswith(prefix) and len(service) > len(prefix)


# --- the LIST projection ------------------------------------------------------------------------


def listing(disposition: PairDisposition) -> PairCredential | PairConflict | None:
    """What LIST shows for one pair: its neutral credential, its conflict, or nothing."""
    provider = disposition.marker.provider
    if disposition.row == 3:
        return PairConflict(provider, "ambiguous")
    if disposition.row == 11:
        return PairConflict(provider, "unresolved")
    if disposition.row in (5, 9) and disposition.connection is not None:
        return connection_credential(disposition.connection)
    return None


def connection_credential(connection: OAuthConnection) -> PairCredential:
    """The neutral view of a Connection that `_require_known` (or a write) has vetted."""
    return PairCredential(
        connection.provider,
        _AUTH_TYPES[connection.auth_type],
        _STATE_FOR_STATUS[connection.status],
        connection.last_refreshed_at,
    )


@contextmanager
def store_reads() -> Iterator[None]:
    """Expected storage failures inside the block become the whole-request store refusal (row 1).

    # WHY public: the route's own account lookup is the request's first database read; an outage
    # there must be the same 503 as one in the inventory, never a bare 500.
    """
    try:
        yield
    except _STORE_READ_FAILURES as exc:
        raise CredentialStoreReadUnavailable() from exc


async def pair_inventory(app: Any, account_id: str) -> PairInventory:
    """Every pair of the account through the §5 table — the successor LIST (§4)."""
    markers = PairAuthorityStore()
    for _attempt in range(_INVENTORY_READ_ATTEMPTS):
        with store_reads():
            before = await _read_generations(markers, account_id)
            connections = await OAuthConnectionStore().list(account_id)
            providers = sorted(
                {c.provider for c in connections} | {provider for provider, _generation in before}
            )
            authorities = {
                provider: await read_marker(markers, account_id, provider) for provider in providers
            }
            after = await _read_generations(markers, account_id)
        if _stable_inventory_snapshot(before, after, authorities):
            return _project_inventory(app, connections, authorities)
    raise CredentialStoreReadUnavailable()


def _stable_inventory_snapshot(
    before: tuple[tuple[str, int], ...],
    after: tuple[tuple[str, int], ...],
    authorities: Mapping[str, PairAuthority],
) -> bool:
    if before != after:
        return False
    generations = dict(after)
    return all(
        marker.generation == generations.get(provider, 0)
        for provider, marker in authorities.items()
    )


def _project_inventory(
    app: Any,
    connections: Sequence[OAuthConnection],
    authorities: Mapping[str, PairAuthority],
) -> PairInventory:
    credentials: list[PairCredential] = []
    conflicts: list[PairConflict] = []
    for provider, marker in authorities.items():
        plugin = app.state.providers.get(provider)
        disposition = classify_pair(
            marker,
            [c for c in connections if c.provider == provider],
            credential_provider=(
                None if plugin is None else credential_service_provider_for(plugin, provider)
            ),
        )
        result = listing(disposition)
        if isinstance(result, PairCredential):
            credentials.append(result)
        elif isinstance(result, PairConflict):
            conflicts.append(result)
    return PairInventory(tuple(credentials), tuple(conflicts))


async def read_marker(markers: PairAuthorityStore, account_id: str, provider: str) -> PairAuthority:
    try:
        return await markers.read(account_id, provider)
    except ValueError as exc:
        # WHY ValueError: `PairAuthorityStore` refuses an unknown stored state with it.
        raise CredentialAuthorityUnavailable(provider) from exc
    except _STORE_READ_FAILURES as exc:
        raise CredentialStoreReadUnavailable() from exc


async def _read_generations(
    markers: PairAuthorityStore, account_id: str
) -> tuple[tuple[str, int], ...]:
    try:
        return await markers.generations(account_id)
    except PairAuthorityDataError as exc:
        raise CredentialAuthorityUnavailable(exc.provider) from exc
    except _STORE_READ_FAILURES as exc:
        raise CredentialStoreReadUnavailable() from exc


__all__ = [
    "CredentialState",
    "PairConflict",
    "PairConflictKind",
    "PairCredential",
    "PairDisposition",
    "PairInventory",
    "classify_pair",
    "connection_credential",
    "listing",
    "pair_inventory",
    "read_marker",
    "store_reads",
]
