"""The Profile-backed `ProviderAccess` (OME-1200): today's resolution, behind the port.

Relocated from `routes/chat_credentials.py` (`_credential_target_for_chat`,
`_active_oauth_connection_for_profile`, `_repair_api_key_only_connection_auth_type`) and
`routes/model_parameters.py::_context_identity`; behaviour unchanged.

# AIDEV-NOTE: this is the compatibility-window implementation (A1–A4). Stage B swaps the backing
# (D11: Connections + a slot, or a provider-account model) behind the same port; the contract
# suite is what proves the swap.
"""

from __future__ import annotations

from typing import Any

from ..oauth.models import OAuthConnection
from ..oauth.store import credential_key_for
from ..profile_index import ProfileIndexStore
from ..profile_models import AuthMode, Profile, ProfileDefaults, ProfileState, credential_name_for
from ._auth_mode import (
    allows_chatless,
    auth_mode,
    auth_type_of,
    available_auth_modes,
    contract_auth_mode,
    profileless_auth_mode,
)
from ._ports import ProviderAccess
from ._selector import Selector
from ._types import (
    Authorization,
    AvailabilityRow,
    CredentialTarget,
    RequestDefaults,
    ResolvePolicy,
    SelectorAmbiguous,
    SelectorUnknown,
    TargetKind,
    TargetMissing,
    TargetPending,
    TargetReauthRequired,
    WriteConflict,
)
from .profile_authorize import (
    authorize,
    backing_rows,
    oauth_connection_store,
    reauth_url_for,
    record_dispatch_failure,
)
from .profile_defaults import read_defaults


def context_stamp(
    account_id: str, profile: Profile | None, connection: OAuthConnection | None
) -> str:
    """Opaque, NON-secret digest input: account + selected target + its state.

    Folded by the contract endpoint into its one-way digests so the ids change when the
    selected target or its generation/state changes. Never echoed.
    # INVARIANT: byte-identical to `routes/model_parameters.py::_context_identity` at 17048f5d
    # (pinned by the shim suite) — a changed stamp silently re-keys every published contract.
    """
    if connection is not None:
        target = f"conn:{connection.id}:{connection.status}:{connection.last_refreshed_at or '-'}"
    elif profile is not None:
        target = f"prof:{profile.id}:{profile.state.value}:{profile.last_refreshed_at or '-'}"
    else:
        target = "anon"
    return f"acct:{account_id}|{target}"


def profile_target(
    account_id: str, provider: str, selector: Selector, profile: Profile
) -> CredentialTarget:
    auth_type = auth_type_of(profile, None)
    return CredentialTarget(
        kind="stored",
        auth_type=auth_type,
        credential_name=credential_name_for(account_id, selector.name),
        context_stamp=context_stamp(account_id, profile, None),
        reauth_url=reauth_url_for(provider, selector.name, auth_type),
        defaults=profile.defaults,
        _backing=profile,
    )


def connection_target(
    account_id: str, provider: str, selector: Selector, connection: OAuthConnection
) -> CredentialTarget:
    auth_type = auth_type_of(None, connection)
    return CredentialTarget(
        kind="stored",
        auth_type=auth_type,
        credential_name=credential_key_for(account_id, connection.id),
        context_stamp=context_stamp(account_id, None, connection),
        reauth_url=reauth_url_for(
            provider, selector.name, auth_type, connection_id=str(connection.id)
        ),
        defaults=RequestDefaults(),
        _backing=connection,
    )


def targetless(account_id: str, plugin: Any) -> CredentialTarget:
    kind: TargetKind = "ambient" if profileless_auth_mode(plugin) is not None else "none"
    return CredentialTarget(
        kind=kind,
        auth_type="oauth",
        credential_name=None,
        context_stamp=context_stamp(account_id, None, None),
        reauth_url=None,
        defaults=RequestDefaults(),
        _backing=None,
    )


