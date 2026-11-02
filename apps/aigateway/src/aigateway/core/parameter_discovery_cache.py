"""OME-479 §5.3 — bounded in-memory public-observation cache.

FEATURE: safe dynamic observation cache. Public discovery evidence (§5.2) may be
shared across accounts because it depends only on the PUBLIC source, never on a
caller's credentials. This cache is keyed by ``source + canonical model/backend``
and additionally guarded by the source ``revision`` so a projection-schema bump
never serves evidence gathered under the old shape.

INVARIANT (§5.3): this cache never fabricates fresh support. A cold failure or an
expired-past-stale entry yields a DEGRADED outcome (value ``None``) that a provider
maps to ``unknown`` — it is honest absence, not invented capability.

INVARIANT: single-flight per key — concurrent callers for the same key coalesce
onto ONE refresh; the losers reuse the just-stored fresh entry. No durable store,
no scheduler, no new dependency (§5.3, §11): a process-lifetime ``OrderedDict``.
"""

from __future__ import annotations

import asyncio
import time
from collections import OrderedDict
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Literal, Protocol

from .parameter_discovery import DiscoveryError

# fresh: within TTL for the requested revision.
# stale: TTL expired but within the bounded stale-on-error window, same revision,
#        and only served when a refresh actually FAILED (never pre-emptively).
# degraded: no trustworthy value — the provider must map this to ``unknown``.
Freshness = Literal["fresh", "stale", "degraded"]


class MonotonicClock(Protocol):
    """Injected time seam — a real monotonic clock in prod, a fake in tests.

    # WHY: TTL math must not depend on wall-clock jumps, and tests must drive time
    # deterministically. The cache never calls ``time`` directly.
    """

    def now(self) -> float: ...


class SystemMonotonicClock:
    """The production ``MonotonicClock``: the process's own monotonic timer.

    # WHY monotonic and not wall time: an NTP correction or a DST change must not
    # expire — or resurrect — cached evidence.
    """

    def now(self) -> float:
        return time.monotonic()


@dataclass(frozen=True)
class CacheLimits:
    """Freshness/size bounds for the observation cache (§5.3)."""

    ttl_s: float
    stale_ttl_s: float
    max_entries: int
    # Zero preserves eager retries for direct callers that do not opt in.
    failure_ttl_s: float = 0.0


@dataclass(frozen=True)
class CacheOutcome:
    """The result of a lookup: a value (or ``None``) plus its trust label."""

    value: Any | None
    freshness: Freshness


@dataclass(frozen=True)
class _Entry:
    value: Any
    stored_at: float
    revision: str


@dataclass(frozen=True)
class _FailureEntry:
    failed_at: float
    revision: str


@dataclass
class _InFlight:
    """Coordination state for the callers currently inside ``get_or_refresh`` for one key.

    # WHY: this is state about CALLERS, not about entries. Tying its cleanup to the
    # entry table (drop the lock when the key is evicted) leaks on every path that
    # returns without storing — which is every failure path — and bounds the lock
    # table by "distinct keys ever seen" instead of by concurrency. Owning it here,
    # created by the first caller in and dropped by the last caller out, makes the
    # bound structural: coordination state cannot outnumber in-flight callers.
    """

    lock: asyncio.Lock
    waiters: int = 0
    # Completed refresh attempts for this key within THIS batch. A caller reads it
    # before queuing; if it moved while the caller waited, some other caller already
    # paid for an attempt.
    attempts: int = 0
    # The exact outcome of the most recent completed attempt in this batch.
    # A capacity eviction may remove a successful entry before queued losers run,
    # so both successful and failed outcomes need this non-durable handoff.
    result: tuple[str, CacheOutcome] | None = None


