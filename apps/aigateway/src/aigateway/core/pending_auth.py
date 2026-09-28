from __future__ import annotations

import time
from dataclasses import dataclass


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