class ProfileBackedProviderAccess:
    """Profiles first, active Connections when no Profile matches — exactly today's order."""

    def __init__(self, app: Any) -> None:
        # WHY the app, not the stores: `profile_index`, `credential_store`, `oauth_connections`
        # and `{provider}_http_factory` are read LAZILY at call time, exactly as the route
        # helpers did — tests monkeypatch them onto `app.state` after the app is built.
        self._app = app

    @property
    def _index(self) -> ProfileIndexStore:
        return self._app.state.profile_index

    async def defaults_for(
        self, account_id: str, provider: str, selector: Selector
    ) -> RequestDefaults | None:
        return await read_defaults(self._index, account_id, provider, selector)

    async def resolve(
        self,
        account_id: str,
        provider: str,
        selector: Selector,
        *,
        plugin: Any,
        policy: ResolvePolicy = ResolvePolicy.DISPATCH,
    ) -> CredentialTarget:
        profile = await self._index.get(account_id, provider, selector.name)
        if profile is None:
            return await self._resolve_without_profile(
                account_id, provider, selector, plugin=plugin, policy=policy
            )
        if profile.state == ProfileState.PENDING:
            raise TargetPending(provider, selector.name)
        if profile.state == ProfileState.ERROR:
            # INVARIANT (pinned by OME-1198): the resolve-time refusal names the BARE profile
            # URL, with no `/api-key` suffix even for an api-key profile — today's behaviour.
            raise TargetReauthRequired(
                provider, f"/v1/auth/{provider}/profiles/{selector.name}", requested=selector.name
            )
        return profile_target(account_id, provider, selector, profile)

    async def _resolve_without_profile(
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
            return connection_target(account_id, provider, selector, connection)
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
        auth_type = auth_type_of(None, connection)
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

    def auth_mode(self, target: CredentialTarget, plugin: Any) -> AuthMode:
        return auth_mode(target, plugin=plugin)

    def contract_auth_mode(self, target: CredentialTarget, plugin: Any) -> AuthMode:
        return contract_auth_mode(target, plugin=plugin)

    async def authorize(
        self, target: CredentialTarget, *, plugin: Any, provider: str
    ) -> Authorization:
        return await authorize(self._app, target, plugin=plugin, provider=provider)

    async def record_dispatch_failure(
        self, target: CredentialTarget, status: int, detail: Any, *, plugin: Any
    ) -> dict[str, Any] | None:
        return await record_dispatch_failure(self._app, target, status, detail, plugin=plugin)

    async def availability(self, account_id: str) -> tuple[AvailabilityRow, ...]:
        # AIDEV-NOTE (A3): the Profile-backed body — today's Engine aggregation
        # (authenticated > pending > error; Connection-only accounts `not_connected`) — lands
        # with its golden-equivalence tests at A3 (plan §3). Declared on the port at A1 so the
        # contract is complete; fail closed until then. No caller exists before A4.
        raise NotImplementedError("ProviderAccess.availability is implemented at A3 (OME-1138)")


def provider_access_for(app: Any) -> ProviderAccess:
    """The app's port implementation; created Profile-backed only when none is wired.

    # INVARIANT (review F2): whatever `app.state.provider_access` holds IS the port — a fake in a
    # test or a later backing must be what the shims call. The lazy branch exists for apps built
    # without `main.create_app` (scaffolds) and only fills an ABSENT slot.
    """
    access = getattr(app.state, "provider_access", None)
    if access is None:
        access = ProfileBackedProviderAccess(app)
        app.state.provider_access = access
    return access


# --- shim support: dies at A2 with `routes/chat_credentials.py` ---------------------------------


def legacy_target_parts(
    target: CredentialTarget,
) -> tuple[Profile | None, OAuthConnection | None, ProfileDefaults]:
    """Today's `(profile, connection, defaults)` triple, for the route call sites A1 leaves."""
    profile, connection = backing_rows(target)
    return profile, connection, target.defaults


def target_from_legacy(
    account_id: str,
    provider: str,
    profile_name: str,
    *,
    profile: Profile | None,
    connection: OAuthConnection | None,
    plugin: Any,
) -> CredentialTarget:
    """Rebuild the target a route was handed as a legacy triple (the `_inject_credentials` shim)."""
    selector = Selector.from_header(profile_name)
    if connection is not None:
        return connection_target(account_id, provider, selector, connection)
    if profile is not None:
        return profile_target(account_id, provider, selector, profile)
    return targetless(account_id, plugin)
