"""One close per owner, kept across a cancelled caller (PR #1555 review 4).

FEATURE: url4 source fetch destination guard (OME-1544) — bounded per-host pools (OME-1719).
STORY: as an SDK embedder, a shutdown I cancel and then retry still reports how the close ended.

INVARIANT: an owner's close runs ONCE, as one shielded task. Cancelling a caller never cancels
it, and every :meth:`CloseOnce.run` — the first, a concurrent one or a retry — awaits that same
task until a caller that was NOT cancelled has seen it end (success, or its exception). After
that, ``run`` is a no-op: the outcome was reported.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable


class CloseOnce:
    __slots__ = ("_reported", "_task")

    def __init__(self) -> None:
        self._task: asyncio.Future[None] | None = None
        self._reported = False

    async def run(self, close: Callable[[], Awaitable[None]]) -> None:
        """Start ``close`` on the first call, then await its one task (see the INVARIANT)."""
        if self._reported:
            return
        if self._task is None:
            self._task = asyncio.ensure_future(close())
            # WHY: if every caller was cancelled and none retries, the failure was already
            # logged where it happened; retrieve it so asyncio does not log it a second time.
            self._task.add_done_callback(_retrieve)
        task = self._task
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            raise  # WHY: a cancelled caller saw nothing; the next run() awaits the task again
        except BaseException:
            self._reported = True
            raise
        self._reported = True


def _retrieve(task: asyncio.Future[None]) -> None:
    if not task.cancelled():
        task.exception()


__all__ = ["CloseOnce"]
