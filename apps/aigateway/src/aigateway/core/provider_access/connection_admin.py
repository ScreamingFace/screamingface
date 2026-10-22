"""The D18 API-key publication on a pair's Connection (OME-1208 S2'b1; reshaped by OME-1209 E3b).

# FEATURE: OME-1138 D18 — the admin PUT (`pair_admin_writes.set_pair_api_key`) lands an API key on
# the pair's Connection through `publish_api_key`; a pair captured as `none` is adopted (the G1
# bridge).
# INVARIANT (design card, one lock/CAS order): marker advance → Connection row → blob, inside ONE
# transaction. The marker's generation CAS is the fence: a writer that observed a stale generation
# changes nothing and surfaces `WriteConflict("superseded", subject="connection")`.
# WHY no compat-document mirror (OME-1209 E4b): no runtime path writes a Profile document. A pair
# changed after E4b is not coherent for an R1 rollback (spec §8 Q7).
"""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

from tortoise.transactions import in_transaction

from ..oauth.models import OAuthConnection
from ..oauth.store import OAuthConnectionStore, credential_locator_for
from ..plugin_base import credential_service_provider_for
from . import profile_admin
from .connection_locator import credential_name_from_locator
from .pair_authority import PairAuthority, PairAuthorityConflict, PairAuthorityStore
from .profile_admin import ProfileBackedCredentialAdmin
from .profile_authorize import oauth_connection_store
from .types import UnsupportedAuthMode, WriteConflict

# WHY: the Connection-native default label for a keyed row; unique by construction, so the
# authority never needs a label-conflict path.
_API_KEY_LABEL = "api-key-{id}"
_ERROR_PLACEHOLDER = "error:"


class ConnectionBackedCredentialAdmin(ProfileBackedCredentialAdmin):
    """The D18 publication with per-pair authority: the marker's generation CAS fences it."""

    def __init__(self, app: Any, *, markers: PairAuthorityStore | None = None) -> None:
        super().__init__(app)
        self._markers = markers or PairAuthorityStore()

    async def publish_api_key(
        self,
        account_id: str,
        provider: str,
        plugin: Any,
        *,
        pair: PairAuthority,
        reuse: OAuthConnection | None,
        name: str,
        raw_api_key: str,
        expected_live: frozenset[UUID],
    ) -> OAuthConnection:
        """Publish `pair` as `migrated` with an active API-key Connection.

        `reuse` keeps an existing row (its id and locator); None mints a row on `name`'s Profile
        address. Fenced on `pair.generation`, so a pair captured as `none` is adopted (the G1
        bridge) and a stale capture loses. `expected_live` is the pair's live rows the caller
        classified: any other live row found after the claim supersedes the write.
        """
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
                await _require_live(
                    account_id, provider, expected_live | {connection.id}, requested=name
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
        self._invalidate(plugin, credential_name)
        return connection


async def live_connection_ids(account_id: str, provider: str) -> frozenset[UUID]:
    """The ids of the pair's non-revoked Connections, read now."""
    ids = (
        await OAuthConnection.filter(account_id=account_id, provider=provider)
        .exclude(status="revoked")
        .values_list("id", flat=True)
    )
    return frozenset(UUID(str(value)) for value in ids)


async def _require_live(
    account_id: str, provider: str, expected: frozenset[UUID], *, requested: str
) -> None:
    """Inside the claim: the pair's live rows must be exactly the ones the caller classified.

    # WHY: a native create on a `migrated` pair claims nothing (owner decision 2026-10-06), so the
    # generation alone cannot see an extra candidate; a write over it would pick one silently.
    """
    if await live_connection_ids(account_id, provider) != expected:
        raise WriteConflict(
            "superseded", subject="connection", provider=provider, requested=requested
        )


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


__all__ = [
    "ConnectionBackedCredentialAdmin",
    "live_connection_ids",
]
