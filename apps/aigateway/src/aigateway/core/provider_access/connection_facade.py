"""Legacy Profile facades over a MIGRATED pair's effective Connection (OME-1208, Stage B S2'b3).

# FEATURE: Stage B Target — the Profile status/patch/refresh routes are compatibility facades: for
# a `migrated` pair they render state and auth type from the effective Connection
# (locator-authoritative reads) and refresh THROUGH it; `defaults`/`account_label` stay on the
# compatibility document (D16 (a)), which the authority mirrors on every write (D-S2b-2).
# INVARIANT: a `none`/`quarantined` pair is handed back as its legacy document after ONE marker
# read; nothing here writes for such a pair.
# AIDEV-NOTE: the legacy refresh body stays in `routes/auth.py`; `refresh_facade` is the
# Connection-owned half only (D-S2b3-4/5). The routes keep rendering their own refusals.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from tortoise.transactions import in_transaction

from ..credential_strategy_cache import credential_strategy_cache
from ..errors import AuthError, CredentialNotFoundError
from ..oauth.models import OAuthConnection
from ..oauth.store import OAuthConnectionStore
from ..plugin_base import credential_service_provider_for
from ..profile_index import ProfileIndexStore, ProfileTransitionConflict
from ..profile_models import Profile, ProfileDefaults, ProfileState
from .auth_mode import auth_type_of
from .connection_admin import legacy_view
from .connection_authority import LEGACY_STATE_FOR_STATUS
from .connection_locator import credential_name_from_locator, credential_strategy_for_connection
from .pair_authority import PairAuthorityStore
from .profile_authorize import invalidate_session, oauth_connection_store
from .types import TargetReauthRequired, UnsupportedAuthMode, WriteConflict


@dataclass(frozen=True, slots=True)
class FacadeTarget:
    """What a legacy Profile facade addresses: the document, plus the authority when migrated."""

    document: Profile
    connection: OAuthConnection | None

    @property
    def view(self) -> Profile:
        """The document as the facade must SHOW it — the Connection decides state and auth type."""
        if self.connection is None:
            return self.document
        return legacy_view(self.document, self.connection)


async def facade_target(
    app: Any, *, account_id: str, provider: str, name: str
) -> FacadeTarget | None:
    """Resolve `(account, provider, name)` for a facade; `None` reads as `404 profile_not_found`.

    # INVARIANT (D-S2b3-2): a migrated pair with no document, or whose effective Connection is
    # absent or revoked, is nothing to show — exactly what op 7's list omits, so status, patch
    # and list agree. The mirror document's own `state` is never load-bearing for a read.
    """
    document = await app.state.profile_index.get(account_id, provider, name)
    if document is None:
        return None
    pair = await PairAuthorityStore().read(account_id, provider)
    if pair.migration_state != "migrated":
        return FacadeTarget(document, None)
    connection: OAuthConnection | None = None
    if pair.effective_connection_id is not None:
        connection = await oauth_connection_store(app).get(account_id, pair.effective_connection_id)
    if connection is None or connection.status not in LEGACY_STATE_FOR_STATUS:
        return None
    return FacadeTarget(document, connection)


async def patch_facade(
    app: Any,
    target: FacadeTarget,
    *,
    defaults: ProfileDefaults | None,
    account_label: str | None,
) -> Profile:
    """Edit metadata on the compatibility document only (D16 (a)); raises on a vanished document.

    # WHY no marker advance: a metadata edit changes no credential authority (D-S2b3-3), so a
    # flow in flight is not fenced by it — exactly as the legacy route never bumped the OAuth
    # generation. The Connection row is not touched either.
    """
    updated = await app.state.profile_index.update_metadata(
        target.document.id, defaults=defaults, account_label=account_label
    )
    return FacadeTarget(updated, target.connection).view


async def refresh_facade(
    app: Any, plugin: Any, target: FacadeTarget, *, provider: str, account_id: str, name: str
) -> Profile:
    """The Connection-owned refresh of a migrated pair (D-S2b3-4); returns the facade's view.

    Raises `TargetReauthRequired` (the legacy `401 auth_required` body), `UnsupportedAuthMode`
    (`400 provider_does_not_use_oauth`) or `WriteConflict` (`409 profile_conflict`).
    """
    connection = target.connection
    if connection is None:
        raise ValueError("refresh_facade needs a migrated target")
    # INVARIANT (OME-1198, kept for the facade): the bare legacy URL, no `/api-key` suffix.
    reauth_url = f"/v1/auth/{provider}/profiles/{name}"
    if connection.status != "active":
        # INVARIANT (D-S2b3-5): an errored or pending authority is never refreshed — no network
        # call, no row or document mutation. SF-291: an errored OAuth Connection is superseded
        # by re-auth, never revived; a pending row belongs to the flow in progress.
        state = LEGACY_STATE_FOR_STATUS[connection.status]
        raise TargetReauthRequired(
            provider, reauth_url, message=f"stored credential is {state}; re-authenticate"
        )
    credential_name = credential_name_from_locator(
        connection.credential_locator,
        credential_provider=credential_service_provider_for(plugin, provider),
        account_id=account_id,
        connection_id=connection.id,
    )
    cache = credential_strategy_cache(app)
    # WHY the shared instance: its lock single-flights the refresh with concurrent dispatch under
    # the same locator name (SF-323, the `refresh_connection` idiom); evicted afterwards so the
    # next dispatch rebuilds from the persisted tokens (SF-282).
    strategy = cache.get_or_create(
        provider=provider,
        auth_type=auth_type_of(None, connection),
        credential_name=credential_name,
        build=lambda: credential_strategy_for_connection(
            app, plugin, provider, connection, account_id=account_id
        ),
    )
    if strategy is None:
        raise UnsupportedAuthMode("oauth")
    store = oauth_connection_store(app)
    index: ProfileIndexStore = app.state.profile_index
    try:
        await strategy.refresh_credentials()
    except (CredentialNotFoundError, AuthError) as exc:
        cache.evict(credential_name)
        await _mark_failed(store, index, target.document, connection, str(exc))
        invalidate_session(plugin, credential_name)
        raise TargetReauthRequired(provider, reauth_url, message=str(exc)) from exc
    cache.evict(credential_name)
    invalidate_session(plugin, credential_name)
    mirror = target.document.model_copy(
        update={"state": ProfileState.AUTHENTICATED, "last_refreshed_at": datetime.now(UTC)}
    )
    try:
        # INVARIANT (OME-307 H-1): publish only while the document is still PRESENT — a delete
        # that committed during the provider network window removed it (S2'b1 op 9) and wins.
        async with in_transaction():
            await store.touch_last_refreshed(connection)
            await index.upsert(mirror, require_present=True)
    except ProfileTransitionConflict as exc:
        raise WriteConflict(
            "superseded", subject="profile", provider=provider, requested=name
        ) from exc
    return legacy_view(mirror, connection)


async def _mark_failed(
    store: OAuthConnectionStore,
    index: ProfileIndexStore,
    document: Profile,
    connection: OAuthConnection,
    message: str,
) -> None:
    """Mark the authority errored (fenced `active`) and mirror it — only when the row was marked."""
    async with in_transaction():
        if await store.mark_error(connection, message) is None:
            return
        try:
            await index.upsert(
                document.model_copy(update={"state": ProfileState.ERROR}), require_present=True
            )
        except ProfileTransitionConflict:
            # WHY swallowed: the document vanished during the window (deleted); the row is
            # marked and there is nothing left to mirror — the caller still answers 401.
            return


__all__ = ["FacadeTarget", "facade_target", "patch_facade", "refresh_facade"]
