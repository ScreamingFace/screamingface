"""The provider-access boundary (OME-1200, A1 of OME-1138): the ONE place a route asks
"which credential, and may I use it?".

# FEATURE: OME-1138 — deprecate Profiles and converge on Connections, adapter-first. Routes
# depend on this port; the Profile-backed implementation below is the compatibility-window
# adapter, swapped at Stage B (D11) without touching a route.
# INVARIANT (hexagonal): core defines the port; nothing in this package imports a route or a
# plugin. THIS module is the public surface — import from here, never from a half.
"""

from __future__ import annotations

from .auth_mode import (
    allows_chatless,
    auth_mode,
    auth_mode_for,
    auth_type_of,
    available_auth_modes,
    contract_auth_mode,
    profileless_auth_mode,
    provider_name_of,
)
from .defaults import apply_defaults
from .ports import ProviderAccess, ProviderCredentialAdmin
from .profile_authorize import (
    apply_authorization,
    invalidate_session,
    mark_profile_error_fresh,
    oauth_connection_store,
    reauth_url_for,
)
from .profile_backed import (
    ProfileBackedProviderAccess,
    context_stamp,
    legacy_target_parts,
    provider_access_for,
    target_from_legacy,
)
from .profile_defaults import read_defaults
from .selector import DEFAULT_SELECTOR_NAME, Selector, SelectorPolicy
from .types import (
    Authorization,
    AvailabilityRow,
    AvailabilityStatus,
    CredentialSummary,
    CredentialTarget,
    ProviderAccessRefusal,
    RequestDefaults,
    ResolvePolicy,
    SelectorAmbiguous,
    SelectorUnknown,
    SelectorUnsupported,
    TargetKind,
    TargetMissing,
    TargetPending,
    TargetReauthRequired,
    UnsupportedAuthMode,
    WriteConflict,
)

__all__ = [
    "DEFAULT_SELECTOR_NAME",
    "Authorization",
    "AvailabilityRow",
    "AvailabilityStatus",
    "CredentialSummary",
    "CredentialTarget",
    "ProfileBackedProviderAccess",
    "ProviderAccess",
    "ProviderAccessRefusal",
    "ProviderCredentialAdmin",
    "RequestDefaults",
    "ResolvePolicy",
    "Selector",
    "SelectorAmbiguous",
    "SelectorPolicy",
    "SelectorUnknown",
    "SelectorUnsupported",
    "TargetKind",
    "TargetMissing",
    "TargetPending",
    "TargetReauthRequired",
    "UnsupportedAuthMode",
    "WriteConflict",
    "allows_chatless",
    "apply_authorization",
    "apply_defaults",
    "auth_mode",
    "auth_mode_for",
    "auth_type_of",
    "available_auth_modes",
    "context_stamp",
    "contract_auth_mode",
    "invalidate_session",
    "legacy_target_parts",
    "mark_profile_error_fresh",
    "oauth_connection_store",
    "profileless_auth_mode",
    "provider_access_for",
    "provider_name_of",
    "read_defaults",
    "reauth_url_for",
    "target_from_legacy",
]
