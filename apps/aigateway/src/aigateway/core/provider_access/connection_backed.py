"""The Connection-backed `ProviderAccess` (OME-1208, Stage B S2'; OME-1209, Stage E, E4a).

# FEATURE: Stage E plan §3 E4a — the pair marker alone decides how a pair resolves, and the
# legacy Profile index is never read. A `migrated` pair whose marker names an effective Connection
# is served from it; any other `migrated`, `none` or unmarked pair resolves through its Connections
# by label (chatless or ambient when it has none); a `quarantined` pair fails closed. Op 3 is pure;
# op 1 (the stored-defaults read) was deleted at Stage E, E2b.
# INVARIANT (D14): one authority per pair per call — the marker is read once at the top of
# `resolve`/`availability`; ops 4–5 follow the target's backing. An unreadable marker store
# propagates its error: never a silent fall-back.
# INVARIANT (spec §9 Q8): a Profile document is never a target and never a status; only the
# offline tools still read the index until E5 deletes it.
"""

from __future__ import annotations

import logging
from dataclasses import replace
from typing import Any

from ..auth_types import AuthMode
from ..credential_blob import DispatchObservation, OperationalOutcome
from ..oauth.models import OAuthConnection
from .auth_mode import (
    allows_chatless,
    auth_mode,
    auth_type_of,
    available_auth_modes,
    contract_auth_mode,
)
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
from .ports import ProviderAccess, ProviderOperationalAccess
from .profile_authorize import authorize, oauth_connection_store, record_dispatch_failure
from .selector import Selector
from .targets import connection_target, targetless
from .types import (
    Authorization,
    AvailabilityRow,
    AvailabilityStatus,
    CredentialTarget,
    PairNotManageable,
    ResolvePolicy,
    SelectorAmbiguous,
    SelectorUnknown,
    TargetMissing,
    TargetPending,
    TargetReauthRequired,
    WriteConflict,
)

logger = logging.getLogger(__name__)
# The refusals that mean "this pair's credential is not usable now" — the ones OME-1389 could not
# see. Selector and store refusals already say what went wrong in their own response.
_UNUSABLE = (TargetMissing, TargetPending, TargetReauthRequired)


def _log_refusal(
    account_id: str,
    provider: str,
    connection: OAuthConnection | None,
    refusal: Exception,
    policy: ResolvePolicy,
) -> None:
    """One record per refused resolve on a migrated pair (OME-1389).

    # WHY: this refusal never reaches the provider, so the access log's `401` was the only trace
    # and finding the cause took a database query. The refused Connection and its status are
    # known only here — the refusal itself carries neither.
    # INVARIANT: identifiers and closed vocabularies only; never the refusal's message, the
    # Connection's `error_message` (provider text) or its locator.
    # WHY WARNING: as `log_dispatch_failure` for a 4xx — visible to WARNING+ alerting, no page.
    """
    logger.warning(
        "provider access refused provider=%s account=%s connection=%s status=%s refusal=%s "
        "policy=%s",
        provider,
        account_id,
        "none" if connection is None else connection.id,
        "none" if connection is None else connection.status,
        type(refusal).__name__,
        policy.value,
    )


def _answers(selector: Selector, effective: OAuthConnection | None) -> bool:
    """Whether a migrated pair's effective reference answers this selector.

    # WHY: the reference answers the pair's default target, and a name only when it is the
    # effective Connection's own label — the document name the backfill gave it. Any other name
    # is matched by label or refused, never served by another row (refuse, never retarget).
    """
    if selector.is_default:
        return True
    return effective is not None and effective.label == selector.name


