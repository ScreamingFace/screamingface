"""Spec §5's 90-day purge, as a policy object with the loop split off.

`sweep()` is one pass and does no waiting, so its behaviour is testable without a clock or a
sleep; `run()` is the forever-loop the lifespan owns. That split is the engine's sweeper/reaper
shape, and it is the reason none of the tests below take a second to run.

**It is started inside `_lifespan`, never `app.router.on_startup`** (plan §6, §11 conflict 12).
On the pinned fastapi/starlette, passing `lifespan=` sets `Router.lifespan_context` directly:
`router.startup()` is never called, an appended handler is dropped with no exception and no
warning, and starlette 1.3.1 removed `on_startup` from `Router.__init__` entirely, so not even
the deprecation warning survives. The purge would simply never run in production while every
unit test calling `purge_expired()` directly still passed.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import timedelta

from .pipeline import StorageUnavailable
from .store import ReportStore

logger = logging.getLogger(__name__)

PURGE_INTERVAL = timedelta(hours=6)
"""Four passes a day against a 90-day window. Deliberately not an environment variable: plan
§2.4 fixes the chart's rendered set, and a knob nobody would ever turn is one more name that can
drift out of `Settings`. The window itself IS configurable — that is the number with a policy
behind it."""


class RetentionPurge:
    def __init__(self, store: ReportStore, interval: timedelta = PURGE_INTERVAL) -> None:
        self._store = store
        self._interval = interval

    async def sweep(self) -> int:
        """One pass. Returns how many rows went, and never raises.

        A purge failure must not take the process down or stop the loop: the database being
        briefly unreachable is what `/readyz` is for, and retention is the least urgent thing
        this service does. It is logged at warning so a purge that has been failing for a week
        is visible rather than merely absent.
        """
        try:
            purged = await self._store.purge_expired()
        except StorageUnavailable as exc:
            logger.warning("retention purge failed; will retry next sweep (%s)", exc)
            return 0
        if purged:
            logger.info("retention purge removed %d expired report(s)", purged)
        return purged

    async def run(self) -> None:
        """Sweep, then sweep again every interval, until cancelled.

        The first pass runs immediately rather than after a wait: a process that is restarted
        more often than the interval would otherwise never purge anything at all, and that is
        the ordinary life of a pod during a rollout.
        """
        while True:
            await self.sweep()
            await asyncio.sleep(self._interval.total_seconds())
