"""The provider-access port (OME-1200, spec §3.3): what a route may ask about credentials.

# INVARIANT (hexagonal): this module names only core types. The Profile-backed implementation
# in `profile_backed.py` and any later Connection-backed one satisfy the same Protocol, and the
# contract suite under `tests/unit/core/provider_access/` runs unchanged over each.
# INVARIANT (spec §3.3): the operations below are exactly the approved ones, with the spec's
# parameter shapes — pinned by `test_provider_access_port_shape.py`. Later stages add
# implementations and callers; they do not re-cut the port.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from ..profile_models import AuthMode
from .selector import Selector
from .types import (
    Authorization,
    AvailabilityRow,
    CredentialSummary,
    CredentialTarget,
    RequestDefaults,
    ResolvePolicy,
)


@runtime_checkable
class ProviderAccess(Protocol):
    """The read interface plus the two writes the read path performs today (ops 1–6)."""

    async def defaults_for(
        self, account_id: str, provider: str, selector: Selector
    ) -> RequestDefaults | None:
        """Op 1 — stored request defaults, BEFORE any credential is resolved.

        # INVARIANT: never raises and never inspects the target's state — this read sits
        # ahead of the response-cache lookup, where a refusal would deny a cacheable request.
        # `None` means the store could not be read (bypass the cache); "no defaults" is an
        # empty `RequestDefaults`.
        """
        ...

    async def resolve(
        self,
        account_id: str,
        provider: str,
        selector: Selector,
        *,
        plugin: Any,
        policy: ResolvePolicy = ResolvePolicy.DISPATCH,
    ) -> CredentialTarget:
        """Op 2 — the one target this selector names, or a typed refusal — never another."""
        ...

    def auth_mode(self, target: CredentialTarget, plugin: Any) -> AuthMode:
        """Op 3 — the mode dispatch and the parameter contract are matched against.

        Provider-declared logic: raises `UnsupportedAuthMode` when the provider does not
        declare the target's mode. Pure; no store is read.
        """
        ...

    def contract_auth_mode(self, target: CredentialTarget, plugin: Any) -> AuthMode:
        """Op 3 — `auth_mode`, plus the keyless datasheet branch (OME-1167)."""
        ...

    async def authorize(
        self, target: CredentialTarget, *, plugin: Any, provider: str
    ) -> Authorization:
        """Op 4 — provider headers for one request; an unusable credential is marked, its
        cached strategy evicted, its session invalidated, and the call refused. A usable
        Connection credential is touched as used."""
        ...

    async def record_dispatch_failure(
        self, target: CredentialTarget, status: int, detail: Any, *, plugin: Any
    ) -> dict[str, Any] | None:
        """Op 5 — the store half of the dispatch-failure marker.

        The caller has already decided (through the plugin's status hook) that `status`
        marks an error; `status` travels with the call so a backing may record it. Returns
        the rewritten error detail for a target whose failure body gains a `reauth_url`, or
        `None` when the caller's detail stands as-is.
        """
        ...

    async def availability(self, account_id: str) -> tuple[AvailabilityRow, ...]:
        """Op 6 — the caller-scoped listing (D17): provider and status only.

        No secret read, no refresh, no mutation. `needs_reauth` is never emitted in the
        compatibility window.
        """
        ...


@runtime_checkable
class ProviderCredentialAdmin(Protocol):
    """The write interface behind the credential admin routes (ops 7–9; A3, declared at A1).

    # AIDEV-NOTE: window-compatible by construction — `legacy_name` exists only so the
    # Profile-backed body (`profile_admin.py`, the relocated `upsert_api_key_profile` /
    # `delete_profile_for_account`) can keep today's semantics; it disappears with the selector
    # sunset. `defaults` left op 8 at the D2 cutover (OME-1323, Stage C).
    """

    async def list(
        self, account_id: str, provider: str | None = None
    ) -> tuple[CredentialSummary, ...]:
        """Op 7 — masked summaries; never a secret."""
        ...

    async def set_api_key(
        self,
        account_id: str,
        provider: str,
        *,
        raw_api_key: str,
        legacy_name: str | None,
    ) -> CredentialSummary:
        """Op 8 — store an API key for the (account, provider) pair; `legacy_name or "default"`
        names the Profile in the window; a Profile's historical defaults are kept as stored and
        a new Profile gets none (D2: request parameters are the caller's); delete-wins and both
        conflict contracts (`WriteConflict`) are preserved."""
        ...

    async def delete(self, account_id: str, provider: str, *, legacy_name: str) -> None:
        """Op 9 — delete the named legacy target: index CAS first, blob second, one
        transaction."""
        ...
