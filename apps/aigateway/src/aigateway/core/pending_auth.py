from __future__ import annotations

import time
from collections.abc import Collection
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    # WHY type-only: `provider_access` imports this module while it initialises.
    from .provider_access.pair_authority import PairAuthority


@dataclass
class PendingAuthEntry:
    account_id: str
    provider: str
    profile_name: str
    profile_id: str
    code_verifier: str
    redirect_uri: str
    connection_id: str | None = None
    requested_label: str | None = None
    compatibility_profile_name: str | None = None
    # WHY: the ownership generation this flow claimed at begin_pending (OME-307 Blocker 1).
    # The callback presents it to authenticate_pending so a superseded flow loses inside the
    # durable CAS. None for connection flows (which do not publish a pending profile).
    oauth_generation: int | None = None
    # WHY (OME-1208, D14): the pair-marker generation a MIGRATED pair's Profile-facade flow
    # claimed at start. The callback compare-and-sets the marker from it, so a newer start, a
    # delete or an API-key write in between rejects the stale callback at commit time. None for
    # every flow the legacy Profile (or a Connection flow) owns.
    pair_generation: int | None = None
    # WHY (OME-1497, G0 writer floor §5.3): the pair a flow the legacy Profile owns observed at
    # start. Begin never advances it; the callback's completion claims this generation, so an
    # ownership change in between makes the stale callback lose. None for migrated flows, which
    # are fenced by `pair_generation`.
    observed_pair: PairAuthority | None = None
    # WHY (OME-1209, E1b, spec R6): the `migrated` pair a native flow observed at start while its
    # effective row was unusable (`error`/`revoked`). The callback switches the effective row to
    # this flow's from that generation, so a newer start, a delete or a key write in between
    # makes the stale callback lose. None for every other flow.
    replaces_effective: PairAuthority | None = None


class PendingAuthTable:
    """In-memory CSRF-state store for pending OAuth flows. TTL-bounded."""

    def __init__(self, ttl_seconds: int = 600) -> None:
        self._ttl = ttl_seconds
        self._entries: dict[str, tuple[PendingAuthEntry, float]] = {}

    def put(self, state: str, entry: PendingAuthEntry) -> None:
        self._entries[state] = (entry, time.monotonic())

    def pop_for_profile(
        self,
        account_id: str,
        provider: str,
        profile_name: str,
        *,
        exclude_state: str | None = None,
    ) -> list[str]:
        """Remove pending entries for the same account/provider/profile.

        Returns the removed states so callers can tear down any state-scoped
        loopback listeners without disturbing unrelated in-flight profiles.

        INVARIANT (OME-307 Blocker 5): ``exclude_state`` protects the caller's OWN
        just-published flow. ``start_oauth`` publishes its pending profile FIRST, then calls
        this to supersede older flows — passing its fresh state as ``exclude_state`` so it does
        not evict itself while tearing down the flows it replaced.
        """
        removed: list[str] = []
        now = time.monotonic()
        for state, (entry, ts) in list(self._entries.items()):
            if state == exclude_state:
                continue
            expired = now - ts > self._ttl
            matches = (
                entry.account_id == account_id
                and entry.provider == provider
                and entry.profile_name == profile_name
            )
            if expired or matches:
                self._entries.pop(state, None)
            if matches and not expired:
                removed.append(state)
        return removed

    def pop_for_pair(
        self,
        account_id: str,
        provider: str,
        *,
        profile_names: Collection[str],
        connection_ids: Collection[str],
    ) -> list[str]:
        """Remove the pending flows of one pair's captured targets (D18 contract §5.2).

        # WHY scoped to the targets, not the whole pair: a flow for an unrelated new Connection
        # is not the credential a successor PUT or DELETE replaced. A stale callback loses its
        # pair fence anyway (G0), so this is cleanup, not correctness.
        """
        removed: list[str] = []
        for state, (entry, _ts) in list(self._entries.items()):
            if entry.account_id != account_id or entry.provider != provider:
                continue
            if entry.profile_name in profile_names or entry.connection_id in connection_ids:
                self._entries.pop(state, None)
                removed.append(state)
        return removed

    def pop(self, state: str) -> PendingAuthEntry | None:
        item = self._entries.pop(state, None)
        if item is None:
            return None
        entry, ts = item
        if time.monotonic() - ts > self._ttl:
            return None
        return entry

    def peek(self, state: str) -> PendingAuthEntry | None:
        """Look up an entry without removing it. Returns None if expired."""
        item = self._entries.get(state)
        if item is None:
            return None
        entry, ts = item
        if time.monotonic() - ts > self._ttl:
            self._entries.pop(state, None)
            return None
        return entry
