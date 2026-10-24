"""The D18 successor PUT and DELETE through the mutation bridge (OME-1497, G1; §5.1-§5.3).

# FEATURE: OME-1138 D18 — an admin replaces or disconnects the ONE credential of an
# `(account, provider)` pair. An empty or single-Connection `none` pair (rows 7, 9) is adopted at
# mutation time: PUT publishes `migrated` with an active API-key Connection, DELETE ends the pair
# `migrated` with a null reference. No other pair is touched and no dummy Connection is created.
# STORY: as an operator, I attach a key to a tenant's provider, or disconnect it, without knowing
# whether the tenant's credential is still a legacy Profile or already a Connection.
# INVARIANT (§5.3): the pair is captured AFTER the key validation and every write is fenced on the
# captured generation — marker → row → blob in one transaction. A stale mutation is never
# retried on a freshly read generation; it surfaces as `WriteConflict("superseded")`.
# INVARIANT: a refused mutation (rows 3, 4, 11; an inconsistency; a lost fence) writes nothing.
# WHY no Profile document (OME-1209 E4b): neither mutation writes, removes or reads one; a document
# left behind, and a blob at its address, stay until the E5 purge. A PUT never adopts such a blob:
# its new row takes its own address (E5a).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from tortoise.transactions import in_transaction

from ..credential_strategy_cache import credential_strategy_cache
from ..oauth.models import OAuthConnection
from ..oauth.store import OAuthConnectionStore, ensure_anonymous_account
from ..plugin_base import credential_service_provider_for
from ..storage_outages import STORAGE_OUTAGES
from .connection_admin import ConnectionBackedCredentialAdmin, live_connection_ids
from .connection_native import credential_has_other_owner, credential_name_of, lock_lower_addressers
from .pair_admin import (
    PairConflictKind,
    PairCredential,
    PairDisposition,
    classify_pair,
    connection_credential,
    read_marker,
    store_reads,
)
from .pair_authority import UNMARKED_GENERATION, PairAuthorityConflict, PairAuthorityStore
from .profile_authorize import invalidate_session
from .types import CredentialStoreUnavailable, PairNotManageable, ProviderUnknown, WriteConflict

# WHY row 11 is refused outright (OME-1209 E4a): the legacy shadow identity proof compared a
# Profile document's credential, and no document takes part in the table any more.
_REFUSED_ROWS: dict[int, PairConflictKind] = {3: "ambiguous", 4: "unresolved", 11: "unresolved"}
# Rows a DELETE has nothing to remove from: a disconnected (6) or empty (7) pair.
_NOTHING_TO_DELETE = (6, 7)


@dataclass(frozen=True)
class PairMutation:
    """What a committed mutation changed — for the response and the post-commit cleanup.

    `connection_ids` is the pair's captured Connection: the pending OAuth flows to drop are exactly
    the ones naming it (§5.2). A row a PUT mints is new, so no flow can name it.
    """

    credential: PairCredential | None
    connection_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class _Capture:
    plugin: Any
    disposition: PairDisposition
    live: frozenset[UUID]


async def set_pair_api_key(
    app: Any,
    account_id: str,
    provider: str,
    raw_api_key: str,
    *,
    validate: Callable[[], Awaitable[None]],
) -> PairMutation:
    """PUT: the pair's one credential becomes this API key on an active Connection."""
    # WHY capture twice: the first refuses a conflicting pair before any provider I/O; the second,
    # AFTER the key check, is the capture the write is fenced on (§5.3).
    await _capture(app, account_id, provider)
    await validate()
    capture = await _capture(app, account_id, provider)
    disposition = capture.disposition
    marker = disposition.marker
    admin = ConnectionBackedCredentialAdmin(app)
    if marker.generation == UNMARKED_GENERATION:
        # WHY: the first marker's foreign key names the account (`writer_floor.claim_pair`).
        with _store_writes("update"):
            await ensure_anonymous_account(account_id)
    with _store_writes("update"):
        connection = await admin.publish_api_key(
            account_id,
            provider,
            capture.plugin,
            pair=marker,
            reuse=disposition.connection,
            raw_api_key=raw_api_key,
            expected_live=capture.live,
        )
    return PairMutation(connection_credential(connection), _ids(disposition))