class ConnectionBackedProviderAccess:
    """Every pair from its Connections, under the authority its marker names."""

    def __init__(self, app: Any, *, markers: PairAuthorityStore | None = None) -> None:
        # WHY the app, not the stores: `credential_store`, `oauth_connections` and
        # `{provider}_http_factory` are read LAZILY at call time — tests monkeypatch them onto
        # `app.state` after the app is built.
        self._app = app
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
        # INVARIANT: a provider declaring ONLY "none" owns no credential slot.
        # Legacy rows with the same provider string cannot shadow local no-auth dispatch.
        if available_auth_modes(plugin) == ("none",):
            return targetless(account_id, plugin)
        pair = await self._markers.read(account_id, provider)
        if pair.migration_state == "quarantined":
            # WHY fail closed (spec §9 Q8): quarantine is the backfill's verdict that the pair's
            # candidates could not be proven one credential; serving either one would guess, and
            # only the offline backfill can settle the pair.
            raise PairNotManageable(provider, "unresolved")
        if pair.migration_state != "migrated":
            target = await self._resolve_by_label(
                account_id, provider, selector, plugin=plugin, policy=policy
            )
            return replace(target, _observed_pair=pair)
        connection = await self._effective_connection(account_id, pair)
        if pair.effective_connection_id is None or not _answers(selector, connection):
            return await self._resolve_migrated_by_label(
                account_id, provider, selector, plugin=plugin, policy=policy
            )
        try:
            target = migrated_target(account_id, provider, selector, connection, plugin=plugin)
            return await require_operational_access_migrated(
                self._app,
                target,
                plugin=plugin,
                provider=provider,
                requested=selector.name,
            )
        except _UNUSABLE as refusal:
            _log_refusal(account_id, provider, connection, refusal, policy)
            raise

    async def _resolve_migrated_by_label(
        self,
        account_id: str,
        provider: str,
        selector: Selector,
        *,
        plugin: Any,
        policy: ResolvePolicy,
    ) -> CredentialTarget:
        # WHY the label path (spec §9 Q9): a migrated pair whose marker names no effective
        # Connection was disconnected, and a row added since is matched by label, never guessed;
        # a named selector is matched the same way. The row refused here is the one matched,
        # which need not be the effective one.
        matched: OAuthConnection | None = None
        try:
            target = await self._resolve_by_label(
                account_id, provider, selector, plugin=plugin, policy=policy
            )
            matched = target._backing if isinstance(target._backing, OAuthConnection) else None
            return await require_operational_access_migrated(
                self._app,
                target,
                plugin=plugin,
                provider=provider,
                requested=selector.name,
            )
        except _UNUSABLE as refusal:
            _log_refusal(account_id, provider, matched, refusal, policy)
            raise

    async def _resolve_by_label(
        self,
        account_id: str,
        provider: str,
        selector: Selector,
        *,
        plugin: Any,
        policy: ResolvePolicy,
    ) -> CredentialTarget:
        connection = await self._active_connection(account_id, provider, selector)
        if connection is not None:
            connection = await self._repair_api_key_only(plugin, connection)
            return connection_target(account_id, provider, connection, plugin=plugin)
        # WHY the escape (OME-1167): the model-parameters DATASHEET needs no stored target for
        # the DEFAULT selector. Chat never asks for it — dispatch keeps the refusal.
        admitted = policy is ResolvePolicy.DATASHEET and selector.is_default
        if not allows_chatless(plugin) and not admitted:
            raise TargetMissing(provider, selector.name)
        return targetless(account_id, plugin)

    async def _active_connection(
        self, account_id: str, provider: str, selector: Selector
    ) -> OAuthConnection | None:
        connections = await oauth_connection_store(self._app).list(
            account_id, provider=provider, status="active"
        )
        if not connections:
            return None
        if selector.explicit:
            for connection in connections:
                if connection.label == selector.name:
                    return connection
        if selector.is_default and len(connections) == 1:
            return connections[0]
        if selector.is_default:
            raise SelectorAmbiguous(provider)
        raise SelectorUnknown(
            provider, selector.name, tuple(connection.label for connection in connections)
        )

    async def _repair_api_key_only(
        self, plugin: Any, connection: OAuthConnection
    ) -> OAuthConnection:
        auth_type = auth_type_of(connection)
        modes = available_auth_modes(plugin)
        if auth_type != "oauth" or "oauth" in modes or "api_key" not in modes:
            return connection
        # INVARIANT: an api-key-only provider has no OAuth path. Retag the connection before
        # parameter validation and credential reads so failures stay recoverable through the
        # connection-native replace-key endpoint.
        repaired = await oauth_connection_store(self._app).set_auth_type(connection, "api_key")
        if repaired is None:
            raise WriteConflict("superseded", subject="connection")
        return repaired

    async def _effective_connection(
        self, account_id: str, pair: PairAuthority
    ) -> OAuthConnection | None:
        if pair.effective_connection_id is None:
            return None
        return await oauth_connection_store(self._app).get(account_id, pair.effective_connection_id)

    def auth_mode(self, target: CredentialTarget, plugin: Any) -> AuthMode:
        return auth_mode(target, plugin=plugin)

    def contract_auth_mode(self, target: CredentialTarget, plugin: Any) -> AuthMode:
        return contract_auth_mode(target, plugin=plugin)

    async def authorize(
        self, target: CredentialTarget, *, plugin: Any, provider: str
    ) -> Authorization:
        if isinstance(target._backing, MigratedBacking):
            return await authorize_migrated(self._app, target, plugin=plugin, provider=provider)
        return await authorize(self._app, target, plugin=plugin, provider=provider)

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
        return await record_dispatch_failure(self._app, target, status, detail, plugin=plugin)

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
        """Op 6 (A3, OME-1230): a migrated pair reports its effective Connection's status.

        # WHY every other pair is `not_connected`: D17 keeps Connections out of the listing until
        # its flagged change, so an unmarked, `none` or `quarantined` pair reads as a
        # Connection-only account always has. A registered provider with no pair is listed too.
        # INVARIANT: no secret read, no refresh, no mutation; rows carry provider and status
        # ONLY, sorted by provider for a stable listing.
        """
        registry = getattr(self._app.state, "providers", None)
        statuses: dict[str, AvailabilityStatus] = {}
        if registry is not None:
            statuses = {plugin.custom_llm_provider: "not_connected" for plugin in registry.all()}
        for pair in await self._markers.list(account_id):
            if pair.migration_state != "migrated":
                continue
            connection = await self._effective_connection(account_id, pair)
            plugin = None if registry is None else registry.get(pair.provider)
            statuses[pair.provider] = (
                availability_status_for(connection)
                if plugin is None
                else await operational_availability_status_for(self._app, connection, plugin=plugin)
            )
        return tuple(AvailabilityRow(provider, statuses[provider]) for provider in sorted(statuses))


def provider_access_for(app: Any) -> ProviderAccess:
    """The app's port implementation; created Connection-backed only when none is wired.

    # INVARIANT (review F2): whatever `app.state.provider_access` holds IS the port — a fake in a
    # test or a later backing must be what the shims call. The lazy branch exists for apps built
    # without `main.create_app` (scaffolds) and only fills an ABSENT slot.
    """
    access = getattr(app.state, "provider_access", None)
    if access is None:
        access = ConnectionBackedProviderAccess(app)
        app.state.provider_access = access
    return access


def operational_access_for(app: Any) -> ProviderOperationalAccess | None:
    """Return the optional outcome capability without widening the stable port."""
    access = provider_access_for(app)
    return access if isinstance(access, ProviderOperationalAccess) else None
