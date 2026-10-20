"""The provider-access boundary (OME-1200, A1 of OME-1138): the ONE place a route asks
"which credential, and may I use it?".

# FEATURE: OME-1138 — deprecate Profiles and converge on Connections, adapter-first. Routes
# depend on this port; the Connection-backed implementation is its only adapter since OME-1209
# Stage E, E4a deleted the Profile-backed one without touching a route.
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
from .connection_backed import (
    ConnectionBackedProviderAccess,
    operational_access_for,
    provider_access_for,
)
from .connection_native import (
    claim_for_connection,
    claim_native_write,
    credential_has_other_owner,
    credential_name_of,
    effective_pair_of,
    effective_to_replace,
    lock_lower_addressers,
    replace_effective,
    replaced_label,
    republish_effective_api_key,
    retire_effective,
    retire_replaced,
    take_over_effective,
)
from .pair_admin import (
    CredentialState,
    PairConflict,
    PairConflictKind,
    PairCredential,
    PairDisposition,
    PairInventory,
    classify_pair,
    pair_inventory,
    store_reads,
)
from .pair_admin_writes import PairMutation, delete_pair, set_pair_api_key
from .pair_authority import (
    MigrationState,
    PairAuthority,
    PairAuthorityConflict,
    PairAuthorityStore,
)
from .ports import ProviderAccess, ProviderOperationalAccess
from .profile_authorize import (
    apply_authorization,
    invalidate_session,
    oauth_connection_store,
    reauth_url_for,
)
from .refresh_guard import ConnectionRefreshOwner, guard_refresh
from .selector import DEFAULT_SELECTOR_NAME, Selector, SelectorPolicy
from .targets import context_stamp
from .types import (
    Authorization,
    AvailabilityRow,
    AvailabilityStatus,
    CredentialAuthorityUnavailable,
    CredentialStoreReadUnavailable,
    CredentialStoreUnavailable,
    CredentialTarget,
    PairNotManageable,
    ProviderAccessRefusal,
    ProviderUnknown,
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
from .writer_floor import (
    bootstrap_under_the_floor,
    claim_observed,
    claim_pair,
    fences_writer,
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
    "ConnectionBackedProviderAccess",
    "ConnectionRefreshOwner",
    "CredentialAuthorityUnavailable",
    "CredentialState",
    "CredentialStoreReadUnavailable",
    "CredentialStoreUnavailable",
    "MigrationState",
    "CredentialTarget",
    "PairAuthority",
    "PairAuthorityConflict",
    "PairConflict",
    "PairConflictKind",
    "PairCredential",
    "PairDisposition",
    "PairInventory",
    "PairMutation",
    "PairNotManageable",
    "PairAuthorityStore",
    "ProviderAccess",
    "ProviderAccessRefusal",
    "ProviderOperationalAccess",
    "ProviderUnknown",
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
    "auth_mode",
    "auth_mode_for",
    "auth_type_of",
    "available_auth_modes",
    "bootstrap_under_the_floor",
    "claim_for_connection",
    "claim_native_write",
    "claim_observed",
    "claim_pair",
    "classify_pair",
    "delete_pair",
    "set_pair_api_key",
    "context_stamp",
    "contract_auth_mode",
    "credential_has_other_owner",
    "lock_lower_addressers",
    "credential_name_of",
    "effective_pair_of",
    "effective_to_replace",
    "fences_writer",
    "guard_refresh",
    "invalidate_session",
    "oauth_connection_store",
    "operational_access_for",
    "pair_inventory",
    "profileless_auth_mode",
    "provider_access_for",
    "provider_name_of",
    "reauth_url_for",
    "replace_effective",
    "replaced_label",
    "republish_effective_api_key",
    "retire_effective",
    "retire_replaced",
    "store_reads",
    "take_over_effective",
]