async def delete_pair(app: Any, account_id: str, provider: str) -> PairMutation:
    """DELETE: the pair ends `migrated` with no effective Connection and without its blob."""
    capture = await _capture(app, account_id, provider)
    disposition = capture.disposition
    if disposition.row in _NOTHING_TO_DELETE:
        # WHY no write: repeating a delete is a success, and an empty pair gets no marker (row 7).
        return PairMutation(None)
    evicted: list[str] = []
    try:
        with _store_writes("delete"):
            await _delete_in_transaction(app, capture, evicted)
    except PairAuthorityConflict as exc:
        raise _superseded(provider) from exc
    for credential_name in evicted:
        invalidate_session(capture.plugin, credential_name)
        credential_strategy_cache(app).evict(credential_name)
    return PairMutation(None, _ids(disposition))


async def _delete_in_transaction(app: Any, capture: _Capture, evicted: list[str]) -> None:
    """The DELETE's one transaction: marker → row → blob (§5.3 lock order)."""
    disposition = capture.disposition
    marker = disposition.marker
    account_id, provider = marker.account_id, marker.provider
    connection = disposition.connection
    async with in_transaction():
        if marker.generation == UNMARKED_GENERATION:
            await ensure_anonymous_account(account_id)
        await PairAuthorityStore().advance(
            account_id,
            provider,
            expected_generation=marker.generation,
            migration_state="migrated",
            effective_connection_id=None,
        )
        if await live_connection_ids(account_id, provider) != capture.live:
            raise _superseded(provider)
        if connection is not None:
            evicted.append(await _retire_connection(app, capture.plugin, connection, account_id))


@contextmanager
def _store_writes(operation: str) -> Iterator[None]:
    """An expected storage failure inside a mutation is the scoped write refusal (§7, 503).

    # WHY safe to retry: the transaction rolled back whole, and PUT and DELETE are idempotent.
    # The adapter's text is chained, never repeated — it may echo stored values.
    """
    try:
        yield
    except STORAGE_OUTAGES as exc:
        raise CredentialStoreUnavailable("credentials", operation=operation) from exc


async def _capture(app: Any, account_id: str, provider: str) -> _Capture:
    """Read the pair — marker FIRST, then its Connections — and refuse rows 3, 4 and 11.

    # WHY marker first: a writer that moves the pair after this read advances the generation the
    # write is fenced on; candidates read before the marker could pair stale rows with a new owner.
    """
    plugin = app.state.providers.get(provider)
    if plugin is None:
        raise ProviderUnknown(provider)
    markers = PairAuthorityStore()
    marker = await read_marker(markers, account_id, provider)
    with store_reads():
        connections = await OAuthConnectionStore().list(account_id, provider=provider)
    disposition = classify_pair(
        marker,
        connections,
        credential_provider=credential_service_provider_for(plugin, provider),
    )
    kind = _REFUSED_ROWS.get(disposition.row)
    if kind is not None:
        raise PairNotManageable(provider, kind)
    return _Capture(plugin, disposition, frozenset(c.id for c in connections))


async def _retire_connection(
    app: Any, plugin: Any, connection: OAuthConnection, account_id: str
) -> str:
    """Revoke the pair's Connection and drop its blob unless another live owner serves it."""
    await lock_lower_addressers(connection)
    await OAuthConnectionStore().mark_revoked(connection)
    if not await credential_has_other_owner(connection):
        locator = connection.credential_locator
        await app.state.credential_store.delete(locator["service"], locator["account"])
    return credential_name_of(plugin, connection, account_id=account_id)


def _ids(disposition: PairDisposition) -> tuple[str, ...]:
    connection = disposition.connection
    return () if connection is None else (str(connection.id),)


def _superseded(provider: str) -> WriteConflict:
    return WriteConflict("superseded", subject="connection", provider=provider)


__all__ = ["PairMutation", "delete_pair", "set_pair_api_key"]
