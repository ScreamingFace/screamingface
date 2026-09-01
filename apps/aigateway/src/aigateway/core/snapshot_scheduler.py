"""The weekly Friday-snapshot scheduler (OME-1021).

Owns the in-process cron loop: compute the next Friday 05:00:00 UTC strictly after now,
sleep until it, fire the export once (with bounded jittered backoff on failure), record the
outcome, recompute from ``now`` and repeat. The task is OWned — created in ``_lifespan``,
cancelled and awaited at shutdown — and every failure is contained: a bad fire logs and the
next Friday is the backstop (no catch-up is a locked decision; nothing queues).

Concurrency posture (named patterns): single-flight — one ``_busy`` slot, a fire that finds
the previous run still in flight skips and logs (weekly cadence has no queue); structured
concurrency — the loop task cannot outlive ``stop()``; idempotent by construction — the
exporter's timestamped object keys make a re-run harmless.
"""

from __future__ import annotations

import asyncio
import logging
import random
from collections import deque
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

logger = logging.getLogger(__name__)

_CRON_DAY = 4  # datetime.weekday(): Monday = 0 … Friday = 4
_CRON_HOUR = 5
_CRON_MINUTE = 0

DEFAULT_RETRY_ATTEMPTS = 3
DEFAULT_RETRY_BACKOFF_S = 60.0
_HISTORY_LIMIT = 50

type Run = Callable[[], Awaitable[None]]
type Sleep = Callable[[float], Awaitable[None]]
type Jitter = Callable[[], float]


def next_fire(now: datetime) -> datetime:
    """The earliest Friday 05:00:00 UTC strictly after ``now`` (UTC, no DST).

    ``strictly`` is the no-catch-up contract: at Friday 05:00:00.000 exactly, the answer is
    the NEXT Friday — a process that starts mid-window does not fire an on-the-spot run.
    """
    current = now.astimezone(UTC)
    candidate = current.replace(hour=_CRON_HOUR, minute=_CRON_MINUTE, second=0, microsecond=0)
    if candidate <= current:
        candidate += timedelta(days=1)
    while candidate.weekday() != _CRON_DAY:
        candidate += timedelta(days=1)
    return candidate


@dataclass(slots=True)
class SnapshotRecord:
    """One scheduled fire's observable outcome (serialized shape for ``app.state``)."""

    started_at: datetime
    state: str = "running"  # running | complete | failed | skipped
    finished_at: datetime | None = None
    error: str | None = None
    attempts: int = 0


class CacheSnapshotScheduler:
    """One owned task that fires the cache-snapshot export on its weekly deadline.

    Everything timing-related is injectable for tests: the clock, the sleeper, the backoff
    jitter, the run itself. Production wiring supplies the exporter's ``run`` closure and
    ``asyncio.sleep``.
    """

    def __init__(
        self,
        run: Run,
        *,
        now: Callable[[], datetime] | None = None,
        sleep: Sleep | None = None,
        jitter: Jitter | None = None,
        retry_attempts: int = DEFAULT_RETRY_ATTEMPTS,
        retry_backoff_s: float = DEFAULT_RETRY_BACKOFF_S,
    ) -> None:
        self._run = run
        self._now = now if now is not None else lambda: datetime.now(UTC)
        self._sleep = sleep if sleep is not None else asyncio.sleep
        self._jitter = jitter if jitter is not None else (lambda: random.uniform(0.5, 1.5))
        self._retry_attempts = retry_attempts
        self._retry_backoff_s = retry_backoff_s
        self._task: asyncio.Task[None] | None = None
        self._busy = False
        self._records: deque[SnapshotRecord] = deque(maxlen=_HISTORY_LIMIT)

    # --- lifecycle ------------------------------------------------------------------------

    def start(self) -> None:
        """Begin the loop as one owned task. Idempotent: a live task is left alone."""
        if self._task is not None and not self._task.done():
            return
        self._task = asyncio.get_running_loop().create_task(
            self._loop(), name="cache-snapshot-scheduler"
        )

    async def stop(self) -> None:
        """Cancel and await the owned task — no orphan survives shutdown."""
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
    def busy(self) -> bool:
        """Whether a fire is still in flight (the single-flight gate's input)."""

        return self._busy

    def records(self) -> list[SnapshotRecord]:
        return list(self._records)

    # --- the loop -------------------------------------------------------------------------

    async def _loop(self) -> None:
        while True:
            try:
                await self._cycle()
            except asyncio.CancelledError:
                raise
            except Exception:
                # The scheduler must never die on one bad cycle: a fresh next_fire from
                # now lands on the next Friday and the schedule resumes.
                logger.exception(
                    "cache snapshot schedule cycle failed; next Friday is the backstop"
                )

    async def _cycle(self) -> None:
        fire_at = next_fire(self._now())
        delay = (fire_at - self._now()).total_seconds()
        await self._sleep(max(delay, 0.0))
        await self._fire()

    async def _fire(self) -> None:
        """One scheduled fire: skip if one is in flight, else run with bounded retries."""
        if self._busy:
            self._records.append(SnapshotRecord(started_at=self._now(), state="skipped"))
            logger.warning("cache snapshot fire skipped: a previous run is still in flight")
            return
        self._busy = True
        record = SnapshotRecord(started_at=self._now())
        self._records.append(record)
        try:
            await self._run_with_retry(record)
        finally:
            self._busy = False

    async def _run_with_retry(self, record: SnapshotRecord) -> None:
        """Run the export with exponential backoff (jittered), then record the outcome.

        The record is mutated in place; on terminal failure the error is logged and the
        record says so — nothing escapes into the caller.
        """
        for attempt in range(self._retry_attempts):
            try:
                await self._run()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                record.attempts = attempt + 1
                if attempt == self._retry_attempts - 1:
                    record.state = "failed"
                    record.error = f"{type(exc).__name__}: {exc}"
                    record.finished_at = self._now()
                    logger.error(
                        "cache snapshot failed after %d attempts: %s",
                        record.attempts,
                        exc,
                    )
                    return
                delay = self._retry_backoff_s * (2**attempt) * self._jitter()
                logger.warning(
                    "cache snapshot attempt %d failed (%s); retrying in %.0fs",
                    attempt + 1,
                    exc,
                    delay,
                )
                await self._sleep(delay)
                continue
            record.state = "complete"
            record.finished_at = self._now()
            return


__all__ = [
    "CacheSnapshotScheduler",
    "DEFAULT_RETRY_ATTEMPTS",
    "DEFAULT_RETRY_BACKOFF_S",
    "SnapshotRecord",
    "next_fire",
]
