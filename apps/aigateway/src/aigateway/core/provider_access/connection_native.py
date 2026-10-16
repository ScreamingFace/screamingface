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
# FEATURE (OME-1497, G0 writer floor §5.3): on a `none`/`quarantined` pair a native create, OAuth
# start, key replacement or delete is an ownership change — `claim_native_write` claims the pair
# it observed, keeping the state (no auto-promotion, D14), as the FIRST write of its transaction.
# FEATURE (OME-1209, E1b, spec R6): a native OAuth flow started while a `migrated` pair's
# effective row was unusable takes the pair over at its callback — `replace_effective` moves the
# marker to the new row, `retire_replaced` revokes the old one. Connection side only, so the
# repair outlives the Profile routes and the Profile index.
"""

from __future__ import annotations

from collections.abc import Collection
from typing import Any

from tortoise.expressions import Q
from tortoise.queryset import QuerySet

from aigateway.core.oauth.models import OAuthConnection
from aigateway.core.oauth.store import OAuthConnectionStore, credential_locator_for
from aigateway.core.plugin_base import credential_service_provider_for
from aigateway.core.profile_index import ProfileIndexStore, ProfileTransitionConflict

from .connection_admin import api_key_mirror
from .connection_locator import credential_name_from_locator
from .pair_authority import PairAuthority, PairAuthorityConflict, PairAuthorityStore
from .types import WriteConflict
from .writer_floor import claim_observed


def credential_name_of(plugin: Any, connection: OAuthConnection, *, account_id: str) -> str:
    """The credential name this row's locator addresses — today's UUID name for a plain row."""
    return credential_name_from_locator(
        connection.credential_locator,
        credential_provider=credential_service_provider_for(plugin, connection.provider),
        account_id=account_id,
        connection_id=connection.id,
    )


async def claim_native_write(observed: PairAuthority, *, requested: str) -> PairAuthority | None:
    """Claim the legacy-owned pair a native writer observed; the published pair, else None.

    Runs inside the caller's transaction as its FIRST write (marker → row → blob). A `migrated`
    pair is a no-op: its effective row is fenced by `retire_effective` and
    `republish_effective_api_key`, and its other rows keep their fences (owner decision
    2026-10-06). A lost claim is the native superseded conflict (409 `connection_conflict`).
    """
    try:
        return await claim_observed(observed)
    except PairAuthorityConflict as exc:
        raise WriteConflict(
            "superseded", subject="connection", provider=observed.provider, requested=requested
        ) from exc


async def claim_for_connection(connection: OAuthConnection) -> None:
    """Key replacement and delete: capture this row's pair now — after any key validation — and
    claim it (§5.3: replacement captures after validation; delete has no network I/O)."""
    observed = await PairAuthorityStore().read(str(connection.account_id), connection.provider)
    await claim_native_write(observed, requested=str(connection.id))


async def effective_pair_of(connection: OAuthConnection) -> PairAuthority | None:
    """The `migrated` marker naming THIS row as the pair's effective credential, else None."""
    pair = await PairAuthorityStore().read(str(connection.account_id), connection.provider)
    if pair.migration_state != "migrated" or pair.effective_connection_id != connection.id:
        return None
    return pair


# WHY these two: a row in `error` or `revoked` serves nothing — a new OAuth flow replaces it
# whatever its auth type, as the Profile facade did.
UNUSABLE_EFFECTIVE = frozenset({"error", "revoked"})


# WHY: `mark_error`, `mark_revoked` and a pending start park a row under these — never a name.
_PLACEHOLDER_LABEL_PREFIXES = ("error:", "revoked:", "pending-")


async def effective_to_replace(
    observed: PairAuthority, *, requested_label: str | None
) -> PairAuthority | None:
    """Start time: the observed `migrated` pair when this native write replaces its effective row.

    It does when that row is unusable, when the write names no label ("no label = the pair's main
    connection", as the Profile API's default name), or when it asks for the row's own label (the
    native write's only address — "re-authorise THAT one"). Otherwise a working effective row
    stays and the write adds a plain row beside it.
    """
    effective = await _effective_row(observed)
    if effective is None:
        return None
    if (
        effective.status in UNUSABLE_EFFECTIVE
        or requested_label is None
        or effective.label == requested_label
    ):
        return observed
    return None


