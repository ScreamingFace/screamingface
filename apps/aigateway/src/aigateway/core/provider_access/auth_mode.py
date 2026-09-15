"""Auth-mode derivation for a resolved target (OME-1200, spec §3.3 op 3).

Relocated from `routes/chat_credentials.py` (`auth_mode_for_target`, `resolved_auth_mode`,
`_available_auth_modes`, `_unsupported_auth_mode_error`) and `routes/model_parameters.py`
(`_contract_auth_mode`); behaviour unchanged. The shims re-export these under their old names.
"""

from __future__ import annotations

from typing import Any, cast

from ..oauth.models import OAuthConnection
from ..profile_models import AuthMode, AuthType, Profile
from .types import CredentialTarget, UnsupportedAuthMode


def auth_type_of(profile: Profile | None, connection: OAuthConnection | None) -> AuthType:
    """The PERSISTED credential type of a stored target.

    # INVARIANT: the auth type is never caller-declared — it is derived solely from the stored
    # connection/profile. A connection's own `auth_type` wins; a bare profile uses its
    # `auth_type`; with neither resolved, oauth is the safe default. Single source so chat
    # dispatch and the detailed contract cannot disagree about which mode a target uses.
    """
    if connection is not None:
        # WHY: tortoise-orm >=1.1.8 types CharField as `str`; the stored column is a bare
        # CharField, so narrowing it back to AuthType is ours to assert. `or "oauth"` keeps the
        # documented fallback for an empty stored value.
        return cast(AuthType, connection.auth_type or "oauth")
    if profile is not None:
        return profile.auth_type
    return "oauth"


def available_auth_modes(plugin: Any) -> tuple[AuthMode, ...]:
    modes = getattr(plugin, "available_auth_modes", None)
    if not callable(modes):
        return ("oauth",)
    return cast("tuple[AuthMode, ...]", tuple(cast(Any, modes)()))


def profileless_auth_mode(plugin: Any) -> AuthMode | None:
    hook = getattr(plugin, "profileless_auth_mode", None)
    return cast("AuthMode | None", hook()) if callable(hook) else None


def allows_chatless(plugin: Any) -> bool:
    checker = getattr(plugin, "allows_chatless_profile", None)
    return bool(checker()) if callable(checker) else False


def provider_name_of(plugin: Any) -> str | None:
    provider = getattr(plugin, "custom_llm_provider", "")
    return provider if isinstance(provider, str) and provider else None


def auth_mode_for(auth_type: AuthType | None, *, plugin: Any) -> AuthMode:
    """The RESOLVED auth mode; `auth_type is None` means "no stored target".

    Same resolution as `auth_type_of` for anything with a stored credential, widened by one
    outcome: a provider that declares no credential type at all resolves to `"none"` instead
    of the `"oauth"` fiction (OME-636).

    # INVARIANT: `"none"` comes from the PROVIDER's declaration, never from an absent target.
    # Gemini also permits a target-less request, so triggering on the missing target would
    # silently drop a credentialed provider into no-auth.
    """
    if auth_type is None:
        profileless = profileless_auth_mode(plugin)
        if profileless is not None:
            return profileless
        if available_auth_modes(plugin) == ("none",):
            return "none"
    mode: AuthMode = auth_type or "oauth"
    if mode not in available_auth_modes(plugin):
        raise UnsupportedAuthMode(mode, provider=provider_name_of(plugin))
    return mode


def auth_mode(target: CredentialTarget, *, plugin: Any) -> AuthMode:
    """The auth mode dispatch and the parameter contract are matched against."""
    return auth_mode_for(target.auth_type if target.kind == "stored" else None, plugin=plugin)


def contract_auth_mode(target: CredentialTarget, *, plugin: Any) -> AuthMode:
    """The auth mode the published contract is bound to, keyless case included.

    With any stored target — or a provider that permits a chatless profile — this is exactly
    `auth_mode`. The added branch (OME-1167) covers only the target-less answer that used to
    404: the datasheet is published under the provider's own declared preference — its
    profileless mode when it names one, else its FIRST declared auth mode.

    # WHY not `auth_mode` for that case: its target-less fallback is `"oauth"`, which refuses
    # an api-key-only provider — correct for a dispatch target, wrong for a datasheet that
    # merely needs A mode to be published under.
    """
    if target.kind != "stored" and not allows_chatless(plugin):
        keyless = profileless_auth_mode(plugin)
        if keyless is not None:
            return keyless
        return available_auth_modes(plugin)[0]
    return auth_mode(target, plugin=plugin)
