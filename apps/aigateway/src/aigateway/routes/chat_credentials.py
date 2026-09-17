"""Compatibility shim: the credential-side names the routes import, now delegating to the
provider-access port (OME-1200, A1 of OME-1138).

Every refusal the port raises is rendered through the ONE edge table in
`provider_access_http.py`, which reproduces the status codes and detail bodies this module
raised itself at 17048f5d; the pure helpers are re-exported by identity. Behaviour is unchanged
— pinned by `test_chat_split_characterization.py`, `test_profile_resolution_characterisation.py`
and the shim suite.

# AIDEV-NOTE (A2, OME-1207): NO ROUTE IMPORTS THIS MODULE ANY MORE. `chat.py`,
# `chat_dispatch.py`, `model_parameters.py` and `model_admission.py` call the port directly, so
# this file is dead to production and lives on for exactly one reason: the A1 shim suite
# (`tests/unit/core/provider_access/test_provider_access_shims.py`) still imports these names,
# and a prior suite is not deleted to make a removal tidy.
# REMOVAL POINT: Stage E (OME-1209), together with the legacy vocabulary it speaks. Add no logic
# here — a behaviour that needs a home belongs in `core/provider_access`.
"""

from __future__ import annotations

from typing import Any

from fastapi import Request

from ..core.oauth.models import OAuthConnection
from ..core.oauth.store import OAuthConnectionStore
from ..core.plugin_base import ProviderPluginBase
from ..core.profile_models import AuthMode, AuthType, Profile, ProfileDefaults
from ..core.provider_access import (
    ResolvePolicy,
    Selector,
    apply_authorization,
    apply_defaults,
    auth_mode_for,
    auth_type_of,
    invalidate_session,
    legacy_target_parts,
    mark_profile_error_fresh,
    oauth_connection_store,
    provider_access_for,
    reauth_url_for,
    target_from_legacy,
)
from .provider_access_http import refusals_as_http

# Pure helpers: the same objects, under the names the routes and their tests bind.
auth_mode_for_target = auth_type_of
_apply_defaults = apply_defaults
_reauth_url_for = reauth_url_for
_invalidate_profile_session = invalidate_session


def resolved_auth_mode(
    profile: Profile | None,
    connection: OAuthConnection | None,
    *,
    plugin: ProviderPluginBase,
) -> AuthMode:
    """The auth mode the PARAMETER CONTRACT and dispatch are matched against (400 when the
    provider does not declare it). See `core.provider_access.auth_mode_for`."""
    stored = profile is not None or connection is not None
    with refusals_as_http():
        return auth_mode_for(auth_type_of(profile, connection) if stored else None, plugin=plugin)


def _oauth_connection_store(request: Request) -> OAuthConnectionStore:
    return oauth_connection_store(request.app)


async def _credential_target_for_chat(
    request: Request,
    *,
    account_id: str,
    provider: str,
    profile_name: str,
    plugin: Any,
    missing_target_ok: bool = False,
) -> tuple[Profile | None, OAuthConnection | None, ProfileDefaults]:
    """Today's `(profile, connection, defaults)` triple, resolved through the port.

    # WHY DATASHEET iff `missing_target_ok`: the only caller passing True is the model-parameter
    # contract, and it does so exactly when `profile_name == "default"` (OME-1167). The port
    # carries that rule itself (`ResolvePolicy.DATASHEET` admits the DEFAULT selector only), so
    # the two agree by construction.
    """
    policy = ResolvePolicy.DATASHEET if missing_target_ok else ResolvePolicy.DISPATCH
    with refusals_as_http():
        target = await provider_access_for(request.app).resolve(
            account_id,
            provider,
            Selector.from_header(profile_name),
            plugin=plugin,
            policy=policy,
        )
    return legacy_target_parts(target)


async def _mark_profile_error_fresh(request: Request, *, profile: Profile) -> None:
    """Mark only the authenticated credential version used by this request."""
    await mark_profile_error_fresh(request.app.state.profile_index, profile=profile)


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
    """Authorize the resolved target and seal `body`; returns `(credential_name, auth_type)`
    for later dispatch-failure handling. Raises 401 (marking the row) when the stored
    credential is unusable, 400 when the target says api_key but the provider has no API-key
    strategy."""
    target = target_from_legacy(
        account_id, provider, profile_name, profile=profile, connection=connection, plugin=plugin
    )
    with refusals_as_http():
        authorization = await provider_access_for(request.app).authorize(
            target, plugin=plugin, provider=provider
        )
    apply_authorization(body, authorization.headers)
    return authorization.credential_name, authorization.auth_type