async def replaced_label(observed: PairAuthority | None) -> str | None:
    """The replaced effective row's label when it is a real name — the one an unlabelled write
    keeps, and the one a write naming it may take."""
    effective = None if observed is None else await _effective_row(observed)
    if effective is None or effective.label.startswith(_PLACEHOLDER_LABEL_PREFIXES):
        return None
    return effective.label


async def _effective_row(observed: PairAuthority) -> OAuthConnection | None:
    if observed.migration_state != "migrated" or observed.effective_connection_id is None:
        return None
    return await OAuthConnection.filter(
        id=observed.effective_connection_id, account_id=observed.account_id
    ).first()


async def replace_effective(observed: PairAuthority, *, connection_id: Any) -> None:
    """Callback time, the FIRST write of its transaction (D14): `connection_id` becomes effective.

    # INVARIANT: compare-and-set from the generation observed at start — a newer start, a delete
    # or a key write in between raises `PairAuthorityConflict` and the caller rolls back, so the
    # pair never names two effective rows and never loses the one a newer writer published.
    """
    await PairAuthorityStore().advance(
        observed.account_id,
        observed.provider,
        expected_generation=observed.generation,
        migration_state="migrated",
        effective_connection_id=connection_id,
    )


async def retire_replaced(
    observed: PairAuthority, *, alongside: Collection[Any] = (), identity_sub: str | None = None
) -> list[OAuthConnection]:
    """Callback time, after `replace_effective` and BEFORE the new row activates: revoke the
    row it replaced and, for a sign-in with `identity_sub`, every other row of the pair holding
    that provider identity. Returns them (their cached strategies are the caller's to evict).

    # INVARIANT: these rows and every row in `alongside` lock in ONE ascending id order — the
    # order delete uses (`lock_lower_addressers`) — so a concurrent delete cannot deadlock it.
    # WHY before activation: `identity_sub` and `label` are unique per pair whatever the status;
    # revocation frees both, so the new row can take them.
    # WHY revoke a same-identity row rather than reuse it: a refresh that started on its old
    # tokens may still fail and mark it `error` after this commits; a revoked row ignores that,
    # and the fresh tokens live only on the new row nobody else has seen.
    """
    scope = Q(id__in=[observed.effective_connection_id, *alongside])
    if identity_sub is not None:
        scope |= Q(provider=observed.provider, identity_sub=identity_sub)
    locked = (
        await OAuthConnection.filter(scope, account_id=observed.account_id)
        .order_by("id")
        .select_for_update()
    )
    keep = {str(row_id) for row_id in alongside}
    store = OAuthConnectionStore()
    retired = []
    for row in locked:
        if str(row.id) in keep:
            continue
        if row.status != "revoked":
            row = await store.mark_revoked(row, "replaced")
        retired.append(row)
    return retired


async def take_over_effective(
    observed: PairAuthority, connection: OAuthConnection
) -> list[OAuthConnection]:
    """API-key create, inside its transaction after the fresh row exists (the marker's FK needs
    it; nobody can contend a row whose UUID no one has seen): `connection` becomes effective and
    the row it replaces is revoked. Returns the retired rows.

    A lost compare-and-set is the native superseded conflict (409 `connection_conflict`).
    """
    try:
        await replace_effective(observed, connection_id=connection.id)
    except PairAuthorityConflict as exc:
        raise _superseded(connection) from exc
    return await retire_replaced(observed, alongside=(connection.id,))


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
    "claim_for_connection",
    "claim_native_write",
    "credential_has_other_owner",
    "credential_name_of",
    "effective_pair_of",
    "effective_to_replace",
    "lock_lower_addressers",
    "replace_effective",
    "replaced_label",
    "republish_effective_api_key",
    "retire_effective",
    "retire_replaced",
    "take_over_effective",
]
