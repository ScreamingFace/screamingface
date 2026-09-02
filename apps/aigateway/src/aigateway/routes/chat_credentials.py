"""Credential-side helpers for /v1/chat/completions.

Everything between the incoming request and a dispatch-ready body lives here:
profile/connection resolution, credential-strategy lookup, profile-defaults
merging, and credential injection. Split out of routes/chat.py (OME-428
Phase 1) behind characterization tests; behavior is unchanged.
"""

from __future__ import annotations

from typing import Any, cast

from fastapi import HTTPException, Request

from ..core.credential_strategy_cache import credential_strategy_cache
from ..core.effective_credential import (
    DEFAULT_PROFILE_NAME,
    AmbiguousCredential,
    UnknownConnectionLabel,
    resolve_effective_credential,
)
from ..core.errors import AuthError, CredentialNotFoundError
from ..core.oauth.models import OAuthConnection
from ..core.oauth.store import OAuthConnectionStore, credential_key_for
from ..core.plugin_base import ProviderPluginBase, credential_strategy_from
from ..core.profile_index import ProfileIndexStore, ProfileTransitionConflict
from ..core.profile_models import (
    AuthMode,
    AuthType,
    Profile,
    ProfileDefaults,
    ProfileState,
    credential_name_for,
)


def auth_mode_for_target(
    profile: Profile | None,
    connection: OAuthConnection | None,
) -> AuthType:
    """Resolve the REAL auth mode for a resolved chat/contract target.

    INVARIANT: the auth mode is never caller-declared — it is derived solely from
    the stored connection/profile. A connection's own ``auth_type`` wins; a bare
    profile uses its ``auth_type``; with neither resolved, oauth is the safe
    default. Single source so chat dispatch and the detailed contract cannot
    disagree about which mode a profile uses.
    """
    if connection is not None:
        # WHY: tortoise-orm >=1.1.8 types CharField as `str`; the stored column is a bare
        # CharField, so narrowing it back to AuthType is ours to assert. `or "oauth"`
        # keeps the documented fallback for an empty stored value.
        return cast(AuthType, connection.auth_type or "oauth")
    if profile is not None:
        return profile.auth_type
    return "oauth"


def resolved_auth_mode(
    profile: Profile | None,
    connection: OAuthConnection | None,
    *,
    plugin: ProviderPluginBase,
) -> AuthMode:
    """Resolve the auth mode the PARAMETER CONTRACT and dispatch are matched against.

    Same resolution as ``auth_mode_for_target`` for anything with a stored
    credential, widened by one outcome: a provider that declares no credential
    type at all resolves to ``"none"`` instead of the ``"oauth"`` fiction (OME-636).

    # WHY this is a separate function rather than a wider return on
    # ``auth_mode_for_target``: that function also feeds credential-strategy
    # selection, which has no ``"none"`` branch and cannot grow one. Splitting
    # keeps the credential path structurally unable to receive a mode it could
    # not serve, instead of relying on a runtime check.
    # INVARIANT: ``"none"`` comes from the PROVIDER's declaration, never from an
    # absent profile. Gemini also permits a profile-less request, so triggering on
    # the missing profile would silently drop a credentialed provider into no-auth.
    """
    if connection is None and profile is None:
        profileless_mode = plugin.profileless_auth_mode()
        if profileless_mode is not None:
            return profileless_mode
        if plugin.available_auth_modes() == ("none",):
            return "none"
    return auth_mode_for_target(profile, connection)


_BUCKET_A_FIELDS = (
    "model",
    "max_tokens",
    "temperature",
    "timeout_seconds",
    "reasoning_effort",
)


def _has_system_message(body: dict[str, Any]) -> bool:
    return any(m.get("role") == "system" for m in body.get("messages", []))


def _should_apply_profile_default(plugin: Any, field: str) -> bool:
    checker = getattr(plugin, "should_apply_profile_default", None)
    return bool(checker(field)) if callable(checker) else True


def _allows_chatless_profile(plugin: Any) -> bool:
    checker = getattr(plugin, "allows_chatless_profile", None)
    return bool(checker()) if callable(checker) else False


def _invalidate_profile_session(plugin: Any, profile_name: str) -> None:
    invalidator = getattr(plugin, "invalidate_profile_session", None)
    if callable(invalidator):
        invalidator(profile_name)


def _oauth_connection_store(request: Request) -> OAuthConnectionStore:
    store = getattr(request.app.state, "oauth_connections", None)
    if isinstance(store, OAuthConnectionStore):
        return store
    store = OAuthConnectionStore()
    request.app.state.oauth_connections = store
    return store


