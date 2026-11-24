"""The periodic trigger of the frozen copy sweep
(OME-1947, prd/copy-sweep.md S-23, contracts.md K7)."""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from functools import partial

import pytest

from aigateway.config import Settings
from aigateway.core.frozen_copy import sweep as sweep_module
from aigateway.core.frozen_copy import sweep_trigger as trigger_module
from aigateway.core.frozen_copy.sweep import FrozenCopySweep
from aigateway.core.frozen_copy.sweep_trigger import FrozenCopySweepTrigger, build_sweep_trigger

_TRIGGER_LOGGER = "aigateway.core.frozen_copy.sweep_trigger"
_SWEEP_LOGGER = "aigateway.core.frozen_copy.sweep"
# WHY bound at import: a test that patches asyncio.sleep must still be able to yield to the loop.
_REAL_SLEEP = asyncio.sleep


async def _settle() -> None:
    for _ in range(20):
        await _REAL_SLEEP(0)


class _GatedSleep:
    """A sleeper that records each delay and returns only when the test releases it."""

    def __init__(self) -> None:
        self.delays: list[float] = []
        self._gate: asyncio.Queue[None] = asyncio.Queue()

    async def __call__(self, delay: float) -> None:
        self.delays.append(delay)
        await self._gate.get()

    def release(self) -> None:
        self._gate.put_nowait(None)


@pytest.mark.asyncio
async def test_the_first_run_waits_for_the_start_delay_then_one_run_for_each_interval() -> None:
    sleep = _GatedSleep()
    calls: list[int] = []
    busy_seen: list[bool] = []
    holder: dict[str, FrozenCopySweepTrigger] = {}

    async def run() -> None:
        calls.append(len(sleep.delays))
        busy_seen.append(holder["t"].busy)

    fixed = datetime(2026, 11, 17, 12, 0, tzinfo=UTC)
    trigger = FrozenCopySweepTrigger(
        run,
        interval_s=3600.0,
        start_delay_s=lambda: 90.0,
        now=lambda: fixed,
        sleep=sleep,
    )
    holder["t"] = trigger
    trigger.start()
    await _settle()

    assert sleep.delays == [90.0]
    assert calls == []
    assert trigger.runs == 0
    assert trigger.last_started_at is None

    sleep.release()
    await _settle()

    assert calls == [1]
    assert busy_seen == [True]
    assert trigger.busy is False
    assert trigger.runs == 1
    assert sleep.delays == [90.0, 3600.0]
    assert trigger.last_started_at == fixed

    sleep.release()
    await _settle()

    assert calls == [1, 2]
    assert trigger.runs == 2
    assert sleep.delays == [90.0, 3600.0, 3600.0]

    await trigger.stop()
    assert trigger.task is None


@pytest.mark.asyncio
async def test_a_run_that_raises_does_not_stop_the_next_run(
    caplog: pytest.LogCaptureFixture,
) -> None:
    sleep = _GatedSleep()
    outcomes: list[str] = []

    async def run() -> None:
        if not outcomes:
            outcomes.append("raised")
            raise RuntimeError("db down SECRET-MARKER")
        outcomes.append("ok")

    trigger = FrozenCopySweepTrigger(
        run, interval_s=3600.0, start_delay_s=lambda: 60.0, sleep=sleep
    )
    with caplog.at_level(logging.DEBUG, logger=_TRIGGER_LOGGER):
        trigger.start()
        await _settle()
        sleep.release()
        await _settle()
        sleep.release()
        await _settle()

    assert outcomes == ["raised", "ok"]
    assert trigger.runs == 2
    assert trigger.busy is False
    task = trigger.task
    assert task is not None and not task.done()
    trigger_records = [r for r in caplog.records if r.name == _TRIGGER_LOGGER]
    assert [r for r in trigger_records if r.levelno >= logging.ERROR] == []
    assert [r.getMessage() for r in trigger_records if r.levelno == logging.DEBUG] == [
        "frozen copy sweep trigger run failed error=RuntimeError"
    ]
    assert "SECRET-MARKER" not in caplog.text

    await trigger.stop()


@pytest.mark.asyncio
async def test_no_run_starts_while_one_is_in_progress() -> None:
    sleep = _GatedSleep()
    release_run = asyncio.Event()
    started: list[int] = []

    async def run() -> None:
        started.append(1)
        await release_run.wait()

    trigger = FrozenCopySweepTrigger(
        run, interval_s=3600.0, start_delay_s=lambda: 90.0, sleep=sleep
    )
    trigger.start()
    await _settle()
    sleep.release()
    await _settle()

    assert started == [1]
    assert trigger.busy is True
    assert trigger.runs == 0
    # WHY: the interval sleep has not started while the run is in progress.
    assert sleep.delays == [90.0]

    release_run.set()
    await _settle()

    assert started == [1]
    assert trigger.busy is False
    assert trigger.runs == 1
    assert sleep.delays == [90.0, 3600.0]

    await trigger.stop()


