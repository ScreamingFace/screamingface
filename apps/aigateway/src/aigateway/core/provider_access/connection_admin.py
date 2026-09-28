"""The Connection-backed `ProviderCredentialAdmin` (OME-1208, Stage B S2'b1; spec §3.3 ops 7–9).

# FEATURE: OME-1138 Stage B (D14) — for a `migrated` pair every credential WRITE the legacy Profile
# routes perform lands on the pair's effective Connection through THIS authority; `none` and
# `quarantined` pairs keep the Profile-backed body byte for byte via `super()`.
# INVARIANT (design card, one lock/CAS order): marker advance → index row CAS → Connection row →
# blob, inside ONE transaction. The marker's generation CAS is the fence: a writer that observed a
# stale generation changes nothing and surfaces `WriteConflict("superseded", subject="connection")`.
# INVARIANT (D16 (a), D5): the legacy document is rewritten as a faithful MIRROR of what today's
# Profile would hold, so an R1 rollback (marker reset, blobs kept) serves the same credential from
# the legacy path. While migrated the document is never read as authority — `list` renders the
# Connection's state over it.
# AIDEV-NOTE: subclass, not sibling — the admin contract pins `isinstance(admin,
# ProfileBackedCredentialAdmin)` and patches its seams (`persist_credentials_or_refuse` is called
# through the `profile_admin` module attribute for the same reason).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from tortoise.transactions import in_transaction

from ..credential_blob.store import CredentialBlobMutationConflict
from ..oauth.models import OAuthConnection
from ..oauth.store import OAuthConnectionStore, credential_locator_for
from ..plugin_base import credential_service_provider_for
from ..profile_index import ProfileTransitionConflict
from ..profile_models import Profile, ProfileState, credential_name_for, profile_id_for
from . import profile_admin
from .connection_authority import LEGACY_STATE_FOR_STATUS
from .connection_locator import credential_name_from_locator, credential_strategy_for_connection
from .pair_authority import PairAuthority, PairAuthorityConflict, PairAuthorityStore
from .profile_admin import DEFAULT_LEGACY_NAME, ProfileBackedCredentialAdmin, summary_of
from .profile_authorize import oauth_connection_store
from .types import (
    CredentialSummary,
    TargetMissing,
    UnsupportedAuthMode,
    WriteConflict,
)

# WHY: the Connection-native default label for a keyed row; unique by construction, so the
# authority never needs a label-conflict path.
_API_KEY_LABEL = "api-key-{id}"
_ERROR_PLACEHOLDER = "error:"


def legacy_view(document: Profile, connection: OAuthConnection) -> Profile:
    """The compat document as the legacy facade must SHOW it: the Connection decides the state."""
    state = LEGACY_STATE_FOR_STATUS.get(connection.status)
    if state is None:
        raise ValueError(f"connection {connection.id} is not effective ({connection.status})")
    return document.model_copy(
        update={"state": ProfileState(state), "auth_type": connection.auth_type}
    )


def api_key_mirror(
    document: Profile | None,
    *,
    account_id: str,
    provider: str,
    name: str,
    raw_api_key: str,
) -> Profile:
    """What today's `set_api_key` would leave in the index — the rollback-coherent mirror.

    # INVARIANT (OME-1323, D2): the mirror never writes `defaults` — a document keeps its
    # historical ones byte-identical, and a new document gets the empty model default.
    """
    profile = document or Profile(
        id=profile_id_for(account_id, provider, name),
        account_id=account_id,
        provider=provider,
        name=name,
    )
    profile.auth_type = "api_key"
    profile.state = ProfileState.AUTHENTICATED
    profile.last_refreshed_at = datetime.now(UTC)
    profile.account_label = f"API key ····{raw_api_key[-4:]}"
    profile.scopes = []
    return profile


def _is_effective(connection: OAuthConnection | None) -> bool:
    return connection is not None and connection.status in LEGACY_STATE_FOR_STATUS


class ConnectionBackedCredentialAdmin(ProfileBackedCredentialAdmin):
    """Ops 7–9 with per-pair authority: a migrated pair's effective Connection, else legacy."""

    def __init__(self, app: Any, *, markers: PairAuthorityStore | None = None) -> None:
        super().__init__(app)
        self._markers = markers or PairAuthorityStore()

    # --- op 7 ---------------------------------------------------------------------------------

    async def list(
        self, account_id: str, provider: str | None = None
    ) -> tuple[CredentialSummary, ...]:
        documents = await self._index.list(account_id, provider)
        migrated = {
            pair.provider: pair
            for pair in await self._markers.list(account_id)
            if pair.migration_state == "migrated"
        }
        effective: dict[str, OAuthConnection | None] = {}
        rendered: list[CredentialSummary] = []
        for document in documents:
            pair = migrated.get(document.provider)
            if pair is None:
                rendered.append(summary_of(document))
                continue
            if document.provider not in effective:
                effective[document.provider] = await self._effective(account_id, pair)
            connection = effective[document.provider]
            # WHY omit: a migrated pair with no effective Connection has NO credential (it is
            # `not_connected`); listing its compat document would show a Profile serving nothing.
            if connection is None or not _is_effective(connection):
                continue
            rendered.append(summary_of(legacy_view(document, connection)))
        return tuple(rendered)

    # --- op 8 ---------------------------------------------------------------------------------

    async def set_api_key(
        self,
        account_id: str,
        provider: str,
        *,
        raw_api_key: str,
        legacy_name: str | None,
    ) -> CredentialSummary:
        name = legacy_name or DEFAULT_LEGACY_NAME
        plugin = self._plugin(provider)
        pair = await self._markers.read(account_id, provider)
        if pair.migration_state != "migrated":
            return await super().set_api_key(
                account_id,
                provider,
                raw_api_key=raw_api_key,
                legacy_name=legacy_name,
            )
        current = await self._effective(account_id, pair)
        # WHY start over: a revoked or absent effective Connection is the post-delete state; the
        # key becomes a NEW Connection addressing the requested name's Profile blob (D5: a rollback
        # finds it exactly where the legacy Profile would have written it).
        reuse = current if _is_effective(current) else None
        credential_provider = credential_service_provider_for(plugin, provider)
        connection_id = reuse.id if reuse is not None else uuid4()
        locator = (
            reuse.credential_locator
            if reuse is not None
            else credential_locator_for(credential_provider, account_id, name)
        )
        credential_name = credential_name_from_locator(
            locator,
            credential_provider=credential_provider,
            account_id=account_id,
            connection_id=connection_id,
        )
        strategy = self._strategy(plugin, provider, credential_name, auth_type="api_key")
        if strategy is None:
            raise UnsupportedAuthMode("api_key", provider=provider)

        document = await self._index.get(account_id, provider, name)
        document_observed = document is not None
        mirror = api_key_mirror(
            document,
            account_id=account_id,
            provider=provider,
            name=name,
            raw_api_key=raw_api_key,
        )
        store = oauth_connection_store(self._app)
        try:
            async with in_transaction():
                if reuse is not None:
                    connection = reuse
                else:
                    # WHY before the marker: the marker's FK must name an existing row, and a row
                    # whose id was minted here is uncontended — no lock-order hazard.
                    connection = await store.create_api_key(
                        account_id=account_id,
                        provider=provider,
                        label=_API_KEY_LABEL.format(id=connection_id),
                        connection_id=connection_id,
                        credential_provider=credential_provider,
                        credential_locator=locator,
                    )
                await self._markers.advance(
                    account_id,
                    provider,
                    expected_generation=pair.generation,
                    migration_state="migrated",
                    effective_connection_id=connection.id,
                )
                # INVARIANT (OME-307 Unit 3, kept): an observed document publishes conditionally
                # so a concurrent removal wins; a first mirror is an unconditional create.
                if document_observed:
                    await self._index.upsert(mirror, require_present=True)
                else:
                    await self._index.upsert(mirror)
                await self._mirror_siblings(
                    account_id, provider, name=name, raw_api_key=raw_api_key
                )
                if reuse is not None:
                    await _publish_api_key_on(store, reuse, provider=provider, requested=name)
                await profile_admin.persist_credentials_or_refuse(
                    strategy,
                    {"auth_type": "api_key", "api_key": raw_api_key},
                    description="API-key credentials",
                )
        except PairAuthorityConflict as exc:
            raise WriteConflict(
                "superseded", subject="connection", provider=provider, requested=name
            ) from exc
        except ProfileTransitionConflict as exc:
            raise WriteConflict(
                "superseded", subject="profile", provider=provider, requested=name
            ) from exc
        except CredentialBlobMutationConflict as exc:
            raise WriteConflict(
                "retry_exhausted", subject="profile", provider=provider, requested=name
            ) from exc
        self._invalidate(plugin, credential_name)
        return summary_of(legacy_view(mirror, connection))

    # --- op 9 ---------------------------------------------------------------------------------

    async def delete(self, account_id: str, provider: str, *, legacy_name: str) -> None:
        plugin = self._plugin(provider)
        pair = await self._markers.read(account_id, provider)
        if pair.migration_state != "migrated":
            return await super().delete(account_id, provider, legacy_name=legacy_name)
        document = await self._index.get(account_id, provider, legacy_name)
        if document is None:
            raise TargetMissing(provider, legacy_name)
        current = await self._effective(account_id, pair)
        revocable = current if current is not None and current.status != "revoked" else None
        if revocable is not None:
            strategy = credential_strategy_for_connection(
                self._app, plugin, provider, revocable, account_id=account_id
            )
            credential_name = credential_name_from_locator(
                revocable.credential_locator,
                credential_provider=credential_service_provider_for(plugin, provider),
                account_id=account_id,
                connection_id=revocable.id,
            )
        else:
            # WHY the legacy address: with no effective Connection the compat document's own blob
            # (if any) is the only credential left; an orphan would reappear after a rollback.
            credential_name = credential_name_for(account_id, legacy_name)
            strategy = self._strategy(
                plugin, provider, credential_name, auth_type=document.auth_type
            )
        store = oauth_connection_store(self._app)
        try:
            async with in_transaction():
                await self._markers.advance(
                    account_id,
                    provider,
                    expected_generation=pair.generation,
                    migration_state="migrated",
                )
                await self._index.remove(document.id)
                if revocable is not None:
                    await store.mark_revoked(revocable)
                if strategy is not None:
                    await strategy.delete_credentials()
        except PairAuthorityConflict as exc:
            raise WriteConflict(
                "superseded", subject="connection", provider=provider, requested=legacy_name
            ) from exc
        self._invalidate(plugin, credential_name)

    # --- shared --------------------------------------------------------------------------------

    async def _mirror_siblings(
        self, account_id: str, provider: str, *, name: str, raw_api_key: str
    ) -> None:
        """Every OTHER document of the pair describes the same ONE credential — say so (D-R1-3).

        # WHY: the key lands at the effective row's locator, which may be ANOTHER document's
        # address (an alias write); that document must read api_key after an R1 rollback, as the
        # native key route already ensures (`republish_effective_api_key`). Defaults are kept.
        """
        for document in await self._index.list(account_id, provider):
            if document.name == name:
                continue
            sibling = api_key_mirror(
                document,
                account_id=account_id,
                provider=provider,
                name=document.name,
                raw_api_key=raw_api_key,
            )
            await self._index.upsert(sibling, require_present=True)

    async def _effective(self, account_id: str, pair: PairAuthority) -> OAuthConnection | None:
        if pair.effective_connection_id is None:
            return None
        return await oauth_connection_store(self._app).get(account_id, pair.effective_connection_id)


