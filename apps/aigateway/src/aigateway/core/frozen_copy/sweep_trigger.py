"""The periodic trigger of the frozen copy sweep (OME-1947, spec contracts.md K7).

FEATURE (OME-1947): the gateway lifespan always arms this trigger. It has no switch (owner
decision Q22). The first run is 1 to 5 minutes after the start; then one run for each interval.
INVARIANT: one loop owns each run, so two runs of one process never overlap; a failed run is
logged one time, by the sweep, and the next interval runs as normal.
WHY sleep, now and the start delay are bound in the constructor: some tests patch the global
asyncio.sleep, and each gateway test that uses TestClient runs the lifespan with this trigger armed.
"""

from __future__ import annotations

import asyncio
import logging
import random
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from functools import partial
from typing import TYPE_CHECKING

from aigateway.core.snapshot_scheduler import Sleep

from .sweep import build_frozen_copy_sweep

if TYPE_CHECKING:
    from aigateway.config import Settings

__all__ = ["FrozenCopySweepTrigger", "build_sweep_trigger"]

logger = logging.getLogger(__name__)

# WHY bound at import: a later global patch of asyncio.sleep must not make the loop spin.
_ASYNC_SLEEP: Sleep = asyncio.sleep
_TASK_NAME = "frozen-copy-sweep"
_START_DELAY_MIN_S = 60.0
_START_DELAY_MAX_S = 300.0


def _random_start_delay() -> float:
    # WHY random: replicas that start at the same time do not run the sweep at the same moment.
    return random.uniform(_START_DELAY_MIN_S, _START_DELAY_MAX_S)


def _utc_now() -> datetime:
    return datetime.now(UTC)


class FrozenCopySweepTrigger:
    """One owned task: the sweep runs after a start delay, then one time for each interval."""

    def __init__(
        self,
        run: Callable[[], Awaitable[object]],
        *,
        interval_s: float,
        start_delay_s: Callable[[], float] | None = None,
        now: Callable[[], datetime] | None = None,
        sleep: Sleep | None = None,
    ) -> None:
        self._run = run
        self._interval_s = float(interval_s)
        self._start_delay_s = start_delay_s if start_delay_s is not None else _random_start_delay
        self._now = now if now is not None else _utc_now
        self._sleep = sleep if sleep is not None else _ASYNC_SLEEP
        self._task: asyncio.Task[None] | None = None
        self._busy = False
        self._runs = 0
        self._last_started_at: datetime | None = None

    def start(self) -> None:
        """Begin the loop as one owned task. A live task is left alone."""
        if self._task is not None and not self._task.done():
            return
        self._task = asyncio.get_running_loop().create_task(self._loop(), name=_TASK_NAME)

    async def stop(self) -> None:
        """Cancel and await the owned task, also when it is in its first sleep."""
        task = self._task
        self._task = None
        if task is None:
            return
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    @property
    def task(self) -> asyncio.Task[None] | None:
        return self._task

    @property
    def busy(self) -> bool:
        return self._busy

    @property
    def runs(self) -> int:
        """The number of runs that ended, with success or with an error."""
        return self._runs

    @property
    def interval_s(self) -> float:
        return self._interval_s

    @property
    def last_started_at(self) -> datetime | None:
        return self._last_started_at

    async def _loop(self) -> None:
        await self._sleep(self._start_delay_s())
        while True:
            await self._run_once()
            await self._sleep(self._interval_s)

    async def _run_once(self) -> None:
        self._busy = True
        self._last_started_at = self._now()
        try:
            await self._run()
        except Exception as exc:
            # WHY DEBUG: run_pass already writes the one ERROR record of a failed run (spec
            # prd/copy-sweep.md section 4.4); a second record would count the failure two times.
            # The type only: the message of a database error can carry row data.
            logger.debug("frozen copy sweep trigger run failed error=%s", type(exc).__name__)
        finally:
            self._busy = False
        self._runs += 1


def build_sweep_trigger(settings: Settings) -> FrozenCopySweepTrigger:
    """The periodic trigger of this gateway: each run is one pass of the sweep of `settings`."""
    sweep = build_frozen_copy_sweep(settings)
    return FrozenCopySweepTrigger(
        partial(sweep.run_pass, trigger="periodic"),
        interval_s=float(settings.frozen_copy_sweep_interval_seconds),
    )
