"""Authorize and failure-marking of a label-path Connection target (OME-1200, ops 4–5).

Relocated from `routes/chat_credentials.py` (`_strategy_for_credential_target`,
`_inject_credentials`, `_reauth_url_for`, `_invalidate_profile_session`,
`_oauth_connection_store`) and the STORE half of
`routes/chat_dispatch.py::_dispatch_failure_response`. OME-1209 Stage E, E4a removed the
Profile-target branches: no resolve answers a Profile any more.

# INVARIANT: these are the ONLY writes the read interface performs — strategy-cache eviction,
# error marking, session invalidation, last-used touch. No HTTP code is chosen here.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ..auth_types import AuthType
from ..credential_strategy_cache import credential_strategy_cache
from ..errors import AuthError, CredentialNotFoundError, RefreshSuperseded
from ..oauth.models import OAuthConnection
from ..oauth.store import OAuthConnectionStore
from ..plugin_base import credential_strategy_from
from .refresh_guard import ConnectionRefreshOwner, guard_refresh
from .types import (
    Authorization,
    CredentialTarget,
    TargetReauthRequired,
    UnsupportedAuthMode,
    WriteConflict,
)
from .writer_floor import mark_error_checked

# FEATURE (OME-1209 Stage E, spec R2): every re-auth pointer names a live Connection route —
# the Profile routes are retired, so a pointer at one would send the caller to a 410.
CONNECTIONS_URL = "/v1/oauth/connections"


def reauth_url_for(auth_type: AuthType | None, *, connection_id: str | None = None) -> str:
    """Where to repair an unusable credential; `None` when the target is unknown (resolve time).

    # WHY the Connection id for an api-key target: re-keying THAT row replaces the credential chat
    # reads; creating a new row would leave the pair's effective Connection untouched.
    """
    if auth_type != "api_key":
        return CONNECTIONS_URL
    if connection_id is not None:
        return f"{CONNECTIONS_URL}/{connection_id}/api-key"
    return f"{CONNECTIONS_URL}/api-key"


def invalidate_session(plugin: Any, credential_name: str) -> None:
    invalidator = getattr(plugin, "invalidate_profile_session", None)
    if callable(invalidator):
        invalidator(credential_name)


def oauth_connection_store(app: Any) -> OAuthConnectionStore:
    store = getattr(app.state, "oauth_connections", None)
    if isinstance(store, OAuthConnectionStore):
        return store
    store = OAuthConnectionStore()
    app.state.oauth_connections = store
    return store


def _connection_of(target: CredentialTarget) -> OAuthConnection | None:
    """The Connection behind a label-path target; None for a targetless one."""
    backing = target._backing
    return backing if isinstance(backing, OAuthConnection) else None


def _strategy_for(app: Any, plugin: Any, provider: str, target: CredentialTarget) -> Any:
    name = str(target.credential_name)
    # Share ONE strategy instance per credential across concurrent requests so its asyncio.Lock
    # single-flights the OAuth refresh (SF-282). Building is only a constructor call; the cache
    # is evicted on every credential mutation.
    return credential_strategy_cache(app).get_or_create(
        provider=provider,
        auth_type=target.auth_type,
        credential_name=name,
        build=lambda: _guarded(
            credential_strategy_from(
                plugin,
                name,
                auth_type=target.auth_type,
                credential_store=app.state.credential_store,
                http_client_factory=getattr(app.state, f"{provider}_http_factory", None),
            ),
            target,
            provider=provider,
        ),
    )


def _guarded(strategy: Any, target: CredentialTarget, *, provider: str) -> Any:
    """A dispatch-triggered refresh publishes only while its owner and credential hold (§5.3)."""
    connection = _connection_of(target)
    if connection is None:
        return strategy
    owner = ConnectionRefreshOwner(str(connection.account_id), provider, connection.id)
    return guard_refresh(strategy, owner)


def _superseded(app: Any, target: CredentialTarget, *, plugin: Any, provider: str) -> WriteConflict:
    """A refresh whose credential moved under it: evict, mark nothing (§5.3)."""
    credential_name = str(target.credential_name)
    credential_strategy_cache(app).evict(credential_name)
    invalidate_session(plugin, credential_name)
    return WriteConflict("superseded", subject="connection", provider=provider)


def _reauth_url(target: CredentialTarget) -> str:
    # INVARIANT: every stored target is built with a reauth_url (see `targets`), so the
    # fallback is unreachable; it exists only to keep the return type honest.
    return target.reauth_url or ""


async def _refuse_unusable(
    app: Any,
    target: CredentialTarget,
    *,
    plugin: Any,
    provider: str,
    exc: AuthError | CredentialNotFoundError,
) -> TargetReauthRequired:
    """Today's two `except` branches of `_inject_credentials`, in their exact order of writes.

    # WHY the Connection is marked on either failure while only a REJECTED credential
    # (`AuthError`) invalidates its session: the legacy label-path rule, kept as it was.
    """
    credential_name = str(target.credential_name)
    credential_strategy_cache(app).evict(credential_name)
    connection = _connection_of(target)
    if connection is not None:
        await mark_error_checked(
            oauth_connection_store(app), connection, str(exc), observed=target._observed_pair
        )
        if isinstance(exc, AuthError):
            invalidate_session(plugin, credential_name)
    return TargetReauthRequired(provider, _reauth_url(target), message=str(exc))


async def authorize(
    app: Any, target: CredentialTarget, *, plugin: Any, provider: str
) -> Authorization:
    """Resolve the target's credential strategy and produce the request's provider headers.

    Refuses with `TargetReauthRequired` (marking the row) when the stored credential is
    unusable, and with `UnsupportedAuthMode` when the target says api_key but the provider has
    no API-key strategy (SF-244 F15) — never fall through to an unauthenticated dispatch.
    """
    if target.kind != "stored" or target.credential_name is None:
        return Authorization(headers={}, credential_name=None, auth_type="oauth")
    strategy = _strategy_for(app, plugin, provider, target)
    if strategy is None:
        if target.auth_type == "api_key":
            raise UnsupportedAuthMode("api_key", provider=provider)
        return Authorization(
            headers={}, credential_name=target.credential_name, auth_type=target.auth_type
        )
    try:
        raw_headers = await strategy.get_authorization_header()
    except RefreshSuperseded as exc:
        raise _superseded(app, target, plugin=plugin, provider=provider) from exc
    except (CredentialNotFoundError, AuthError) as exc:
        raise await _refuse_unusable(
            app, target, plugin=plugin, provider=provider, exc=exc
        ) from exc
    # INVARIANT (review F5): the result is proven to be a header mapping BEFORE any write, so a
    # strategy handing back garbage raises here and never leaves a false `last_used`.
    headers = dict(raw_headers)
    connection = _connection_of(target)
    if connection is not None:
        # WHY the touch precedes body sealing — an ACCEPTED parity exception (owner, 2026-09-14):
        # spec §3.3 op 4 keeps every storage side effect of the read path inside `authorize` and
        # makes `apply_authorization` a separate pure step, so the touch cannot follow sealing
        # without an extra impure operation on the port. At 17048f5d the touch followed the
        # in-place sealing. What remains observable: a body whose `extra_headers` is not a
        # mapping fails in the pure step AFTER the touch — the hardening layer rejects such a
        # caller body before this point, so only a malformed provider-produced body reaches it.
        # Pinned by the touch and malformed-result contract tests.
        await oauth_connection_store(app).touch_last_used(connection)
    return Authorization(
        headers=headers, credential_name=target.credential_name, auth_type=target.auth_type
    )


def apply_authorization(body: dict[str, Any], headers: Mapping[str, str]) -> None:
    """Seal `body` with the provider headers: a Bearer goes to `api_key`, the rest to
    `extra_headers`. Pure — the store-touching half is `authorize`."""
    remaining = dict(headers)
    auth_value = remaining.pop("Authorization", None)
    if auth_value and auth_value.lower().startswith("bearer "):
        body["api_key"] = auth_value.split(" ", 1)[1]
    if remaining:
        merged = dict(body.get("extra_headers") or {})
        merged.update(remaining)
        body["extra_headers"] = merged


async def record_dispatch_failure(
    app: Any, target: CredentialTarget, status: int, detail: Any, *, plugin: Any
) -> dict[str, Any] | None:
    """The store half of today's `_dispatch_failure_response` (spec §3.3 op 5).

    Drops the cached strategy so its (now bad) token is not reused and marks the Connection; the
    detail is never rewritten for a label-path target. The status gate
    (`should_mark_profile_error_on_dispatch_status`) stays with the caller; `status` travels
    with the call for a backing that records it — this one persists only the message, exactly
    as at 17048f5d.
    """
    if target.kind != "stored" or target.credential_name is None:
        return None
    credential_name = str(target.credential_name)
    credential_strategy_cache(app).evict(credential_name)
    body = detail if isinstance(detail, dict) else {"message": str(detail)}
    connection = _connection_of(target)
    if connection is None:
        return None
    await mark_error_checked(
        oauth_connection_store(app),
        connection,
        str(body.get("message", str(detail))),
        observed=target._observed_pair,
    )
    invalidate_session(plugin, credential_name)
    return None
