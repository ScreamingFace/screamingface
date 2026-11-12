"""The App's Run sweeps: reconcile (E5 P1 spec R6) and retention (R7), at start and hourly.

FEATURE: first-class Runs (OME-1785). Modelled on the artifact sweeper (`app.py`): one sweep at
start clears what the last process left, and a periodic one covers an App that stays up for
weeks. The queries are the registry's; this only decides when they run.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable, Sequence
from datetime import datetime, timedelta
from typing import Protocol

logger = logging.getLogger(__name__)


class Sweepable(Protocol):
    """The part of `RunRegistry` a sweep uses."""

    def reconcile(self) -> Awaitable[int]: ...

    def expiring(self, older_than: datetime) -> Awaitable[list[str]]: ...

    def expire(self, run_ids: Sequence[str]) -> Awaitable[int]: ...


class RunSweeper:
    def __init__(
        self, registry: Sweepable, *, retention: timedelta, clock: Callable[[], datetime]
    ) -> None:
        self._registry = registry
        self._retention = retention
        self._clock = clock

    async def sweep_once(self) -> None:
        lost = await self._registry.reconcile()
        cutoff = self._clock() - self._retention
        expired = 0
        # WHY batches until one deletes nothing: `expiring` lists one batch at a time, and a
        # batch that deletes nothing would be listed again forever.
        while batch := await self._registry.expiring(cutoff):
            deleted = await self._registry.expire(batch)
            expired += deleted
            if not deleted:
                break
        if lost or expired:
            logger.info("Run sweep: %d Candidates lost, %d Runs expired", lost, expired)

    async def run(self, *, interval_s: float, sweep_first: bool = True) -> None:
        """Sweep now (unless ``sweep_first`` is False), then every ``interval_s``, until
        cancelled."""
        if not sweep_first:
            await asyncio.sleep(interval_s)
        while True:
            # INVARIANT: one failed sweep never ends the loop; a database blip would otherwise
            # stop reconcile and retention until the next deploy.
            try:
                await self.sweep_once()
            except Exception:
                logger.exception("Run sweep failed; retrying next interval")
            await asyncio.sleep(interval_s)


__all__ = ["RunSweeper", "Sweepable"]
