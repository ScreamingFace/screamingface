"""The D18 API-key publication on a pair's Connection (OME-1208 S2'b1; reshaped by OME-1209 E3b).

Since E5a (history cleanup) it also holds what was left of the Profile-backed admin base: the
fresh write-path strategy, the post-commit eviction and the typed persist.

# FEATURE: OME-1138 D18 — the admin PUT (`pair_admin_writes.set_pair_api_key`) lands an API key on
# the pair's Connection through `publish_api_key`; a pair captured as `none` is adopted (the G1
# bridge).
# INVARIANT (design card, one lock/CAS order): marker advance → Connection row → blob, inside ONE
# transaction. The marker's generation CAS is the fence: a writer that observed a stale generation
# changes nothing and surfaces `WriteConflict("superseded", subject="connection")`.
# WHY no compat-document mirror (OME-1209 E4b): no runtime path writes a Profile document. A pair
# changed after E4b is not coherent for an R1 rollback (spec §8 Q7).
# INVARIANT (E5a, history cleanup): a minted row addresses `<account_id>:<row id>`, never a Profile
# address, so a PUT cannot adopt a blob the E5 purge may be deleting.
"""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID, uuid4

from tortoise.transactions import in_transaction

from ..auth_types import AuthType
from ..credential_strategy_cache import credential_strategy_cache
from ..oauth.models import OAuthConnection
from ..oauth.store import OAuthConnectionStore, credential_locator_for
from ..plugin_base import credential_service_provider_for, credential_strategy_from
from .connection_locator import credential_name_from_locator
from .pair_authority import PairAuthority, PairAuthorityConflict, PairAuthorityStore
from .profile_authorize import invalidate_session, oauth_connection_store
from .types import CredentialStoreUnavailable, UnsupportedAuthMode, WriteConflict

logger = logging.getLogger(__name__)

# WHY: the Connection-native default label for a keyed row; unique by construction, so the
# authority never needs a label-conflict path.
_API_KEY_LABEL = "api-key-{id}"
_ERROR_PLACEHOLDER = "error:"


async def persist_credentials_or_refuse(
    strategy: Any, credentials: dict[str, Any], *, description: str
) -> None:
    """Persist through the strategy or refuse with the typed store-unavailable outcome.

    `routes/credential_persistence.py::persist_credentials_or_503` minus the HTTP; the OAuth
    flows keep using that helper, this one serves the D18 publication.
    """
    try:
        await strategy.persist_credentials(credentials)
    except Exception as exc:
        # WHY `Exception`: the store adapter is a port; any failure it raises means "not stored".
        # Store adapters may echo credentials in exception text; log only type + service.
        logger.error(
            "Failed to persist %s for service %s: %s",
            description,
            strategy.credential_service(),
            type(exc).__name__,
        )
        raise CredentialStoreUnavailable(description) from exc


class ConnectionBackedCredentialAdmin:
    """The D18 publication with per-pair authority: the marker's generation CAS fences it."""

    def __init__(self, app: Any, *, markers: PairAuthorityStore | None = None) -> None:
        # WHY the app, not the stores: `credential_store` and `{provider}_http_factory` are read
        # LAZILY at call time — tests monkeypatch them onto `app.state` after the app is built.
        self._app = app
        self._markers = markers or PairAuthorityStore()

    async def publish_api_key(
        self,
        account_id: str,
        provider: str,
        plugin: Any,
        *,
        pair: PairAuthority,
        reuse: OAuthConnection | None,
        raw_api_key: str,
        expected_live: frozenset[UUID],
    ) -> OAuthConnection:
        """Publish `pair` as `migrated` with an active API-key Connection.

        `reuse` keeps an existing row (its id and locator); None mints a row at its own address,
        as a native API-key row. Fenced on `pair.generation`, so a pair captured as `none` is
        adopted (the G1 bridge) and a stale capture loses. `expected_live` is the pair's live rows
        the caller classified: any other live row found after the claim supersedes the write.
        """
        credential_provider = credential_service_provider_for(plugin, provider)
        connection_id = reuse.id if reuse is not None else uuid4()
        locator = (
            reuse.credential_locator
            if reuse is not None
            else credential_locator_for(credential_provider, account_id, connection_id)
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
                await _require_live(account_id, provider, expected_live | {connection.id})
                if reuse is not None:
                    await _publish_api_key_on(store, reuse, provider=provider)
                await persist_credentials_or_refuse(
                    strategy,
                    {"auth_type": "api_key", "api_key": raw_api_key},
                    description="API-key credentials",
                )
        except PairAuthorityConflict as exc:
            raise WriteConflict("superseded", subject="connection", provider=provider) from exc
        self._invalidate(plugin, credential_name)
        return connection

    def _strategy(
        self, plugin: Any, provider: str, credential_name: str, *, auth_type: AuthType
    ) -> Any:
        # WHY not the shared cache: the write path builds a fresh strategy exactly as the route
        # did; the cache is EVICTED after the commit so readers never serve a stale token.
        return credential_strategy_from(
            plugin,
            credential_name,
            auth_type=auth_type,
            credential_store=self._app.state.credential_store,
            http_client_factory=getattr(self._app.state, f"{provider}_http_factory", None),
        )

    def _invalidate(self, plugin: Any, credential_name: str) -> None:
        # Cache invalidation follows the durable boundary so it reflects the committed write.
        invalidate_session(plugin, credential_name)
        # Drop the shared cached strategy so re-auth / api-key change / delete never serve a stale
        # in-memory token from a prior credential (SF-282).
        credential_strategy_cache(self._app).evict(credential_name)


async def live_connection_ids(account_id: str, provider: str) -> frozenset[UUID]:
    """The ids of the pair's non-revoked Connections, read now."""
    ids = (
        await OAuthConnection.filter(account_id=account_id, provider=provider)
        .exclude(status="revoked")
        .values_list("id", flat=True)
    )
    return frozenset(UUID(str(value)) for value in ids)


async def _require_live(account_id: str, provider: str, expected: frozenset[UUID]) -> None:
    """Inside the claim: the pair's live rows must be exactly the ones the caller classified.

    # WHY: a native create on a `migrated` pair claims nothing (owner decision 2026-10-06), so the
    # generation alone cannot see an extra candidate; a write over it would pick one silently.
    """
    if await live_connection_ids(account_id, provider) != expected:
        raise WriteConflict("superseded", subject="connection", provider=provider)


async def _publish_api_key_on(
    store: OAuthConnectionStore, connection: OAuthConnection, *, provider: str
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
        raise WriteConflict("superseded", subject="connection", provider=provider)


__all__ = [
    "ConnectionBackedCredentialAdmin",
    "live_connection_ids",
]
