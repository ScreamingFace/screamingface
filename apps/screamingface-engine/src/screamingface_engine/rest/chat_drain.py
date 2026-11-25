"""The chat drain at App shutdown (CC-S37).

`request()` is safe from a signal handler or another thread. A server hook reaches every live
drain through `request_all_drains()`.
"""

from __future__ import annotations

import asyncio
import weakref

_DRAINS: weakref.WeakSet[ChatDrain] = weakref.WeakSet()


class ChatDrain:
    """One stop-signal flag that wakes every chat handler waiting on it."""

    def __init__(self) -> None:
        self._requested = False
        self._event = asyncio.Event()
        self._loop: asyncio.AbstractEventLoop | None = None
        _DRAINS.add(self)

    @property
    def requested(self) -> bool:
        return self._requested

    def request(self) -> None:
        # INVARIANT: safe from a signal handler and from another thread: a bool write plus
        # call_soon_threadsafe.
        self._requested = True
        loop = self._loop
        if loop is not None and not loop.is_closed():
            loop.call_soon_threadsafe(self._event.set)

    async def wait(self) -> None:
        # WHY: bind the loop first, then read the flag, so a request() that runs between the two
        # still wakes the waiter (it sees the bound loop, or the waiter sees the flag).
        self._loop = asyncio.get_running_loop()
        if self._requested:
            return
        await self._event.wait()


def request_all_drains() -> int:
    """Request every live drain; the number requested."""
    drains = list(_DRAINS)
    for drain in drains:
        drain.request()
    return len(drains)


__all__ = ["ChatDrain", "request_all_drains"]
