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

from screamingface_engine.artifacts.run_results import RunResultStore

logger = logging.getLogger(__name__)


class Sweepable(Protocol):
    """The part of `RunRegistry` a sweep uses."""

    def reconcile(self) -> Awaitable[int]: ...

    def expiring(self, older_than: datetime) -> Awaitable[list[str]]: ...

    def expire(self, run_ids: Sequence[str]) -> Awaitable[int]: ...


class RunSweeper:
    """``results`` and ``objects`` are the run-results store and the registry's read of the keys
    each Run names (E5 P2 spec R13); without them a sweep deletes rows only."""

    def __init__(
        self,
        registry: Sweepable,
        *,
        retention: timedelta,
        clock: Callable[[], datetime],
        results: RunResultStore | None = None,
        objects: Callable[[Sequence[str]], Awaitable[dict[str, list[str]]]] | None = None,
    ) -> None:
        self._registry = registry
        self._retention = retention
        self._clock = clock
        self._results = results
        self._objects = objects

    async def sweep_once(self) -> None:
        lost = await self._registry.reconcile()
        cutoff = self._clock() - self._retention
        expired = 0
        # WHY batches until one deletes nothing: `expiring` lists one batch at a time, and a
        # batch that deletes nothing would be listed again forever.
        while batch := await self._registry.expiring(cutoff):
            cleared = await self._delete_objects(batch)
            deleted = await self._registry.expire(cleared) if cleared else 0
            expired += deleted
            if not deleted:
                break
        if self._results is not None:
            # R13: what no Run names (a second execution, a lost outcome) goes by age, a day after
            # the retention; on S3 the bucket's own rule does it, and this is a no-op.
            await asyncio.to_thread(self._results.delete_older_than, cutoff - timedelta(days=1))
        if lost or expired:
            logger.info("Run sweep: %d Candidates lost, %d Runs expired", lost, expired)

    async def _delete_objects(self, batch: Sequence[str]) -> list[str]:
        """The Runs of ``batch`` whose objects are deleted, so their rows may go (R13).

        INVARIANT: a Run's rows outlive its objects, so a delete that failed is retried by the
        next sweep, which finds the Run again.
        """
        if self._results is None or self._objects is None:
            return list(batch)
        keys = await self._objects(batch)
        cleared: list[str] = []
        for run_id in batch:
            try:
                await asyncio.to_thread(self._results.delete, keys.get(run_id, []))
            except Exception:
                logger.warning("could not delete the objects of %s; keeping it", run_id)
                continue
            cleared.append(run_id)
        return cleared

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
