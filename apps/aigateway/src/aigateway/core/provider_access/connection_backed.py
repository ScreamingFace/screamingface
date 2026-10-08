"""The Connection-backed `ProviderAccess` (OME-1208, Stage B S2'): per-pair authority, one port.

# FEATURE: Stage B Target — a pair whose marker is `migrated` is served from its effective
# Connection; `none` and `quarantined` pairs take today's Profile-backed path, INHERITED — not
# copied — so every legacy seam stays live. Op 1 (`defaults_for`) never reads the marker (D16 (a):
# defaults stay in the legacy index until the Stage C cutover); op 3 is pure. Stage E (OME-1209)
# deletes the parent and this class becomes the only implementation.
# INVARIANT (D14): one authority per pair per call — the marker is read once at the top of
# `resolve`/`availability`; ops 4–5 follow the target's backing. An unreadable marker store
# propagates its error: never a silent fall-back to a superseded legacy credential.
# AIDEV-NOTE: prior suites pin `isinstance(app.state.provider_access, ProfileBackedProviderAccess)`
# and patch `ProfileBackedProviderAccess.resolve` / `.authorize` as seams; `super()` is what keeps
# them honest. Do not replace this subclass by composition without re-deciding those pins.
"""

from __future__ import annotations

from typing import Any

from ..credential_blob import DispatchObservation, OperationalOutcome
from ..oauth.models import OAuthConnection
from .connection_authority import (
    MigratedBacking,
    authorize_migrated,
    availability_status_for,
    begin_dispatch_migrated,
    migrated_target,
    operational_availability_status_for,
    record_dispatch_failure_migrated,
    record_dispatch_outcome_migrated,
    require_operational_access_migrated,
)
from .pair_authority import PairAuthority, PairAuthorityStore
from .profile_authorize import oauth_connection_store
from .profile_backed import ProfileBackedProviderAccess
from .selector import Selector
from .types import (
    Authorization,
    AvailabilityRow,
    AvailabilityStatus,
    CredentialTarget,
    ResolvePolicy,
)


class ConnectionBackedProviderAccess(ProfileBackedProviderAccess):
    """Migrated pairs from their effective Connection; every other pair exactly as before."""

    def __init__(self, app: Any, *, markers: PairAuthorityStore | None = None) -> None:
        super().__init__(app)
        self._markers = markers if markers is not None else PairAuthorityStore()

    async def resolve(
        self,
        account_id: str,
        provider: str,
        selector: Selector,
        *,
        plugin: Any,
        policy: ResolvePolicy = ResolvePolicy.DISPATCH,
    ) -> CredentialTarget:
        pair = await self._markers.read(account_id, provider)
        if pair.migration_state != "migrated":
            return await super().resolve(
                account_id, provider, selector, plugin=plugin, policy=policy
            )
        document = await self._index.get(account_id, provider, selector.name)
        if document is None:
            # WHY: a selector naming no legacy document of this pair is exactly today's situation
            # — the Connection-label path, now locator-authoritative (`connection_target`), so the
            # effective Connection can be matched by label without being poisoned. Never a guess.
            target = await self._resolve_without_profile(
                account_id, provider, selector, plugin=plugin, policy=policy
            )
            return await require_operational_access_migrated(
                self._app,
                target,
                plugin=plugin,
                provider=provider,
                requested=selector.name,
            )
        connection = await self._effective_connection(account_id, pair)
        target = migrated_target(
            account_id, provider, selector, document, connection, plugin=plugin
        )
        return await require_operational_access_migrated(
            self._app,
            target,
            plugin=plugin,
            provider=provider,
            requested=selector.name,
        )

    async def _effective_connection(
        self, account_id: str, pair: PairAuthority
    ) -> OAuthConnection | None:
        if pair.effective_connection_id is None:
            return None
        return await oauth_connection_store(self._app).get(account_id, pair.effective_connection_id)

    async def authorize(
        self, target: CredentialTarget, *, plugin: Any, provider: str
    ) -> Authorization:
        if isinstance(target._backing, MigratedBacking):
            return await authorize_migrated(self._app, target, plugin=plugin, provider=provider)
        return await super().authorize(target, plugin=plugin, provider=provider)

    async def begin_dispatch(
        self, target: CredentialTarget, *, plugin: Any, provider: str
    ) -> DispatchObservation | None:
        if target.auth_type != "api_key":
            return None
        backing = target._backing
        connection = backing.connection if isinstance(backing, MigratedBacking) else backing
        if not isinstance(connection, OAuthConnection):
            return None
        pair = await self._markers.read(str(connection.account_id), connection.provider)
        if pair.migration_state != "migrated" or pair.effective_connection_id != connection.id:
            return None
        return await begin_dispatch_migrated(self._app, target, plugin=plugin, provider=provider)

    async def record_dispatch_failure(
        self, target: CredentialTarget, status: int, detail: Any, *, plugin: Any
    ) -> dict[str, Any] | None:
        if isinstance(target._backing, MigratedBacking):
            return await record_dispatch_failure_migrated(self._app, target, detail, plugin=plugin)
        return await super().record_dispatch_failure(target, status, detail, plugin=plugin)

    async def record_dispatch_outcome(
        self,
        target: CredentialTarget,
        observation: DispatchObservation,
        outcome: OperationalOutcome,
        detail: Any,
        *,
        plugin: Any,
    ) -> dict[str, Any] | None:
        return await record_dispatch_outcome_migrated(
            self._app,
            target,
            observation,
            outcome,
            detail,
            plugin=plugin,
        )

    async def availability(self, account_id: str) -> tuple[AvailabilityRow, ...]:
        """Op 6 reads the pair authority: a migrated provider reports its Connection's status.

        # WHY the overlay: the legacy precedence stays for every unmarked provider (D17 window
        # rule, Connections not folded in), while a migrated pair's still-present document would
        # otherwise keep reporting `connected` after its authority errored or was deleted.
        """
        rows = await super().availability(account_id)
        migrated = [
            pair
            for pair in await self._markers.list(account_id)
            if pair.migration_state == "migrated"
        ]
        if not migrated:
            return rows
        statuses: dict[str, AvailabilityStatus] = {row.provider: row.status for row in rows}
        for pair in migrated:
            connection = await self._effective_connection(account_id, pair)
            registry = getattr(self._app.state, "providers", None)
            plugin = None if registry is None else registry.get(pair.provider)
            statuses[pair.provider] = (
                availability_status_for(connection)
                if plugin is None
                else await operational_availability_status_for(self._app, connection, plugin=plugin)
            )
        return tuple(AvailabilityRow(provider, statuses[provider]) for provider in sorted(statuses))