async def _publish_api_key_on(
    store: OAuthConnectionStore, connection: OAuthConnection, *, provider: str, requested: str
) -> None:
    """Turn the effective Connection into an active api-key row — with the fenced UPDATEs.

    # INVARIANT: every transition is a conditional UPDATE, so a concurrent revoke or delete (the
    # row left its expected status) matches 0 rows and the write is a conflict — never a
    # resurrection. The row object is mutated in place on success, as the store methods do.
    """
    published: OAuthConnection | None = connection
    if connection.status == "pending":
        published = await store.complete_pending(connection, label=connection.label, identity=None)
    if published is not None:
        published = await store.set_auth_type(published, "api_key")
    if published is not None and connection.status != "pending":
        published = await store.reactivate(published)
    if published is not None and published.label.startswith(_ERROR_PLACEHOLDER):
        # WHY: `mark_error` left the OAuth placeholder; an API key has no identity to name the row
        # by, so it takes the Connection-native label (unique by construction).
        published = await store.patch_active_label(
            published, _API_KEY_LABEL.format(id=published.id)
        )
    if published is None:
        raise WriteConflict(
            "superseded", subject="connection", provider=provider, requested=requested
        )


__all__ = ["ConnectionBackedCredentialAdmin", "api_key_mirror", "legacy_view"]
