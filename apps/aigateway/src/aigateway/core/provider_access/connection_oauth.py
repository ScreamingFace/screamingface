"""The Profile-facade OAuth flow of a MIGRATED pair, published on its effective Connection.

(OME-1208, Stage B S2'b2)

# FEATURE: Stage B Target — "OAuth callback publication included" (D14): for a pair whose marker
# reads `migrated`, `POST /v1/auth/{provider}/profiles` and its callback publish the pair's ONE
# effective Connection and the blob its `credential_locator` names. No shadow Connection, no
# UUID-addressed blob; the legacy index is only MIRRORED (D-S2b-2), never read as authority.
# INVARIANT: the fence is the pair marker's generation. `begin` advances it in the transaction
# that publishes the flow's row, the pending entry carries the new generation, and `complete`
# and `fail` compare-and-set from it — so a newer start, a delete or an API-key write in between
# rejects the stale callback at commit time (card: "fenced at commit time, not by an in-memory
# lock"). The Connection row keeps its own status fence (`complete_pending`/`complete_active`)
# as defence in depth against writers that do not consult the marker yet.
# INVARIANT: an `error` or `revoked` row is never revived — a fresh flow opens a NEW pending row
# labelled with the requested name, addressing that name's Profile blob; an `active` row
# re-authenticates IN PLACE and stays usable until the callback swaps its blob (D-S2b2-3).
# AIDEV-NOTE: `none`/`quarantined` pairs never reach these bodies — `begin_connection_oauth`
# answers `None` after ONE marker read and the route runs today's legacy body unchanged.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, cast
from uuid import uuid4

from tortoise.exceptions import IntegrityError
from tortoise.transactions import in_transaction

from ..oauth.models import OAuthConnection
from ..oauth.store import OAuthConnectionStore, credential_locator_for
from ..pending_auth import PendingAuthEntry
from ..plugin_base import credential_service_provider_for, credential_strategy_from
from ..profile_index import ProfileIndexStore, ProfileTransitionConflict
from ..profile_models import Profile, ProfileDefaults, ProfileState, profile_id_for
from . import profile_admin
from .auth_mode import auth_type_of
from .connection_authority import LEGACY_STATE_FOR_STATUS
from .connection_locator import credential_name_from_locator
from .pair_authority import PairAuthority, PairAuthorityConflict, PairAuthorityStore
from .types import UnsupportedAuthMode, WriteConflict, WriteSubject

# WHY: only a row that is still on its way to, or already at, `active` is re-published by a
# flow; `error` and `revoked` rows are placeholders a fresh flow leaves behind.
_REUSABLE = frozenset({"active", "pending"})


@dataclass(frozen=True, slots=True)
class MigratedFlow:
    """What a started flow claimed: the row it will publish and the marker generation."""

    connection_id: str
    generation: int


async def begin_connection_oauth(
    app: Any,
    plugin: Any,
    *,
    account_id: str,
    provider: str,
    name: str,
    scopes: Sequence[str],
    defaults: ProfileDefaults | None,
) -> MigratedFlow | None:
    """Open the flow on a MIGRATED pair, or answer `None` when the legacy Profile owns the pair.

    One transaction: [fresh pending row] → marker advance (the fence) → mirror document. The
    generation returned is what the callback presents to `complete_connection_oauth`.
    """
    markers = PairAuthorityStore()
    pair = await markers.read(account_id, provider)
    if pair.migration_state != "migrated":
        return None
    store = OAuthConnectionStore()
    current = await _effective(store, account_id, pair)
    reuse = current if current is not None and current.status in _REUSABLE else None
    index: ProfileIndexStore = app.state.profile_index
    document = await index.get(account_id, provider, name)
    mirror = _document(document, account_id=account_id, provider=provider, name=name)
    mirror.scopes = list(scopes)
    if defaults is not None:
        mirror.defaults = defaults
    if reuse is None:
        mirror.state = ProfileState.PENDING
    else:
        # INVARIANT (D-S2b-2): the mirror follows the authority — an in-place re-auth of an
        # active row leaves the pair usable, so its document keeps saying so.
        mirror.state = ProfileState(LEGACY_STATE_FOR_STATUS[reuse.status])
        mirror.auth_type = auth_type_of(None, reuse)
    credential_provider = credential_service_provider_for(plugin, provider)
    try:
        async with in_transaction():
            connection = reuse
            if connection is None:
                # WHY before the marker: the marker's FK needs the row, and nobody else can
                # contend a row whose fresh UUID no one has seen.
                connection = await store.create_pending(
                    account_id=account_id,
                    provider=provider,
                    label=name,
                    connection_id=uuid4(),
                    credential_provider=credential_provider,
                    credential_locator=credential_locator_for(
                        credential_provider, account_id, name
                    ),
                )
            claimed = await markers.advance(
                account_id,
                provider,
                expected_generation=pair.generation,
                migration_state="migrated",
                effective_connection_id=connection.id,
            )
            await _write_mirror(index, mirror, observed=document is not None)
    except PairAuthorityConflict as exc:
        raise _superseded(provider, name, "connection") from exc
    except ProfileTransitionConflict as exc:
        raise _superseded(provider, name, "profile") from exc
    except IntegrityError as exc:
        # WHY: another row of this account and provider already carries the requested label.
        raise _superseded(provider, name, "connection") from exc
    return MigratedFlow(str(connection.id), claimed.generation)


async def complete_connection_oauth(
    app: Any, plugin: Any, pending: PendingAuthEntry, creds: dict[str, Any]
) -> str:
    """Publish exchanged OAuth credentials on the pair's effective Connection.

    Returns the credential name the blob was written under (the locator's), for eviction.
    Raises `WriteConflict("superseded")` when this flow no longer owns the pair.
    """
    generation = pending.pair_generation
    if generation is None:
        raise ValueError("not a migrated pair's flow")
    account_id, provider, name = pending.account_id, pending.provider, pending.profile_name
    markers = PairAuthorityStore()
    store = OAuthConnectionStore()
    pair = await markers.read(account_id, provider)
    connection = None
    if pair.generation == generation:
        connection = await _effective(store, account_id, pair)
    if connection is None or connection.status not in _REUSABLE:
        raise _superseded(provider, name, "connection")
    credential_provider = credential_service_provider_for(plugin, provider)
    credential_name = credential_name_from_locator(
        connection.credential_locator,
        credential_provider=credential_provider,
        account_id=account_id,
        connection_id=connection.id,
    )
    strategy = credential_strategy_from(
        plugin,
        credential_name,
        auth_type="oauth",
        credential_store=app.state.credential_store,
        http_client_factory=getattr(app.state, f"{provider}_http_factory", None),
    )
    if strategy is None:
        raise UnsupportedAuthMode("oauth", provider=provider)
    identity = await _identity(app, plugin, provider, creds)
    index: ProfileIndexStore = app.state.profile_index
    document = await index.get(account_id, provider, name)
    mirror = _document(document, account_id=account_id, provider=provider, name=name)
    mirror.state = ProfileState.AUTHENTICATED
    mirror.auth_type = "oauth"
    mirror.last_refreshed_at = datetime.now(UTC)
    label = plugin.account_label_from_credentials(creds)
    if label is not None:
        mirror.account_label = label
    publish = store.complete_pending if connection.status == "pending" else store.complete_active
    try:
        # INVARIANT (card lock order): marker → index mirror → Connection row → blob, in ONE
        # transaction; the token exchange stayed outside it.
        async with in_transaction():
            await markers.advance(
                account_id,
                provider,
                expected_generation=generation,
                migration_state="migrated",
                effective_connection_id=connection.id,
            )
            await _write_mirror(index, mirror, observed=document is not None)
            published = await publish(connection, label=connection.label, identity=identity)
            if published is None:
                raise _superseded(provider, name, "connection")
            if published.auth_type != "oauth":
                # WHY: a completed OAuth round-trip overwrites the slot, so the discriminator
                # flips back even when the row held an API key — as the legacy document's does.
                await store.set_auth_type(published, "oauth")
            await profile_admin.persist_credentials_or_refuse(
                strategy, creds, description="OAuth profile credentials"
            )
    except PairAuthorityConflict as exc:
        raise _superseded(provider, name, "connection") from exc
    except ProfileTransitionConflict as exc:
        raise _superseded(provider, name, "profile") from exc
    except IntegrityError as exc:
        # WHY: the identity this credential carries already belongs to another row.
        raise _superseded(provider, name, "connection") from exc
    return credential_name


async def fail_connection_oauth(app: Any, pending: PendingAuthEntry, message: str) -> None:
    """Record a failed exchange on the flow's PENDING row — only while the flow owns the pair.

    INVARIANT (OME-307 Blocker 2, re-expressed): a stale failure corrupts nothing — a newer
    owner, a delete or an API-key write already moved the marker past this flow. An in-place
    re-auth of an ACTIVE row that fails marks nothing: the working credential stays.
    """
    generation = pending.pair_generation
    if generation is None:
        return
    account_id, provider, name = pending.account_id, pending.provider, pending.profile_name
    markers = PairAuthorityStore()
    store = OAuthConnectionStore()
    pair = await markers.read(account_id, provider)
    if pair.generation != generation:
        return
    connection = await _effective(store, account_id, pair)
    if connection is None or connection.status != "pending":
        return
    index: ProfileIndexStore = app.state.profile_index
    document = await index.get(account_id, provider, name)
    try:
        async with in_transaction():
            await markers.advance(
                account_id,
                provider,
                expected_generation=generation,
                migration_state="migrated",
                effective_connection_id=connection.id,
            )
            if await store.mark_pending_error(connection, message) is None:
                raise _superseded(provider, name, "connection")
            if document is not None:
                document.state = ProfileState.ERROR
                await index.upsert(document, require_present=True)
    except (PairAuthorityConflict, ProfileTransitionConflict, WriteConflict):
        return


async def _effective(
    store: OAuthConnectionStore, account_id: str, pair: PairAuthority
) -> OAuthConnection | None:
    if pair.effective_connection_id is None:
        return None
    return await store.get(account_id, pair.effective_connection_id)


def _document(document: Profile | None, *, account_id: str, provider: str, name: str) -> Profile:
    if document is not None:
        return document
    return Profile(
        id=profile_id_for(account_id, provider, name),
        account_id=account_id,
        provider=provider,
        name=name,
    )


async def _write_mirror(index: ProfileIndexStore, mirror: Profile, *, observed: bool) -> None:
    # WHY `require_present` when observed: a concurrent delete wins and nothing is resurrected.
    if observed:
        await index.upsert(mirror, require_present=True)
    else:
        await index.upsert(mirror)


async def _identity(app: Any, plugin: Any, provider: str, creds: dict[str, Any]) -> Any | None:
    extractor = getattr(plugin, "extract_identity", None)
    if not callable(extractor):
        return None
    return await cast(Callable[..., Awaitable[Any]], extractor)(
        creds, http_client_factory=getattr(app.state, f"{provider}_http_factory", None)
    )


def _superseded(provider: str, name: str, subject: WriteSubject) -> WriteConflict:
    return WriteConflict("superseded", subject=subject, provider=provider, requested=name)


__all__ = [
    "MigratedFlow",
    "begin_connection_oauth",
    "complete_connection_oauth",
    "fail_connection_oauth",
]
