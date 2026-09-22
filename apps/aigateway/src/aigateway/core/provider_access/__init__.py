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
from .backfill_apply import BackfillReport, all_account_ids, run_backfill
from .backfill_classify import BackfillContext, PairPlan, classify_account
from .connection_admin import ConnectionBackedCredentialAdmin
from .connection_backed import ConnectionBackedProviderAccess
from .connection_facade import FacadeTarget, facade_target, patch_facade, refresh_facade
from .connection_native import (
    credential_name_of,
    effective_pair_of,
    republish_effective_api_key,
    retire_effective,
)
from .connection_oauth import (
    MigratedFlow,
    begin_connection_oauth,
    complete_connection_oauth,
    fail_connection_oauth,
)
from .defaults import apply_defaults
from .pair_authority import PairAuthority, PairAuthorityConflict, PairAuthorityStore
from .ports import ProviderAccess, ProviderCredentialAdmin
from .profile_admin import (
    ProfileBackedCredentialAdmin,
    provider_credential_admin_for,
    summary_of,
)
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
    CredentialStoreUnavailable,
    CredentialSummary,
    CredentialTarget,
    ProviderAccessRefusal,
    ProviderUnknown,
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
    "BackfillContext",
    "BackfillReport",
    "PairPlan",
    "all_account_ids",
    "classify_account",
    "run_backfill",
    "DEFAULT_SELECTOR_NAME",
    "Authorization",
    "AvailabilityRow",
    "AvailabilityStatus",
    "ConnectionBackedCredentialAdmin",
    "ConnectionBackedProviderAccess",
    "CredentialStoreUnavailable",
    "CredentialSummary",
    "CredentialTarget",
    "FacadeTarget",
    "MigratedFlow",
    "PairAuthority",
    "PairAuthorityConflict",
    "PairAuthorityStore",
    "ProfileBackedCredentialAdmin",
    "ProfileBackedProviderAccess",
    "ProviderAccess",
    "ProviderAccessRefusal",
    "ProviderCredentialAdmin",
    "ProviderUnknown",
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
    "begin_connection_oauth",
    "complete_connection_oauth",
    "context_stamp",
    "contract_auth_mode",
    "credential_name_of",
    "effective_pair_of",
    "facade_target",
    "fail_connection_oauth",
    "invalidate_session",
    "legacy_target_parts",
    "mark_profile_error_fresh",
    "oauth_connection_store",
    "patch_facade",
    "profileless_auth_mode",
    "provider_access_for",
    "provider_credential_admin_for",
    "provider_name_of",
    "read_defaults",
    "refresh_facade",
    "reauth_url_for",
    "republish_effective_api_key",
    "retire_effective",
    "summary_of",
    "target_from_legacy",
]
