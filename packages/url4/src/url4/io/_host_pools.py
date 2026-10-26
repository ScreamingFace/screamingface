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

FEATURE: url4 source fetch destination guard (OME-1544) — bounded per-host pools (OME-1719).
"""

from __future__ import annotations

import asyncio
from collections import OrderedDict
from collections.abc import Callable, Iterator

import httpx


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
        """End this request's hold; idempotent, so a double close never frees a busy pool."""
        if self._released:
            return
        self._released = True
        await self._owner._release(self._entry)


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
        try:
            await self._evict()
        except BaseException:
            # WHY synchronous: a cancelled acquire hands out no Lease, so it must undo its
            # count here, without another await that a second cancel could interrupt.
            self._drop(entry)
            raise
        return Lease(self, entry)

    async def _evict(self) -> None:
        idle: list[_Entry] = []
        while len(self._entries) > self._limit:
            _host, victim = self._entries.popitem(last=False)
            victim.retired = True
            if victim.active:
                self._retired.add(victim)  # AIDEV-NOTE: closed by its last _release
            else:
                idle.append(victim)
        for victim in idle:
            await self._close(victim)

    def _drop(self, entry: _Entry) -> asyncio.Task[None] | None:
        """Undo one in-flight count; start the close of a retired entry that became idle."""
        entry.active -= 1
        if entry.retired and not entry.active:
            self._retired.discard(entry)
            return self._start_close(entry)
        return None

    async def _release(self, entry: _Entry) -> None:
        closing = self._drop(entry)
        if closing is not None:
            await asyncio.shield(closing)

    def _start_close(self, entry: _Entry) -> asyncio.Task[None]:
        """The entry's one close task, started on first call (a pool is closed at most once)."""
        if entry.closing is None:
            entry.closing = asyncio.ensure_future(entry.transport.aclose())
            self._closing.add(entry.closing)
            entry.closing.add_done_callback(self._closing.discard)
        return entry.closing

    async def _close(self, entry: _Entry) -> None:
        # WHY shield: cancelling the waiter must not abandon a half-closed transport.
        await asyncio.shield(self._start_close(entry))

    async def aclose(self) -> None:
        """Close every pool, retained or evicted-but-busy (adapter shutdown)."""
        entries = [*self._entries.values(), *self._retired]
        self._entries.clear()
        self._retired.clear()
        for entry in entries:
            entry.retired = True
            self._start_close(entry)
        # INVARIANT: shutdown returns only after every close — including ones a cancelled
        # acquire or release left running — has finished.
        pending = list(self._closing)
        if pending:
            await asyncio.gather(*pending)


__all__ = ["HostPools", "Lease"]