async def _credential_target_for_chat(
    request: Request,
    *,
    account_id: str,
    provider: str,
    profile_name: str,
    plugin: Any,
) -> tuple[Profile | None, OAuthConnection | None, ProfileDefaults]:
    """Chat's HTTP contract over the SHARED effective-credential resolution.

    # INVARIANT (OME-1026): the resolution rules live in
    # ``core.effective_credential`` and are shared verbatim with ``GET /v1/models``
    # and ``GET /v1/model-parameters`` — this function only maps each structured
    # outcome onto the status codes and bodies chat has always produced.
    """
    idx: ProfileIndexStore = request.app.state.profile_index
    resolution = await resolve_effective_credential(
        account_id=account_id,
        provider=provider,
        profile_name=profile_name,
        profile_index=idx,
        connections=_oauth_connection_store(request),
    )
    if isinstance(resolution, AmbiguousCredential):
        selectable_labels = [
            label for label in resolution.valid_labels if label != DEFAULT_PROFILE_NAME
        ]
        raise HTTPException(
            status_code=409,
            detail={
                "code": "connection_ambiguous",
                "provider": provider,
                "message": (
                    "Multiple active connections exist. Remove extras until one remains, "
                    "or select a non-default connection by setting X-Profile to its label."
                ),
                "valid_labels": selectable_labels,
            },
        )
    if isinstance(resolution, UnknownConnectionLabel):
        raise HTTPException(
            status_code=404,
            detail={
                "code": "connection_not_found",
                "provider": provider,
                "requested_label": resolution.requested_label,
                "valid_labels": [
                    label for label in resolution.valid_labels if label != DEFAULT_PROFILE_NAME
                ],
            },
        )
    if resolution is None:
        if not _allows_chatless_profile(plugin):
            raise HTTPException(
                status_code=404,
                detail={
                    "code": "profile_not_found",
                    "provider": provider,
                    "name": profile_name,
                },
            )
        return None, None, ProfileDefaults()
    if resolution.connection is not None:
        return None, resolution.connection, ProfileDefaults()

    profile = resolution.profile
    assert profile is not None  # EffectiveCredential holds exactly one backing
    if profile.state == ProfileState.PENDING:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "profile_pending_auth",
                "provider": provider,
                "name": profile_name,
            },
        )
    if profile.state == ProfileState.ERROR:
        raise HTTPException(
            status_code=401,
            detail={
                "code": "auth_required",
                "provider": provider,
                "name": profile_name,
                "reauth_url": f"/v1/auth/{provider}/profiles/{profile_name}",
            },
        )
    return profile, None, profile.defaults


def _strategy_for_credential_target(
    request: Request,
    plugin: Any,
    provider: str,
    *,
    account_id: str,
    profile_name: str,
    profile: Profile | None,
    connection: OAuthConnection | None,
) -> tuple[Any, str | None, AuthType]:
    """Resolve (strategy, credential_name, auth_type) for the chat credential
    target, branching on the target's auth_type discriminator."""
    auth_type: AuthType
    if connection is not None:
        credential_name = credential_key_for(account_id, connection.id)
        auth_type = auth_mode_for_target(profile, connection)
    elif profile is not None:
        credential_name = credential_name_for(account_id, profile_name)
        auth_type = auth_mode_for_target(profile, connection)
    else:
        return None, None, "oauth"
    # Share ONE strategy instance per credential across concurrent requests so its
    # asyncio.Lock single-flights the OAuth refresh (SF-282). Building is only a
    # constructor call; the cache is evicted on every credential mutation.
    strategy = credential_strategy_cache(request.app).get_or_create(
        provider=provider,
        auth_type=auth_type,
        credential_name=credential_name,
        build=lambda: credential_strategy_from(
            plugin,
            credential_name,
            auth_type=auth_type,
            credential_store=request.app.state.credential_store,
            http_client_factory=getattr(request.app.state, f"{provider}_http_factory", None),
        ),
    )
    return strategy, credential_name, auth_type


def _reauth_url_for(
    provider: str,
    profile_name: str,
    auth_type: AuthType,
    *,
    connection_id: str | None = None,
) -> str:
    if connection_id is not None and auth_type == "api_key":
        # An api-key CONNECTION re-keys via its own replace route; never send the
        # user back to the legacy profile api-key endpoint, which would shadow
        # connections on chat (SF-291 review F3).
        return f"/v1/oauth/connections/{connection_id}/api-key"
    base = f"/v1/auth/{provider}/profiles/{profile_name}"
    return f"{base}/api-key" if auth_type == "api_key" else base


async def _mark_profile_error_fresh(
    request: Request,
    *,
    profile: Profile,
) -> None:
    """Mark only the authenticated credential version used by this request."""
    idx: ProfileIndexStore = request.app.state.profile_index
    try:
        await idx.mark_authenticated_error(
            profile.id,
            expected_auth_type=profile.auth_type,
            expected_last_refreshed_at=profile.last_refreshed_at,
        )
    except ProfileTransitionConflict:
        pass


