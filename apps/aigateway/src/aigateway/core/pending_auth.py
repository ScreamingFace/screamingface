from __future__ import annotations

import time
from collections.abc import Collection
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    # WHY type-only: the pair views are annotations here; nothing needs them at runtime.
    from .provider_access.pair_authority import PairAuthority


@dataclass
class PendingAuthEntry:
    account_id: str
    provider: str
    profile_name: str
    code_verifier: str
    redirect_uri: str
    # INVARIANT (OME-1209 E3b): every pending flow is a native Connection flow — the start
    # (`POST /v1/oauth/connections`) creates the pending row before it publishes this entry.
    connection_id: str
    requested_label: str | None = None
    # WHY (OME-1497, G0 writer floor §5.3): the pair the start claimed (`claim_native_write`);
    # the callback's completion claims this generation, so an ownership change in between makes
    # the stale callback lose. None when the floor does not fence the pair.
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

    def pop_for_pair(
        self,
        account_id: str,
        provider: str,
        *,
        connection_ids: Collection[str],
    ) -> list[str]:
        """Remove the pending flows of one pair's captured Connections (D18 contract §5.2).

        # WHY scoped to the targets, not the whole pair: a flow for an unrelated new Connection
        # is not the credential a successor PUT or DELETE replaced. A stale callback loses its
        # pair fence anyway (G0), so this is cleanup, not correctness.
        """
        removed: list[str] = []
        for state, (entry, _ts) in list(self._entries.items()):
            if entry.account_id != account_id or entry.provider != provider:
                continue
            if entry.connection_id in connection_ids:
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
