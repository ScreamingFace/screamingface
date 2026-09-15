"""Authorize and failure-marking of the Profile-backed implementation (OME-1200, ops 4–5).

Relocated from `routes/chat_credentials.py` (`_strategy_for_credential_target`,
`_inject_credentials`, `_reauth_url_for`, `_mark_profile_error_fresh`,
`_invalidate_profile_session`, `_oauth_connection_store`) and the STORE half of
`routes/chat_dispatch.py::_dispatch_failure_response`. Behaviour unchanged.

# INVARIANT: these are the ONLY writes the read interface performs — strategy-cache eviction,
# error marking, session invalidation, last-used touch. No HTTP code is chosen here.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ..credential_strategy_cache import credential_strategy_cache
from ..errors import AuthError, CredentialNotFoundError
from ..oauth.models import OAuthConnection
from ..oauth.store import OAuthConnectionStore
from ..plugin_base import credential_strategy_from
from ..profile_index import ProfileIndexStore, ProfileTransitionConflict
from ..profile_models import AuthType, Profile
from .types import Authorization, CredentialTarget, TargetReauthRequired, UnsupportedAuthMode


def reauth_url_for(
    provider: str,
    profile_name: str,
    auth_type: AuthType,
    *,
    connection_id: str | None = None,
) -> str:
    if connection_id is not None and auth_type == "api_key":
        # An api-key CONNECTION re-keys via its own replace route; never send the user back to
        # the legacy profile api-key endpoint, which would shadow connections on chat (SF-291
        # review F3).
        return f"/v1/oauth/connections/{connection_id}/api-key"
    base = f"/v1/auth/{provider}/profiles/{profile_name}"
    return f"{base}/api-key" if auth_type == "api_key" else base


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


async def mark_profile_error_fresh(index: ProfileIndexStore, *, profile: Profile) -> None:
    """Mark only the authenticated credential version used by this request."""
    try:
        await index.mark_authenticated_error(
            profile.id,
            expected_auth_type=profile.auth_type,
            expected_last_refreshed_at=profile.last_refreshed_at,
        )
    except ProfileTransitionConflict:
        pass


def backing_rows(target: CredentialTarget) -> tuple[Profile | None, OAuthConnection | None]:
    """The stored row behind a target, as today's `(profile, connection)` pair."""
    backing = target._backing
    if isinstance(backing, Profile):
        return backing, None
    if isinstance(backing, OAuthConnection):
        return None, backing
    return None, None


def _strategy_for(app: Any, plugin: Any, provider: str, target: CredentialTarget) -> Any:
    name = str(target.credential_name)
    # Share ONE strategy instance per credential across concurrent requests so its asyncio.Lock
    # single-flights the OAuth refresh (SF-282). Building is only a constructor call; the cache
    # is evicted on every credential mutation.
    return credential_strategy_cache(app).get_or_create(
        provider=provider,
        auth_type=target.auth_type,
        credential_name=name,
        build=lambda: credential_strategy_from(
            plugin,
            name,
            auth_type=target.auth_type,
            credential_store=app.state.credential_store,
            http_client_factory=getattr(app.state, f"{provider}_http_factory", None),
        ),
    )


def _reauth_url(target: CredentialTarget) -> str:
    # INVARIANT: every stored target is built with a reauth_url (see `profile_backed`), so the
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

    # WHY a MISSING credential marks no profile: the index row is fine and only the blob is
    # absent, so flipping the profile to ERROR would hide a recoverable state. A REJECTED
    # credential (`AuthError`) is the one that flips it.
    """
    credential_name = str(target.credential_name)
    credential_strategy_cache(app).evict(credential_name)
    profile, connection = backing_rows(target)
    if connection is not None:
        await oauth_connection_store(app).mark_error(connection, str(exc))
        if isinstance(exc, AuthError):
            invalidate_session(plugin, credential_name)
    elif profile is not None and isinstance(exc, AuthError):
        await mark_profile_error_fresh(app.state.profile_index, profile=profile)
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
    except (CredentialNotFoundError, AuthError) as exc:
        raise await _refuse_unusable(
            app, target, plugin=plugin, provider=provider, exc=exc
        ) from exc
    # INVARIANT (review F5): the result is proven to be a header mapping BEFORE any write, so a
    # strategy handing back garbage raises here and never leaves a false `last_used`.
    headers = dict(raw_headers)
    _profile, connection = backing_rows(target)
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

    Drops the cached strategy so its (now bad) token is not reused, marks the row, and — for
    a Profile target only — returns the detail rewritten with a `reauth_url`. The status gate
    (`should_mark_profile_error_on_dispatch_status`) stays with the caller; `status` travels
    with the call for a backing that records it — the Profile-backed marker persists only the
    message, exactly as at 17048f5d.
    """
    if target.kind != "stored" or target.credential_name is None:
        return None
    credential_name = str(target.credential_name)
    credential_strategy_cache(app).evict(credential_name)
    body = detail if isinstance(detail, dict) else {"message": str(detail)}
    profile, connection = backing_rows(target)
    if connection is not None:
        await oauth_connection_store(app).mark_error(
            connection, str(body.get("message", str(detail)))
        )
        invalidate_session(plugin, credential_name)
        return None
    if profile is None:
        return None
    await mark_profile_error_fresh(app.state.profile_index, profile=profile)
    invalidate_session(plugin, credential_name)
    return {
        "code": body.get("code", "auth_required"),
        "message": body.get("message", str(detail)),
        "reauth_url": body.get("reauth_url", target.reauth_url),
    }
