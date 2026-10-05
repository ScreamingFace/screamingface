"""The identity-keyed model-catalog cache (spec §6.3, §7).

FEATURE: model-catalog discovery. This is the piece that turns "one upstream call per request"
into "one upstream call per credential per TTL", and the piece that keeps an endpoint whose cache
keys come from unverified credentials from becoming a lever against aigateway. This module wraps
any ``CatalogSource`` (see ``catalog/port.py``) — it composes a port implementation rather than
defining one.

Five behaviours compose here, each closing a specific failure:

- **TTL** — bounds staleness.
- **Per-key single-flight** — a cold start under load must not stampede upstream.
- **Stale-on-error** — an upstream blip must not empty every client's model list.
- **Per-key failure backoff** — single-flight bounds *concurrent* misses; this bounds
  *sequential* ones.
- **Bounded LRU + an upstream semaphore** — distinct keys bypass single-flight entirely, so these
  are what bound memory and upstream load under a flood of distinct credentials.

AIDEV-NOTE: the stale-on-error discipline is deliberate — serve what is cached, refuse when cold,
never fail open. A refresh failure must not degrade into "this credential can address no models".
Detailed model-parameter contracts are caller-stateful and explicitly no-store, so this service
only retains their source for composition; those reads never enter this cache.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections import OrderedDict
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from screamingface_engine.catalog.port import (
    CatalogError,
    CatalogSource,
    Credential,
    ModelCatalog,
    ModelParameterSource,
)

logger = logging.getLogger(__name__)


@runtime_checkable
class CatalogService(Protocol):
    """What the REST route needs: a catalog, plus how long it may be cached downstream.

    WHY this is wider than :class:`~screamingface_engine.catalog.port.CatalogSource`:
    ``max_age_s`` is a property of *this cache's* entry, not of a catalog, so it has
    no meaning on a bare adapter. The route types against this so a test can inject a
    fake without subclassing the cache.
    """

    async def fetch(self, credential: Credential) -> ModelCatalog: ...

    def max_age_s(self, credential: Credential) -> int: ...


@dataclass(slots=True)
class _Entry:
    """A cached catalog plus the failure state observed while trying to refresh it.

    INVARIANT: an ``_Entry`` only ever exists for a key that has SUCCEEDED at least once. Failure
    state is therefore a field here rather than a map of its own, which is what makes "a cold
    failure caches nothing" (spec §7) true by construction instead of by convention: a flood of
    bogus credentials gets 401 upstream and leaves no state behind at all.
    """

    catalog: ModelCatalog
    fetched_at: float
    last_error: CatalogError | None = None
    last_error_at: float | None = None


@dataclass(slots=True)
class CacheCounters:
    """Plain counters, lifted into OpenMetrics by the app's metrics wiring.

    WHY not ``prometheus_client`` here: it would put a metrics dependency in the middle of the
    caching logic and make every cache test construct a registry.
    """

    hits: int = 0
    misses: int = 0
    stale_serves: int = 0
    errors: int = 0
    bulkhead_waits: int = 0


class CachedCatalog:
    """A ``CatalogSource`` decorator that caches per credential.

    Being a source itself is what lets the route depend on one type whether or not caching is in
    play, and lets every test here drive a counting in-memory fake instead of HTTP. Coalesces
    concurrent misses for the same credential into a single upstream fetch, serves a stale entry
    while refreshes are failing (up to ``stale_max_s``), and bounds upstream concurrency with a
    semaphore bulkhead.
    """

    def __init__(
        self,
        source: CatalogSource,
        *,
        parameter_source: ModelParameterSource | None = None,
        ttl_s: float = 300.0,
        stale_max_s: float = 3600.0,
        error_backoff_s: float = 30.0,
        max_entries: int = 256,
        upstream_concurrency: int = 8,
        bulkhead_wait_s: float = 15.0,
        clock: Callable[[], float] = time.monotonic,
        source_aclose: Callable[[], Awaitable[None]] | None = None,
    ) -> None:
        self._source = source
        self._parameter_source = parameter_source
        # WHY teardown lives here rather than on the source: the app holds the CACHE, so the cache
        # is what its ASGI shutdown hook can reach. Mirrors `Url4Executor(world_aclose=...)`.
        self._source_aclose = source_aclose
        self._ttl_s = ttl_s
        self._stale_max_s = stale_max_s
        self._error_backoff_s = error_backoff_s
        self._max_entries = max_entries
        self._clock = clock
        # WHY monotonic and injected: a wall clock can step backwards (NTP), which would make an
        # entry look arbitrarily fresh or stale; injecting it lets tests age entries without
        # sleeping.
        self._entries: OrderedDict[str, _Entry] = OrderedDict()
        self._inflight: dict[str, asyncio.Future[ModelCatalog]] = {}
        self._upstream_concurrency = upstream_concurrency
        self._bulkhead_wait_s = bulkhead_wait_s
        self._semaphore: asyncio.Semaphore | None = None
        self.counters = CacheCounters()

    @property
    def entry_count(self) -> int:
        return len(self._entries)

    def invalidate(self) -> None:
        """Expire every cached entry so the next fetch re-reads upstream (OME-880).

        Called when a model is dynamically admitted: the upstream catalog just
        changed, so serving the pre-admission body for the rest of the TTL would
        advertise a world the gateway no longer serves. In-flight fetches are
        deliberately untouched — one may still store a pre-admission body, which
        then ages out on the ordinary TTL (an accepted, rare staleness window).

        INVARIANT (review F5): expiry, never deletion. The bodies stay so the
        stale-on-error fallback keeps its material — an admission followed by a
        gateway blip a second later must degrade to a slightly-stale list, not to
        a fleet-wide 502 (the module's own "an upstream blip must not empty every
        client's model list" promise). `fetched_at` only ever moves BACKWARD here:
        moving it forward would extend an old entry's stale life past
        ``stale_max_s``.
        """
        now = self._clock()
        expired = now - self._ttl_s - 1.0
        for entry in self._entries.values():
            entry.fetched_at = min(entry.fetched_at, expired)

    async def aclose(self) -> None:
        """Release the upstream client, if this service owns one. Idempotent.

        INVARIANT: idempotent because ASGI shutdown may run alongside an explicit close in tests,
        and a second close must not raise.
        """
        aclose, self._source_aclose = self._source_aclose, None
        if aclose is not None:
            await aclose()

    @property
    def model_parameter_source(self) -> ModelParameterSource | None:
        """The uncached detail source sharing this service's owned client lifecycle."""

        return self._parameter_source

    def max_age_s(self, credential: Credential) -> int:
        """Seconds this credential's entry may still be considered fresh, floored at 0.

        Feeds ``Cache-Control: max-age`` (in ``rest/catalog.py``) so a downstream cache expires in
        step with this one rather than extending staleness past our own TTL; returns 0 for a cold
        (never-fetched) key.
        """
        entry = self._entries.get(credential.key)
        if entry is None:
            return 0
        remaining = self._ttl_s - (self._clock() - entry.fetched_at)
        return max(0, int(remaining))

    async def fetch(self, credential: Credential) -> ModelCatalog:
        """Return a fresh, in-flight-shared, or backoff-fallback catalog for ``credential``.

        Concurrent callers that miss on the same key await the same in-flight
        upstream fetch rather than issuing duplicate requests.
        """
        key = credential.key
        now = self._clock()
        fresh = self._fresh(key, now)
        if fresh is not None:
            return fresh
        inflight = self._inflight.get(key)
        if inflight is not None:
            # WHY shield: awaiting a shared Future directly means one waiter's cancellation
            # cancels the Future for EVERY waiter and the leader. Shielding isolates them.
            # AIDEV-NOTE: if the leader itself is cancelled the Future is cancelled in `finally`,
            # so waiters see CancelledError and the client retries — deliberate, since retrying
            # inside the cache risks an unbounded loop.
            return await asyncio.shield(inflight)
        return await self._miss(credential, key, now)

    def _fresh(self, key: str, now: float) -> ModelCatalog | None:
        """The entry for ``key`` if it is still inside the TTL, else ``None``.

        INVARIANT: this is reached BEFORE `fetch` ever awaits — no lock, no task switch — which is
        what makes a warm cache free, and is asserted by
        `test_a_fresh_hit_never_touches_upstream_even_concurrently`.
        """
        entry = self._entries.get(key)
        if entry is None or now - entry.fetched_at > self._ttl_s:
            return None
        self._entries.move_to_end(key)
        self.counters.hits += 1
        return entry.catalog

    async def _miss(self, credential: Credential, key: str, now: float) -> ModelCatalog:
        """No fresh entry and no flight in progress: back off, or lead a refresh."""
        entry = self._entries.get(key)
        if entry is not None and self._inside_backoff(entry, now):
            # WHY serve rather than refetch: a warm caller polling during an aigateway outage
            # would otherwise hit upstream on every single request.
            return self._stale_or_raise(entry, now, entry.last_error)
        self.counters.misses += 1
        return await self._refresh(credential, key)

    async def _refresh(self, credential: Credential, key: str) -> ModelCatalog:
        """Fetch upstream as the single flight for ``key``, settling every waiter identically.

        On failure, falls back to a stale entry via ``_on_failure`` when one is still within
        ``stale_max_s``; otherwise the error propagates to all waiters.
        """
        future: asyncio.Future[ModelCatalog] = asyncio.get_running_loop().create_future()
        self._inflight[key] = future
        try:
            catalog = await self._fetch_upstream(credential)
        except CatalogError as exc:
            self.counters.errors += 1
            fallback = self._on_failure(key, exc)
            if fallback is not None:
                # INVARIANT: the leader and its waiters agree. Returning stale to the leader while
                # raising at the waiters would make the outcome depend on arrival order.
                future.set_result(fallback)
                return fallback
            future.set_exception(exc)
            # WHY retrieve it here: nothing awaits this Future when there are no waiters, and an
            # unretrieved Future exception makes asyncio log a spurious warning at GC time. Same
            # trick as `Url4Executor.execute`'s early-aclose path.
            future.exception()
            raise
        else:
            self._store(key, catalog)
            future.set_result(catalog)
            return catalog
        finally:
            self._inflight.pop(key, None)
            if not future.done():
                # The leader was cancelled before settling; releasing waiters beats hanging them.
                future.cancel()

    async def _fetch_upstream(self, credential: Credential) -> ModelCatalog:
        """The one place upstream is called, behind the concurrency bulkhead (spec §7).

        INVARIANT: waiting for the bulkhead is bounded. The bulkhead exists to protect
        AIGATEWAY from a stampede; the wait bound is what protects THIS process. Cache
        keys derive from credentials screamingface-engine does not verify, so a flood of
        distinct bogus tokens bypasses single-flight entirely — every request takes the
        cold-miss path and queues behind an upstream call that may itself take the full
        request timeout. Unbounded, that queue is just latency with no ceiling and no way
        for a caller to tell a slow answer from a hung
        one; bounded, an overloaded catalog degrades to a prompt 503 the caller can retry.
        """
        if self._semaphore is None:
            # WHY: asyncio.Semaphore binds to the running loop, so it's built lazily
            # here on first use rather than in __init__, where no loop may be running.
            self._semaphore = asyncio.Semaphore(self._upstream_concurrency)
        if self._semaphore.locked():
            self.counters.bulkhead_waits += 1
        try:
            async with asyncio.timeout(self._bulkhead_wait_s):
                await self._semaphore.acquire()
        except TimeoutError as exc:
            self.counters.errors += 1
            raise CatalogError(
                f"catalog upstream is saturated — waited {self._bulkhead_wait_s}s for a slot"
            ) from exc
        try:
            return await self._source.fetch(credential)
        finally:
            self._semaphore.release()

    def _inside_backoff(self, entry: _Entry, now: float) -> bool:
        if entry.last_error_at is None or entry.last_error is None:
            return False
        return now - entry.last_error_at < self._error_backoff_s

    def _stale_or_raise(
        self, entry: _Entry, now: float, error: CatalogError | None
    ) -> ModelCatalog:
        """Serve the stale entry if within ``stale_max_s`` of its last fetch, else raise."""
        if now - entry.fetched_at <= self._stale_max_s:
            self.counters.stale_serves += 1
            logger.warning(
                "serving a stale model catalog (age %.0fs) — upstream refresh is failing",
                now - entry.fetched_at,
            )
            return entry.catalog
        if error is None:
            raise CatalogError("stale catalog exceeded its ceiling")
        # WHY a fresh exception and not `raise error`: `entry.last_error` is a STORED instance,
        # re-raised on every request inside the backoff window and shared across concurrent
        # tasks. Python appends a frame to `__traceback__` on each raise, so the object grows for
        # as long as the outage lasts and its traceback interleaves unrelated callers.
        raise type(error)(*error.args) from error

    def _on_failure(self, key: str, exc: CatalogError) -> ModelCatalog | None:
        """Record the failure against a KNOWN key and decide whether stale service applies.

        INVARIANT: an unknown key records nothing — see :class:`_Entry`. Backoff exists to protect
        established callers during an outage, not to allocate state for arbitrary tokens. Returns
        the stale catalog if the entry is still within ``stale_max_s``, else ``None`` so the caller
        propagates the error instead.
        """
        entry = self._entries.get(key)
        if entry is None:
            return None
        now = self._clock()
        entry.last_error = exc
        entry.last_error_at = now
        if now - entry.fetched_at <= self._stale_max_s:
            self.counters.stale_serves += 1
            logger.warning("model catalog refresh failed; serving cached entry (%s)", exc)
            return entry.catalog
        return None

    def _store(self, key: str, catalog: ModelCatalog) -> None:
        """Insert as most-recently-used and evict down to ``max_entries``."""
        self._entries[key] = _Entry(catalog=catalog, fetched_at=self._clock())
        self._entries.move_to_end(key)
        # INVARIANT: entry count never exceeds max_entries; least-recently-used evicted first.
        while len(self._entries) > self._max_entries:
            self._entries.popitem(last=False)


__all__ = ["CacheCounters", "CachedCatalog", "CatalogService"]
