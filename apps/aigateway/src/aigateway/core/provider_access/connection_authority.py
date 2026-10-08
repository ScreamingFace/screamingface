"""Migrated-pair operations of the Connection-backed authority (OME-1208, Stage B S2'; D14).

The read-path operations for a pair whose marker is `migrated`: its effective Connection is the
one credential target, lifecycle and revision-fenced operational evidence jointly decide access,
and every read-path mutation lands on that Connection or its exact strategy-declared blob slot.

# FEATURE: Stage B Target — Connection-backed authority behind the unchanged provider-access port.
# INVARIANT (D14): the legacy document's own state is never authority for a migrated pair; the
# effective Connection's status is. The document contributes its defaults (D16 (a)) and its name —
# the selector still names it, so every facade URL stays the legacy one.
# INVARIANT (facade parity): legacy op 4/5 rules still apply to unclassified failures. A classified
# `needs_reauth` outcome instead preserves lifecycle, evicts and invalidates, while resolve exposes
# the pinned OME-1198 refusal; `insufficient_credits` remains dispatchable for recovery.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..credential_blob import (
    CredentialOperationalState,
    DispatchObservation,
    OperationalOutcome,
)
from ..credential_strategy_cache import credential_strategy_cache
from ..errors import AuthError, CredentialNotFoundError
from ..oauth.models import OAuthConnection
from ..plugin_base import credential_service_provider_for
from ..profile_models import Profile
from .auth_mode import auth_type_of
from .connection_locator import (
    credential_blob_address,
    credential_name_from_locator,
    credential_strategy_for_connection,
)
from .profile_authorize import invalidate_session, oauth_connection_store, reauth_url_for
from .profile_backed import context_stamp
from .selector import Selector
from .types import (
    Authorization,
    AvailabilityStatus,
    CredentialStoreUnavailable,
    CredentialTarget,
    TargetMissing,
    TargetPending,
    TargetReauthRequired,
    UnsupportedAuthMode,
)

# WHY public: the design card's state mapping in the LEGACY vocabulary (active→authenticated,
# pending→pending, error→error; revoked/absent have no legacy state) — the admin facade renders a
# migrated pair's compat document with it.
LEGACY_STATE_FOR_STATUS: dict[str, str] = {
    "active": "authenticated",
    "pending": "pending",
    "error": "error",
}
_AVAILABILITY_FOR_STATUS: dict[str, AvailabilityStatus] = {
    "active": "connected",
    "pending": "pending",
    "error": "error",
}


@dataclass(frozen=True)
class MigratedBacking:
    """The private `_backing` of a target served by the Connection-backed authority.

    # WHY a distinct type: the legacy Connection fall-back (a bare `OAuthConnection` backing) marks
    # the row but never rewrites a failure detail; a migrated target carries pair-authoritative
    # identity for authorization, failure handling, and revision-fenced operational observations.
    """

    connection: OAuthConnection


def migrated_target(
    account_id: str,
    provider: str,
    selector: Selector,
    document: Profile,
    connection: OAuthConnection | None,
    *,
    plugin: Any,
) -> CredentialTarget:
    """The one target of a migrated pair, or the refusal its effective Connection's status names.

    # INVARIANT: no effective Connection, or a revoked one, is "Connection-owned and empty" — the
    # legitimate post-delete state (S1) — and refuses as MISSING; it never falls back to the
    # document, whose still-authenticated row is exactly the "old credential reappears" hazard.
    """
    if connection is None or connection.status == "revoked":
        raise TargetMissing(provider, selector.name)
    if connection.status == "pending":
        raise TargetPending(provider, selector.name)
    if connection.status != "active":
        # INVARIANT (pinned by OME-1198 for Profiles, kept for the facade): the resolve-time
        # refusal names the BARE legacy URL, no `/api-key` suffix even for an api-key credential.
        raise TargetReauthRequired(
            provider, f"/v1/auth/{provider}/profiles/{selector.name}", requested=selector.name
        )
    auth_type = auth_type_of(None, connection)
    return CredentialTarget(
        kind="stored",
        auth_type=auth_type,
        # WHY the locator: the migrated Connection addresses the blob the Profile already has —
        # "reads without re-entry" (card: Stage B Target); the strategy cache is keyed by this
        # name, so eviction by either path drops the same entry.
        credential_name=credential_name_from_locator(
            connection.credential_locator,
            credential_provider=credential_service_provider_for(plugin, provider),
            account_id=account_id,
            connection_id=connection.id,
        ),
        context_stamp=context_stamp(account_id, None, connection),
        reauth_url=reauth_url_for(provider, selector.name, auth_type),
        defaults=document.defaults,
        _backing=MigratedBacking(connection),
    )


def _strategy_for(app: Any, plugin: Any, provider: str, target: CredentialTarget) -> Any:
    backing: MigratedBacking = target._backing
    connection = backing.connection
    # Share ONE strategy instance per credential across concurrent requests (SF-282), under the
    # locator-derived name — the same key the Profile-backed path used for this blob.
    return credential_strategy_cache(app).get_or_create(
        provider=provider,
        auth_type=target.auth_type,
        credential_name=str(target.credential_name),
        build=lambda: credential_strategy_for_connection(
            app, plugin, provider, connection, account_id=str(connection.account_id)
        ),
    )


async def authorize_migrated(
    app: Any, target: CredentialTarget, *, plugin: Any, provider: str
) -> Authorization:
    """Op 4 for a migrated target: the Profile rules, applied to the effective Connection."""
    backing: MigratedBacking = target._backing
    credential_name = str(target.credential_name)
    strategy = _strategy_for(app, plugin, provider, target)
    if strategy is None:
        if target.auth_type == "api_key":
            raise UnsupportedAuthMode("api_key", provider=provider)
        return Authorization(
            headers={}, credential_name=target.credential_name, auth_type=target.auth_type
        )
    try:
        raw_headers = await strategy.get_authorization_header()
    except (CredentialNotFoundError, AuthError) as exc:
        credential_strategy_cache(app).evict(credential_name)
        if isinstance(exc, AuthError):
            # WHY only a REJECTED credential marks: an absent blob is recoverable, and flipping
            # the authority to error would hide that (the Profile rule, kept for the facade).
            await oauth_connection_store(app).mark_error(backing.connection, str(exc))
            invalidate_session(plugin, credential_name)
        raise TargetReauthRequired(provider, target.reauth_url or "", message=str(exc)) from exc
    # INVARIANT (review F5): proven a header mapping BEFORE any write, so garbage never leaves a
    # false `last_used`.
    headers = dict(raw_headers)
    await oauth_connection_store(app).touch_last_used(backing.connection)
    return Authorization(
        headers=headers, credential_name=target.credential_name, auth_type=target.auth_type
    )


async def record_dispatch_failure_migrated(
    app: Any, target: CredentialTarget, detail: Any, *, plugin: Any
) -> dict[str, Any]:
    """Op 5 for a migrated target: mark the Connection, evict, invalidate, rewrite the detail."""
    backing: MigratedBacking = target._backing
    credential_name = str(target.credential_name)
    credential_strategy_cache(app).evict(credential_name)
    body = detail if isinstance(detail, dict) else {"message": str(detail)}
    message = str(body.get("message", str(detail)))
    await oauth_connection_store(app).mark_error(backing.connection, message)
    invalidate_session(plugin, credential_name)
    return {
        "code": body.get("code", "auth_required"),
        "message": message,
        "reauth_url": body.get("reauth_url", target.reauth_url),
    }


def _connection_of(target: CredentialTarget) -> OAuthConnection:
    backing = target._backing
    return backing.connection if isinstance(backing, MigratedBacking) else backing


def _blob_address(
    app: Any, target: CredentialTarget, *, plugin: Any, provider: str
) -> tuple[str, str]:
    connection = _connection_of(target)
    address = credential_blob_address(app, plugin, provider, connection)
    if address is None:
        raise UnsupportedAuthMode(target.auth_type, provider=provider)
    return address


async def operational_state_migrated(
    app: Any, target: CredentialTarget, *, plugin: Any, provider: str
) -> CredentialOperationalState | None:
    service, account = _blob_address(app, target, plugin=plugin, provider=provider)
    try:
        return await app.state.credential_store.operational_state(service, account)
    except Exception as exc:
        raise CredentialStoreUnavailable("operational credential state", operation="read") from exc


async def require_operational_access_migrated(
    app: Any,
    target: CredentialTarget,
    *,
    plugin: Any,
    provider: str,
    requested: str,
) -> CredentialTarget:
    if target.auth_type != "api_key":
        return target
    state = await operational_state_migrated(app, target, plugin=plugin, provider=provider)
    if state is None or state.outcome == "needs_reauth":
        # OME-1198 pins resolve-time refusals to the selected Profile name and its bare legacy URL.
        # The target's own reauth URL is an authorize-time action and may carry `/api-key` or a
        # Connection id, so it is deliberately not reused here.
        raise TargetReauthRequired(
            provider,
            f"/v1/auth/{provider}/profiles/{requested}",
            requested=requested,
        )
    return target


async def begin_dispatch_migrated(
    app: Any, target: CredentialTarget, *, plugin: Any, provider: str
) -> DispatchObservation:
    service, account = _blob_address(app, target, plugin=plugin, provider=provider)
    try:
        observation = await app.state.credential_store.begin_dispatch(service, account)
    except Exception as exc:
        raise CredentialStoreUnavailable("dispatch observation") from exc
    if observation is None:
        raise TargetReauthRequired(
            provider,
            target.reauth_url or "",
            message="No credential stored",
        )
    return observation


async def record_dispatch_outcome_migrated(
    app: Any,
    target: CredentialTarget,
    observation: DispatchObservation,
    outcome: OperationalOutcome,
    detail: Any,
    *,
    plugin: Any,
) -> dict[str, Any] | None:
    updated = await app.state.credential_store.record_dispatch_outcome(observation, outcome)
    if outcome != "needs_reauth":
        return None

    body = detail if isinstance(detail, dict) else {"message": str(detail)}
    message = str(body.get("message", str(detail)))
    if updated:
        credential_name = str(target.credential_name)
        credential_strategy_cache(app).evict(credential_name)
        invalidate_session(plugin, credential_name)
    return {
        "code": body.get("code", "auth_required"),
        "message": message,
        "reauth_url": body.get("reauth_url", target.reauth_url),
    }


async def operational_availability_status_for(
    app: Any,
    connection: OAuthConnection | None,
    *,
    plugin: Any,
) -> AvailabilityStatus:
    lifecycle = availability_status_for(connection)
    if connection is None or lifecycle != "connected" or connection.auth_type != "api_key":
        return lifecycle
    address = credential_blob_address(app, plugin, connection.provider, connection)
    if address is None:
        # INVARIANT: missing strategy capability/configuration is not operational evidence that an
        # existing credential was rejected. Preserve the lifecycle projection; dispatch owns the
        # provider-specific unsupported-auth refusal.
        return lifecycle
    service, account = address
    try:
        state = await app.state.credential_store.operational_state(service, account)
    except Exception as exc:
        raise CredentialStoreUnavailable("operational credential state", operation="read") from exc
    if state is None or state.outcome == "needs_reauth":
        return "needs_reauth"
    if state.outcome == "insufficient_credits":
        return "error"
    return "connected"


def availability_status_for(connection: OAuthConnection | None) -> AvailabilityStatus:
    """Op 6 for a migrated pair: its effective Connection's status; none or revoked → absent."""
    if connection is None:
        return "not_connected"
    return _AVAILABILITY_FOR_STATUS.get(connection.status, "not_connected")