@pytest.mark.asyncio
async def test_the_default_start_delay_is_one_to_five_minutes() -> None:
    sleep = _GatedSleep()

    async def run() -> None:
        return None

    trigger = FrozenCopySweepTrigger(run, interval_s=3600.0, sleep=sleep)
    trigger.start()
    await _settle()

    assert len(sleep.delays) == 1
    assert 60.0 <= sleep.delays[0] <= 300.0

    await trigger.stop()


@pytest.mark.asyncio
async def test_stop_cancels_a_task_in_its_first_sleep() -> None:
    runs: list[int] = []

    async def run() -> None:
        runs.append(1)

    trigger = FrozenCopySweepTrigger(run, interval_s=3600.0, start_delay_s=lambda: 60.0)
    trigger.start()
    await _settle()

    task = trigger.task
    assert task is not None and not task.done()
    assert task.get_name() == "frozen-copy-sweep"

    await trigger.stop()

    assert task.cancelled()
    assert trigger.task is None
    assert runs == []

    await trigger.stop()


@pytest.mark.asyncio
async def test_start_is_idempotent_while_the_task_is_live() -> None:
    async def run() -> None:
        return None

    trigger = FrozenCopySweepTrigger(run, interval_s=3600.0, start_delay_s=lambda: 60.0)
    trigger.start()
    await _settle()
    first = trigger.task

    trigger.start()

    assert trigger.task is first

    await trigger.stop()


@pytest.mark.asyncio
async def test_a_global_patch_of_asyncio_sleep_does_not_make_the_trigger_spin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runs: list[int] = []

    async def run() -> None:
        runs.append(1)

    async def _instant(delay: float) -> None:
        return None

    monkeypatch.setattr(asyncio, "sleep", _instant)
    trigger = FrozenCopySweepTrigger(run, interval_s=3600.0, start_delay_s=lambda: 60.0)
    trigger.start()
    await _settle()

    assert runs == []
    task = trigger.task
    assert task is not None and not task.done()

    await trigger.stop()
    assert task.done()


@pytest.mark.asyncio
async def test_the_builder_runs_a_periodic_pass_on_the_interval_of_the_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _FakeSweep:
        def __init__(self) -> None:
            self.triggers: list[str] = []

        async def run_pass(self, *, trigger: str, max_entries: int | None = None) -> None:
            self.triggers.append(trigger)

    fake = _FakeSweep()
    sleep = _GatedSleep()

    def _build(settings: Settings) -> _FakeSweep:
        return fake

    monkeypatch.setattr(trigger_module, "build_frozen_copy_sweep", _build)
    monkeypatch.setattr(trigger_module, "_ASYNC_SLEEP", sleep)

    trigger = build_sweep_trigger(
        Settings(**{"_env_file": None, "frozen_copy_sweep_interval_seconds": 120})
    )
    assert trigger.interval_s == 120.0

    trigger.start()
    await _settle()

    assert 60.0 <= sleep.delays[0] <= 300.0

    sleep.release()
    await _settle()

    assert fake.triggers == ["periodic"]
    assert sleep.delays[1] == 120.0

    await trigger.stop()


@pytest.mark.asyncio
async def test_a_failed_periodic_run_writes_one_error_record(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    async def _boom() -> datetime:
        raise RuntimeError("db down SECRET-MARKER")

    monkeypatch.setattr(sweep_module, "database_now", _boom)
    sweep = FrozenCopySweep([], max_entries=1)
    sleep = _GatedSleep()
    trigger = FrozenCopySweepTrigger(
        partial(sweep.run_pass, trigger="periodic"),
        interval_s=3600.0,
        start_delay_s=lambda: 60.0,
        sleep=sleep,
    )
    with (
        caplog.at_level(logging.DEBUG, logger=_TRIGGER_LOGGER),
        caplog.at_level(logging.DEBUG, logger=_SWEEP_LOGGER),
    ):
        trigger.start()
        await _settle()
        sleep.release()
        await _settle()

    errors = [r for r in caplog.records if r.levelno >= logging.ERROR]
    assert [r.getMessage() for r in errors] == [
        "frozen copy sweep run failed trigger=periodic error=RuntimeError"
    ]
    assert trigger.runs == 1
    assert "SECRET-MARKER" not in caplog.text

    await trigger.stop()