class ObservationCache:
    """A bounded, single-flight, TTL+stale in-memory cache for public evidence.

    # AIDEV-NOTE: intentionally process-local and unshared — discovery evidence is
    # public and cheap to re-fetch, so a durable/distributed store would add risk
    # (stale secrets, migrations) for no benefit (§5.3 forbids it).
    """

    def __init__(self, *, clock: MonotonicClock, limits: CacheLimits) -> None:
        self._clock = clock
        self._limits = limits
        # OrderedDict doubles as the LRU: most-recently-used is moved to the end,
        # eviction pops from the front.
        self._entries: OrderedDict[str, _Entry] = OrderedDict()
        # Negative entries carry no evidence, only a bounded retry-suppression window.
        self._failures: OrderedDict[str, _FailureEntry] = OrderedDict()
        # INVARIANT: positive and negative records share ONE advertised capacity.
        # This index owns cross-table recency; the payload maps remain separate so
        # a failure can coexist with the last-good evidence it may serve as stale.
        self._record_lru: OrderedDict[tuple[str, str], None] = OrderedDict()
        # Live only while callers are inside get_or_refresh for the key (see _InFlight).
        self._inflight: dict[str, _InFlight] = {}

    @property
    def limits(self) -> CacheLimits:
        """The bounds this cache enforces.

        # WHY exposed: a consumer that publishes an expiry window must derive it
        # from the SAME TTL the cache expires on. Passing the TTL separately
        # alongside the cache is a two-source-of-truth seam whose drift is
        # invisible — the contract would advertise a window the cache does not
        # honour.
        """
        return self._limits

    @property
    def inflight_key_count(self) -> int:
        """Keys with live coordination state — i.e. callers currently inside the cache.

        # INVARIANT: zero whenever no caller is inside ``get_or_refresh``. Exposed
        # because "the cache's memory is bounded" is an operational property that
        # must be assertable without reaching into internals.
        """
        return len(self._inflight)

    async def get_or_refresh(
        self,
        key: str,
        *,
        revision: str,
        refresh: Callable[[], Awaitable[Any]],
    ) -> CacheOutcome:
        """Return fresh cached evidence, or refresh once, degrading honestly.

        # INVARIANT: a value is returned ONLY when it is trustworthy for THIS
        # ``revision``. A stale entry from a different revision is never served.
        # INVARIANT: one upstream attempt per batch of contemporaneous callers,
        # whether that attempt succeeds or fails.
        """
        state = self._enter(key)
        # Read BEFORE queuing: if this moves while we wait, someone else attempted.
        observed = state.attempts
        try:
            async with state.lock:
                entry = self._entries.get(key)
                if entry is not None and self._is_fresh(entry, revision):
                    self._entries.move_to_end(key)
                    self._touch_record("entry", key)
                    return CacheOutcome(value=entry.value, freshness="fresh")

                # A single-flight LOSER reuses the winner's exact outcome before
                # consulting durable negative cache. Capacity eviction may have
                # removed the stale payload after the winner captured it, so
                # recomputing from current records could downgrade stale to degraded.
                if (
                    state.result is not None
                    and state.result[0] == revision
                    and state.attempts > observed
                ):
                    return state.result[1]

                failure = self._failures.get(key)
                if failure is not None:
                    age = self._clock.now() - failure.failed_at
                    if (
                        failure.revision == revision
                        and self._limits.failure_ttl_s > 0
                        and age <= self._limits.failure_ttl_s
                    ):
                        self._failures.move_to_end(key)
                        # INVARIANT: recompute trust from the current clock; suppressing
                        # a retry must never extend a last-good value's stale window.
                        outcome = self._on_refresh_error(entry, revision)
                        if outcome.value is not None and self._entries.get(key) is entry:
                            self._touch_record("entry", key)
                        self._touch_record("failure", key)
                        return outcome
                    del self._failures[key]
                    self._record_lru.pop(("failure", key), None)

                # Not fresh (cold, expired, or revision changed) → attempt one refresh.
                try:
                    value = await refresh()
                except DiscoveryError:
                    state.attempts += 1
                    outcome = self._on_refresh_error(entry, revision)
                    state.result = (revision, outcome)
                    # Another key may have evicted this stale entry while refresh
                    # awaited I/O. Never resurrect only its LRU token as a ghost.
                    if outcome.value is not None and self._entries.get(key) is entry:
                        self._touch_record("entry", key)
                    self._store_failure(key, revision)
                    return outcome

                state.attempts += 1
                outcome = CacheOutcome(value=value, freshness="fresh")
                state.result = (revision, outcome)
                self._failures.pop(key, None)
                self._record_lru.pop(("failure", key), None)
                self._store(
                    key, _Entry(value=value, stored_at=self._clock.now(), revision=revision)
                )
                return outcome
        finally:
            self._leave(key)

    def peek(self, key: str, *, revision: str) -> Any | None:
        """The last-good value for ``key`` without refreshing, or ``None`` (OME-1807).

        # INVARIANT: a pure read — no refresh, no single-flight entry, no LRU touch, no failure
        # record. A caller on a hot path (chat) can never cause a dial through it.
        # WHY the stale window bounds it: that is the oldest value ``get_or_refresh`` would
        # ever serve; past it the evidence is gone, and ``None`` (unknown) is the honest answer.
        """
        entry = self._entries.get(key)
        if entry is None or entry.revision != revision:
            return None
        if self._clock.now() - entry.stored_at > self._limits.ttl_s + self._limits.stale_ttl_s:
            return None
        return entry.value

    def _enter(self, key: str) -> _InFlight:
        # AIDEV-NOTE: _enter/_leave are deliberately SYNCHRONOUS. With no await
        # between the lookup and the counter change, the event loop cannot interleave
        # another caller here, so the refcount needs no lock of its own.
        state = self._inflight.get(key)
        if state is None:
            state = _InFlight(lock=asyncio.Lock())
            self._inflight[key] = state
        state.waiters += 1
        return state

    def _leave(self, key: str) -> None:
        state = self._inflight.get(key)
        if state is None:  # pragma: no cover - _enter always precedes _leave
            return
        state.waiters -= 1
        if state.waiters <= 0:
            # Last caller out drops the batch — including its failure record, so the
            # next arrival gets a real attempt instead of a pinned outage verdict.
            del self._inflight[key]

    def _is_fresh(self, entry: _Entry, revision: str) -> bool:
        if entry.revision != revision:
            return False
        return (self._clock.now() - entry.stored_at) <= self._limits.ttl_s

    def _on_refresh_error(self, entry: _Entry | None, revision: str) -> CacheOutcome:
        # WHY: fail-soft to the LAST GOOD value only within a bounded window and only
        # for the SAME revision; otherwise fail-closed to degraded rather than invent.
        if entry is not None and entry.revision == revision:
            age = self._clock.now() - entry.stored_at
            if age <= self._limits.ttl_s + self._limits.stale_ttl_s:
                return CacheOutcome(value=entry.value, freshness="stale")
        return CacheOutcome(value=None, freshness="degraded")

    def _store(self, key: str, entry: _Entry) -> None:
        # Eviction touches the entry table ONLY: coordination state has its own
        # lifecycle (_enter/_leave), so there is nothing to reconcile here.
        self._entries[key] = entry
        self._entries.move_to_end(key)
        self._touch_record("entry", key)
        self._trim_records()

    def _store_failure(self, key: str, revision: str) -> None:
        if self._limits.failure_ttl_s <= 0:
            self._failures.pop(key, None)
            self._record_lru.pop(("failure", key), None)
            return
        self._failures[key] = _FailureEntry(
            failed_at=self._clock.now(),
            revision=revision,
        )
        self._failures.move_to_end(key)
        self._touch_record("failure", key)
        self._trim_records()

    def _touch_record(self, kind: str, key: str) -> None:
        record = (kind, key)
        self._record_lru[record] = None
        self._record_lru.move_to_end(record)

    def _trim_records(self) -> None:
        while len(self._record_lru) > self._limits.max_entries:
            (kind, key), _ = self._record_lru.popitem(last=False)
            if kind == "entry":
                self._entries.pop(key, None)
            else:
                self._failures.pop(key, None)
