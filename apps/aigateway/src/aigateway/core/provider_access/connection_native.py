"""The Connection-native routes over a migrated pair's effective row (OME-1208, Stage B S2'b4).

# FEATURE: Stage B Target — a migrated pair's effective Connection is addressed at its
# `credential_locator` (the Profile blob) by EVERY path, and its two authority-changing writes
# keep the pair coherent: delete retires the pair (op 9 shape), key replacement fences the
# generation and mirrors the compat document (op 8 shape).
# INVARIANT (D14): the marker and the index are written inside the CALLER's transaction BEFORE
# the connection row and the blob — marker → index → connection row → blob, the one lock order
# of the backing (`connection_admin`, `connection_oauth`).
# AIDEV-NOTE: a row that is not a migrated pair's effective row is a plain Connection — every
# function here is a no-op for it and the route behaves exactly as before S2'b4. Nothing here
# reads for a response; the routes keep their own HTTP vocabulary.
"""

from __future__ import annotations

from typing import Any

from tortoise.queryset import QuerySet

from aigateway.core.oauth.models import OAuthConnection
from aigateway.core.oauth.store import credential_locator_for
from aigateway.core.plugin_base import credential_service_provider_for
from aigateway.core.profile_index import ProfileIndexStore, ProfileTransitionConflict

from .connection_admin import api_key_mirror
from .connection_locator import credential_name_from_locator
from .pair_authority import PairAuthority, PairAuthorityConflict, PairAuthorityStore
from .types import WriteConflict


def credential_name_of(plugin: Any, connection: OAuthConnection, *, account_id: str) -> str:
    """The credential name this row's locator addresses — today's UUID name for a plain row."""
    return credential_name_from_locator(
        connection.credential_locator,
        credential_provider=credential_service_provider_for(plugin, connection.provider),
        account_id=account_id,
        connection_id=connection.id,
    )


async def effective_pair_of(connection: OAuthConnection) -> PairAuthority | None:
    """The `migrated` marker naming THIS row as the pair's effective credential, else None."""
    pair = await PairAuthorityStore().read(str(connection.account_id), connection.provider)
    if pair.migration_state != "migrated" or pair.effective_connection_id != connection.id:
        return None
    return pair


def _live_rows(connection: OAuthConnection) -> QuerySet[OAuthConnection]:
    return OAuthConnection.filter(
        account_id=str(connection.account_id), provider=connection.provider
    ).exclude(status="revoked")


async def lock_lower_addressers(connection: OAuthConnection) -> None:
    """Delete time, BEFORE `mark_revoked`: lock the pair's live rows ordered below this one.

    # WHY: two deletes of rows sharing one blob would each see the other live and BOTH keep the
    # blob — orphaned. Every deleter therefore locks the pair's live rows in ONE ascending id order:
    # the lower rows here, its own row via `mark_revoked`, the higher rows in
    # `credential_has_other_owner`. One global order cannot deadlock; the later deleter waits for
    # the earlier to commit, and PostgreSQL's re-check then drops the revoked row from its view.
    # AIDEV-NOTE: SQLite ignores FOR UPDATE — its single writer serializes the deletes anyway.
    """
    await _live_rows(connection).filter(id__lt=connection.id).order_by("id").select_for_update()


async def credential_has_other_owner(app: Any, connection: OAuthConnection) -> bool:
    """Delete time, AFTER `mark_revoked`: does another live addresser still serve this row's blob?

    True when another non-revoked row of the pair has the same locator (a superseded `error` row
    beside the row a re-auth opened), or when the legacy Profile owns the pair (marker `none` or
    `quarantined`) and one of its documents is addressed there — the shape an R1 rollback leaves.
    The caller then keeps the blob.
    # INVARIANT (D5, D11): a blob is deleted only when its LAST live addresser goes — never destroy
    # what another owner serves, never guess which one the user meant.
    # WHY a migrated pair's documents do not count: they are mirrors of the effective row, not
    # owners; `retire_effective` removes them when the effective row itself is deleted.
    """
    account_id = str(connection.account_id)
    locator = connection.credential_locator
    await _live_rows(connection).filter(id__gt=connection.id).order_by("id").select_for_update()
    rows = await _live_rows(connection).exclude(id=connection.id)
    if any(row.credential_locator == locator for row in rows):
        return True
    pair = await PairAuthorityStore().read(account_id, connection.provider)
    if pair.migration_state == "migrated":
        return False
    credential_provider = credential_service_provider_for(
        app.state.providers.get(connection.provider), connection.provider
    )
    index: ProfileIndexStore = app.state.profile_index
    return any(
        credential_locator_for(credential_provider, account_id, document.name) == locator
        for document in await index.list(account_id, provider=connection.provider)
    )


async def retire_effective(app: Any, connection: OAuthConnection) -> None:
    """Delete time: the pair keeps no effective Connection and no compat document.

    Runs inside the caller's transaction, BEFORE `mark_revoked` and the blob delete.
    # WHY remove the document: after an R1 rollback the legacy path must not find a document
    # for a credential the user deleted — "delete removes only one → old credential later
    # reappears" is the state the transition forbids. Post-delete shape = op 9's.
    """
    pair = await effective_pair_of(connection)
    if pair is None:
        return
    await _advance(pair, connection, effective_connection_id=None)
    index: ProfileIndexStore = app.state.profile_index
    for document in await index.list(pair.account_id, provider=pair.provider):
        await index.remove(document.id)


async def republish_effective_api_key(
    app: Any, connection: OAuthConnection, *, raw_api_key: str
) -> None:
    """Key replacement: fence the pair and mirror the compat document, as op 8 does.

    Runs inside the caller's transaction, BEFORE `reactivate` and the blob write.
    # INVARIANT: the generation moves (same effective id) so a Profile-facade OAuth callback
    # still in flight loses its fence instead of publishing tokens over the key just set —
    # never last-write-wins between two secrets.
    """
    pair = await effective_pair_of(connection)
    if pair is None:
        return
    await _advance(pair, connection, effective_connection_id=connection.id)
    index: ProfileIndexStore = app.state.profile_index
    for document in await index.list(pair.account_id, provider=pair.provider):
        mirror = api_key_mirror(
            document,
            account_id=pair.account_id,
            provider=pair.provider,
            name=document.name,
            raw_api_key=raw_api_key,
        )
        try:
            await index.upsert(mirror, require_present=True)
        except ProfileTransitionConflict as exc:
            raise _superseded(connection) from exc


async def _advance(
    pair: PairAuthority, connection: OAuthConnection, *, effective_connection_id: Any
) -> None:
    try:
        await PairAuthorityStore().advance(
            pair.account_id,
            pair.provider,
            expected_generation=pair.generation,
            migration_state="migrated",
            effective_connection_id=effective_connection_id,
        )
    except PairAuthorityConflict as exc:
        raise _superseded(connection) from exc


def _superseded(connection: OAuthConnection) -> WriteConflict:
    return WriteConflict(
        "superseded",
        subject="connection",
        provider=connection.provider,
        requested=str(connection.id),
    )


__all__ = [
    "credential_has_other_owner",
    "credential_name_of",
    "effective_pair_of",
    "lock_lower_addressers",
    "republish_effective_api_key",
    "retire_effective",
]
