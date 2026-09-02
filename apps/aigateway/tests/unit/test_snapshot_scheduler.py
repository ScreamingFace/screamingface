"""Schedule evidence for the cache-snapshot scheduler (OME-1021).

The weekly contract, pinned: next-fire is the earliest Friday 05:00:00 UTC STRICTLY after
now (the no-catch-up boundary — at exactly 05:00:00.000 the answer is next week), one
cycle fires exactly once per deadline and never catches up over a gap, a fire while one is
in flight is skipped and recorded, a failing run retries with jittered exponential
backoff and never escapes, and stop() cancels and awaits the owned task.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta

import pytest

from aigateway.core.snapshot_scheduler import CacheSnapshotScheduler, next_fire


def _utc(*args: int) -> datetime:
    return datetime(*args, tzinfo=UTC)


class _FakeClock:
    """A mutable clock; ``sleep`` jumps it forward by the requested delay and yields once."""

    def __init__(self, start: datetime) -> None:
        self.value = start
        self.sleeps: list[float] = []

    def __call__(self) -> datetime:
        return self.value

    async def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.value += timedelta(seconds=seconds)
        await asyncio.sleep(0)  # yield once, like a real sleeper


# --- next-fire math (UTC only, no DST) --------------------------------------------------


def test_friday_04_59_fires_at_five_today() -> None:
    assert next_fire(_utc(2026, 8, 28, 4, 59, 0)) == _utc(2026, 8, 28, 5, 0, 0)


def test_friday_exactly_five_is_next_week_no_catch_up() -> None:
    assert next_fire(_utc(2026, 8, 28, 5, 0, 0)) == _utc(2026, 9, 4, 5, 0, 0)


def test_friday_just_after_five_is_next_week() -> None:
    assert next_fire(_utc(2026, 8, 28, 5, 0, 0, 1)) == _utc(2026, 9, 4, 5, 0, 0)


def test_thursday_evening_fires_tomorrow_morning() -> None:
    assert next_fire(_utc(2026, 8, 27, 23, 59, 59)) == _utc(2026, 8, 28, 5, 0, 0)


def test_saturday_lands_on_the_next_friday() -> None:
    assert next_fire(_utc(2026, 8, 29, 12, 0, 0)) == _utc(2026, 9, 4, 5, 0, 0)


def test_monday_lands_on_the_next_friday() -> None:
    assert next_fire(_utc(2026, 8, 31, 9, 30, 0)) == _utc(2026, 9, 4, 5, 0, 0)


# --- the loop ---------------------------------------------------------------------------


def _scheduler(
    clock: _FakeClock,
    run: Callable[[], Awaitable[None]],
    *,
    jitter: Callable[[], float] = lambda: 1.0,
) -> CacheSnapshotScheduler:
    return CacheSnapshotScheduler(run, now=clock, sleep=clock.sleep, jitter=jitter)


@pytest.mark.asyncio
async def test_a_cycle_fires_once_per_weekly_deadline_and_never_catches_up() -> None:
    clock = _FakeClock(_utc(2026, 8, 26, 12, 0, 0))  # Wednesday
    runs: list[datetime] = []

    async def run() -> None:
        runs.append(clock())

    scheduler = _scheduler(clock, run)

    await scheduler._cycle()
    assert runs == [_utc(2026, 8, 28, 5, 0, 0)]  # fires at Friday 05:00, exactly

    await scheduler._cycle()
    assert runs[-1] == _utc(2026, 9, 4, 5, 0, 0)  # and one week later, again exactly

    # No catch-up: advancing the clock past a deadline (a gap the process slept through)
    # does not fire an on-the-spot run — the next fire is the Friday after the current now.
    clock.value = _utc(2026, 9, 12, 12, 0, 0)  # Saturday
    await scheduler._cycle()
    assert runs[-1] == _utc(2026, 9, 18, 5, 0, 0)
    assert len(runs) == 3

    assert [record.state for record in scheduler.records()] == ["complete"] * 3


@pytest.mark.asyncio
async def test_a_fire_while_one_is_in_flight_is_skipped_and_recorded() -> None:
    clock = _FakeClock(_utc(2026, 8, 28, 5, 0, 0))
    gate = asyncio.Event()
    runs: list[datetime] = []

    async def run() -> None:
        runs.append(clock())
        await gate.wait()

    scheduler = _scheduler(clock, run)
    first = asyncio.create_task(scheduler._fire())
    await asyncio.sleep(0)  # the first fire is now in flight
    await scheduler._fire()  # second fire while busy

    assert scheduler.busy is True
    assert [record.state for record in scheduler.records()] == ["running", "skipped"]
    gate.set()
    await first
    assert runs == [clock.value]
    assert scheduler.busy is False


@pytest.mark.asyncio
async def test_a_failing_run_retries_with_jittered_backoff_then_completes() -> None:
    clock = _FakeClock(_utc(2026, 8, 28, 5, 0, 0))
    attempts: list[int] = []

    async def run() -> None:
        attempts.append(1)
        if len(attempts) < 3:
            raise RuntimeError("garage is down")

    scheduler = _scheduler(clock, run, jitter=lambda: 1.0)
    await scheduler._fire()

    assert len(attempts) == 3
    assert clock.sleeps == [60.0, 120.0]  # exponential: backoff, backoff * 2
    (record,) = scheduler.records()
    assert record.state == "complete"
    assert record.attempts == 2  # two failures before the success


@pytest.mark.asyncio
async def test_a_terminal_failure_is_recorded_and_does_not_escape() -> None:
    clock = _FakeClock(_utc(2026, 8, 28, 5, 0, 0))

    async def run() -> None:
        raise RuntimeError("disk full")

    scheduler = _scheduler(clock, run, jitter=lambda: 1.0)
    await scheduler._fire()

    (record,) = scheduler.records()
    assert record.state == "failed"
    assert record.error == "RuntimeError: disk full"
    assert record.attempts == 3
    assert scheduler.busy is False


@pytest.mark.asyncio
async def test_stop_cancels_and_awaits_the_owned_task() -> None:
    clock = _FakeClock(_utc(2026, 8, 26, 12, 0, 0))
    scheduler = _scheduler(clock, lambda: _never())
    scheduler.start()
    await asyncio.sleep(0)
    assert scheduler._task is not None and not scheduler._task.done()

    await scheduler.stop()
    assert scheduler._task is None
    await asyncio.sleep(0)  # nothing re-scheduled it


async def _never() -> None:
    await asyncio.Event().wait()
