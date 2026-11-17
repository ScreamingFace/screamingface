"""The pod-deletion-cost publisher's log volume (OME-1931, spec D3): what is pinned here.

A streak of failed writes logs ONE warning. WHY: with no Role or no API-server egress every retry
fails, and a warning per retry would have no end. The error counter keeps the rate. The first good
write after a streak logs one INFO line, and the next streak warns again. No network: the writer
is a fake.
"""

import asyncio
import contextlib
import logging

import pytest

from screamingface_engine.worker.deletion_cost import DeletionCostPublisher
from screamingface_engine.worker.metrics import build_worker_metrics

pytestmark = pytest.mark.asyncio

_LOGGER = "screamingface_engine.worker.deletion_cost"


class _ScriptedWriter:
    """Fails while `failing` is set; records each attempt."""

    def __init__(self) -> None:
        self.failing = True
        self.attempts: list[int] = []
        self.costs: list[int] = []

    async def write(self, cost: int) -> None:
        self.attempts.append(cost)
        if self.failing:
            raise RuntimeError("boom")
        self.costs.append(cost)

    async def aclose(self) -> None:
        return None


async def _wait_until(predicate, timeout_s: float = 2.0) -> None:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout_s
    while not predicate():
        if loop.time() > deadline:
            raise AssertionError("condition not met in time")
        await asyncio.sleep(0.005)


def _records(caplog: pytest.LogCaptureFixture, level: int) -> list[logging.LogRecord]:
    return [r for r in caplog.records if r.name == _LOGGER and r.levelno == level]


async def test_a_streak_of_failures_logs_one_warning_then_one_recovery_line(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG)
    metrics = build_worker_metrics()
    writer = _ScriptedWriter()
    pub = DeletionCostPublisher(
        writer,
        writes=metrics.deletion_cost_writes,
        min_interval_s=0.0,
        retry_initial_s=0.01,
        retry_max_s=0.01,
    )
    task = asyncio.create_task(pub.run())
    try:
        pub.notify(2)
        await _wait_until(lambda: len(writer.attempts) >= 4)
        assert len(_records(caplog, logging.WARNING)) == 1
        assert len(_records(caplog, logging.DEBUG)) >= 3

        writer.failing = False
        await _wait_until(lambda: writer.costs == [2])
        assert len(_records(caplog, logging.INFO)) == 1
        assert len(_records(caplog, logging.WARNING)) == 1

        # A NEW streak warns again.
        writer.failing = True
        pub.notify(3)
        await _wait_until(lambda: len(_records(caplog, logging.WARNING)) == 2)
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task


async def test_a_good_write_with_no_streak_logs_nothing(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG)
    metrics = build_worker_metrics()
    writer = _ScriptedWriter()
    writer.failing = False
    pub = DeletionCostPublisher(writer, writes=metrics.deletion_cost_writes, min_interval_s=0.0)
    task = asyncio.create_task(pub.run())
    try:
        pub.notify(0)
        await _wait_until(lambda: writer.costs == [0])
        assert [r for r in caplog.records if r.name == _LOGGER] == []
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
