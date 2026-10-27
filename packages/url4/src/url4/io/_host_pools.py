"""The guarded transport's per-host connection pools, bounded and closed safely (OME-1719).

:class:`~url4.io._guarded_transport.GuardedTransport` keeps one inner transport per host name
(so a TLS connection made with one name's SNI is never reused for another), and the owned
adapter lives as long as its ``Client``/``Url4Node``. Without a bound, every new host name a
long-lived process fetches from would keep a pool — and its idle connections — forever.

INVARIANT: at most ``limit`` pools are RETAINED (reachable by host name). Past it the least
recently used one is evicted from the map at once, and closed as soon as it has no request in
flight — immediately when idle, else when its last open response closes.
INVARIANT: a pool is closed at most once, and never while a request on it is in flight (an
adapter shutdown excepted: :meth:`HostPools.aclose` closes everything).
INVARIANT: an evicted pool is never handed out again; the host gets a fresh pool.
INVARIANT (cancellation): a cancelled acquire never leaves a phantom in-flight count, and a
pool close, once started, runs to completion even if the task awaiting it is cancelled.
INVARIANT (PR #1555 review): the request path only STARTS a close, never awaits one — so a
close's error or slowness can never fail, delay or replace the result of any request (nor spend
its deadline). A close error is logged when it happens; :meth:`HostPools.aclose` additionally
waits for every close and re-raises the failures it waited on as one ``ExceptionGroup``.

FEATURE: url4 source fetch destination guard (OME-1544) — bounded per-host pools (OME-1719).
"""

from __future__ import annotations

import asyncio
import logging
from collections import OrderedDict
from collections.abc import Callable, Iterator

import httpx

_log = logging.getLogger(__name__)


class Lease:
    """One request's hold on a host's pool, from the attempt until its response is closed."""

    __slots__ = ("_entry", "_owner", "_released")

    def __init__(self, owner: HostPools, entry: _Entry) -> None:
        self._owner = owner
        self._entry = entry
        self._released = False

    @property
    def transport(self) -> httpx.AsyncBaseTransport:
        return self._entry.transport

    async def release(self) -> None:
        """End this request's hold; idempotent, so a double close never frees a busy pool.

        Never raises and never waits: a pool this frees is only scheduled to close.
        """
        if self._released:
            return
        self._released = True
        self._owner._drop(self._entry)


class _Entry:
    __slots__ = ("active", "closing", "retired", "transport")

    def __init__(self, transport: httpx.AsyncBaseTransport) -> None:
        self.transport = transport
        self.active = 0
        self.retired = False
        self.closing: asyncio.Task[None] | None = None


class HostPools:
    """An LRU map ``host -> pool`` holding at most ``limit`` pools, with in-flight leases."""

    def __init__(self, factory: Callable[[], httpx.AsyncBaseTransport], limit: int) -> None:
        if limit < 1:
            raise ValueError(f"max_hosts must keep at least one pool, got {limit}")
        self._factory = factory
        self._limit = limit
        self._entries: OrderedDict[str, _Entry] = OrderedDict()
        # WHY: evicted pools still serving a request, so a shutdown can close them too.
        self._retired: set[_Entry] = set()
        # WHY: strong references to closes in progress (the loop only holds tasks weakly).
        self._closing: set[asyncio.Task[None]] = set()

    def __iter__(self) -> Iterator[str]:
        return iter(self._entries)

    def __len__(self) -> int:
        return len(self._entries)

    async def acquire(self, host: str) -> Lease:
        """A lease on ``host``'s pool (created on first use), made most recently used."""
        entry = self._entries.get(host)
        if entry is None:
            entry = self._entries[host] = _Entry(self._factory())
        self._entries.move_to_end(host)
        # WHY before evicting: the counted lease keeps this entry from ever being closed here.
        entry.active += 1
        # WHY no await from here to the Lease: a cancel can only land before this method runs,
        # so a counted entry always reaches its Lease (no phantom in-flight count).
        self._evict()
        return Lease(self, entry)

    def _evict(self) -> None:
        while len(self._entries) > self._limit:
            _host, victim = self._entries.popitem(last=False)
            victim.retired = True
            if victim.active:
                self._retired.add(victim)  # AIDEV-NOTE: closed by its last release
            else:
                # WHY start, not await: the victim's close is not this request's business.
                self._start_close(victim)

    def _drop(self, entry: _Entry) -> None:
        """Undo one in-flight count; start the close of a retired entry that became idle."""
        entry.active -= 1
        if entry.retired and not entry.active:
            self._retired.discard(entry)
            self._start_close(entry)

    def _start_close(self, entry: _Entry) -> None:
        """Start the entry's one close task (a pool is closed at most once)."""
        if entry.closing is None:
            entry.closing = asyncio.ensure_future(entry.transport.aclose())
            self._closing.add(entry.closing)
            entry.closing.add_done_callback(self._closing.discard)
            # WHY: retrieves (so never "Task exception was never retrieved") and logs a close
            # error that no request is allowed to see.
            entry.closing.add_done_callback(_log_close_error)

    async def aclose(self) -> None:
        """Close every pool, retained or evicted-but-busy (adapter shutdown).

        Raises an ``ExceptionGroup`` of the close failures it waited on, after ALL closes end.
        """
        entries = [*self._entries.values(), *self._retired]
        self._entries.clear()
        self._retired.clear()
        for entry in entries:
            entry.retired = True
            self._start_close(entry)
        pending = list(self._closing)
        if not pending:
            return
        # INVARIANT: shutdown returns only after every close has finished — failed ones
        # included (return_exceptions: no fail-fast). WHY shield: cancelling this waiter must
        # not cancel the closes; they stay tracked in _closing, so a later aclose() waits again.
        results = await asyncio.shield(asyncio.gather(*pending, return_exceptions=True))
        failures = [result for result in results if isinstance(result, Exception)]
        if failures:
            raise ExceptionGroup("closing per-host connection pools failed", failures)


def _log_close_error(task: asyncio.Task[None]) -> None:
    if task.cancelled():
        return
    error = task.exception()
    if error is not None:
        _log.warning("closing a per-host connection pool failed", exc_info=error)


__all__ = ["HostPools", "Lease"]