def _apply_defaults(
    body: dict[str, Any], defaults: ProfileDefaults, plugin: Any
) -> tuple[dict[str, Any], frozenset[str]]:
    """Body wins per field. Fields the body omits get the profile default.

    Returns the merged body together with the CLASSIFIER REQUEST PATHS this call
    wrote, so a later parameter rejection can be attributed to the stored profile
    instead of to the request (OME-638).

    # INVARIANT: the reported paths are request paths, NOT ``ProfileDefaults``
    # field names — ``timeout_seconds`` is reported as ``timeout``, the name the
    # classifier sees. A set keyed by the field name could never match a rejected
    # path, so every profile fault would be silently blamed on the caller.
    # INVARIANT: a default only ever occupies a path the body omitted. That is what
    # makes the returned set a sound attribution rather than a guess, and it is why
    # the caller-supplied paths and these paths are always disjoint.
    # AIDEV-NOTE: the ``model`` default is unreachable from /v1/chat/completions —
    # the route rejects a body whose ``model`` is missing or not provider-prefixed
    # well before this runs, so ``"model" not in body`` is never true there. It
    # stays because this helper merges ProfileDefaults as a whole.
    """
    written: set[str] = set()
    if (
        defaults.system_prompt
        and not _has_system_message(body)
        and _should_apply_profile_default(plugin, "system_prompt")
    ):
        body.setdefault("messages", [])
        body["messages"] = [
            {"role": "system", "content": defaults.system_prompt},
            *body["messages"],
        ]
        written.add("messages")
    for field in _BUCKET_A_FIELDS:
        gateway_field = "timeout" if field == "timeout_seconds" else field
        if not _should_apply_profile_default(plugin, field):
            continue
        value = getattr(defaults, field)
        if value is not None and gateway_field not in body:
            body[gateway_field] = value
            written.add(gateway_field)
    return body, frozenset(written)


async def _inject_credentials(
    request: Request,
    *,
    plugin: Any,
    provider: str,
    account_id: str,
    profile_name: str,
    profile: Profile | None,
    connection: OAuthConnection | None,
    body: dict[str, Any],
) -> tuple[str | None, AuthType]:
    """Resolve the profile/connection credential strategy and inject auth
    into ``body``; returns ``(credential_name, auth_type)`` for later dispatch
    failure handling. Raises 401 (marking profile/connection errored) when
    stored credentials are unusable."""
    strategy, credential_name, auth_type = _strategy_for_credential_target(
        request,
        plugin,
        provider,
        account_id=account_id,
        profile_name=profile_name,
        profile=profile,
        connection=connection,
    )
    if strategy is None and credential_name is not None and auth_type == "api_key":
        # Never fall through to an unauthenticated dispatch when the target
        # says api_key but the provider has no API-key strategy (SF-244 F15).
        raise HTTPException(
            status_code=400,
            detail={"code": "api_key_not_supported", "provider": provider},
        )
    if strategy is not None:
        try:
            headers = await strategy.get_authorization_header()
        except CredentialNotFoundError as exc:
            if credential_name is not None:
                credential_strategy_cache(request.app).evict(credential_name)
            if connection is not None:
                await _oauth_connection_store(request).mark_error(connection, str(exc))
            raise HTTPException(
                status_code=401,
                detail={
                    "code": "auth_required",
                    "message": str(exc),
                    "reauth_url": _reauth_url_for(
                        provider,
                        profile_name,
                        auth_type,
                        connection_id=str(connection.id) if connection is not None else None,
                    ),
                },
            )
        except AuthError as exc:
            if credential_name is not None:
                credential_strategy_cache(request.app).evict(credential_name)
            if connection is not None:
                await _oauth_connection_store(request).mark_error(connection, str(exc))
                if credential_name is not None:
                    _invalidate_profile_session(plugin, credential_name)
            elif profile is not None:
                await _mark_profile_error_fresh(
                    request,
                    profile=profile,
                )
                if credential_name is not None:
                    _invalidate_profile_session(plugin, credential_name)
            raise HTTPException(
                status_code=401,
                detail={
                    "code": "auth_required",
                    "message": str(exc),
                    "reauth_url": _reauth_url_for(
                        provider,
                        profile_name,
                        auth_type,
                        connection_id=str(connection.id) if connection is not None else None,
                    ),
                },
            )
        auth_value = headers.pop("Authorization", None)
        if auth_value and auth_value.lower().startswith("bearer "):
            body["api_key"] = auth_value.split(" ", 1)[1]
        if headers:
            merged = dict(body.get("extra_headers") or {})
            merged.update(headers)
            body["extra_headers"] = merged
        if connection is not None:
            await _oauth_connection_store(request).touch_last_used(connection)

    return credential_name, auth_type
