"""The worker's pod-deletion-cost publisher (OME-1931): what is pinned here.

Pins spec D2 (a write on a change, not on a timer: the latest count wins, a burst coalesces, the
same value sends nothing, at most one write per minimum interval) and spec D3 (a failed write
never stops `run`; the retry stops at the first good write; `aclose` hides its own error). The
write counter lives on the worker's own registry. No network: the writer is a fake.
"""

import asyncio
import contextlib

import pytest

from screamingface_engine.worker.deletion_cost import DeletionCostPublisher
from screamingface_engine.worker.metrics import WorkerMetrics, build_worker_metrics

pytestmark = pytest.mark.asyncio


class _FakeWriter:
    def __init__(
        self,
        *,
        fail_times: int = 0,
        fail_costs: frozenset[int] = frozenset(),
        always_fail: bool = False,
        gate: asyncio.Event | None = None,
        close_error: Exception | None = None,
    ) -> None:
        self._fail_times = fail_times
        self._fail_costs = fail_costs
        self._always_fail = always_fail
        self._gate = gate
        self._close_error = close_error
        self.attempts: list[int] = []
        self.attempt_times: list[float] = []
        self.costs: list[int] = []
        self.closed = False

    async def write(self, cost: int) -> None:
        self.attempts.append(cost)
        self.attempt_times.append(asyncio.get_running_loop().time())
        if self._gate is not None:
            await self._gate.wait()
        if self._always_fail or cost in self._fail_costs:
            raise RuntimeError("boom")
        if self._fail_times > 0:
            self._fail_times -= 1
            raise RuntimeError("boom")
        self.costs.append(cost)

    async def aclose(self) -> None:
        self.closed = True
        if self._close_error is not None:
            raise self._close_error


async def _wait_until(predicate, timeout_s: float = 2.0) -> None:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout_s
    while not predicate():
        if loop.time() > deadline:
            raise AssertionError("condition not met in time")
        await asyncio.sleep(0.005)


def _publisher(
    writer: _FakeWriter,
    metrics: WorkerMetrics,
    *,
    min_interval_s: float = 0.0,
    retry_initial_s: float = 0.01,
    retry_max_s: float = 0.02,
) -> DeletionCostPublisher:
    return DeletionCostPublisher(
        writer,
        writes=metrics.deletion_cost_writes,
        min_interval_s=min_interval_s,
        retry_initial_s=retry_initial_s,
        retry_max_s=retry_max_s,
    )


def _count(metrics: WorkerMetrics, outcome: str) -> float:
    return (
        metrics.registry.get_sample_value(
            "screamingface_engine_worker_deletion_cost_writes_total", {"outcome": outcome}
        )
        or 0.0
    )


async def _stop(task: asyncio.Task) -> None:
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task


async def test_the_first_notify_gives_one_start_write() -> None:
    metrics = build_worker_metrics()
    writer = _FakeWriter()
    pub = _publisher(writer, metrics)
    pub.notify(0)
    task = asyncio.create_task(pub.run())
    try:
        await _wait_until(lambda: writer.costs == [0])
        await asyncio.sleep(0.05)
        assert writer.costs == [0]
        assert writer.attempts == [0]
        assert _count(metrics, "ok") == 1.0
    finally:
        await _stop(task)


async def test_notify_before_run_is_kept() -> None:
    metrics = build_worker_metrics()
    writer = _FakeWriter()
    pub = _publisher(writer, metrics)
    pub.notify(3)
    task = asyncio.create_task(pub.run())
    try:
        await _wait_until(lambda: writer.costs == [3])
    finally:
        await _stop(task)


async def test_one_write_per_change() -> None:
    metrics = build_worker_metrics()
    writer = _FakeWriter()
    pub = _publisher(writer, metrics)
    task = asyncio.create_task(pub.run())
    try:
        pub.notify(0)
        await _wait_until(lambda: writer.costs == [0])
        pub.notify(1)
        await _wait_until(lambda: writer.costs == [0, 1])
        pub.notify(2)
        await _wait_until(lambda: writer.costs == [0, 1, 2])
        assert _count(metrics, "ok") == 3.0
    finally:
        await _stop(task)


async def test_a_burst_coalesces_to_the_final_value() -> None:
    metrics = build_worker_metrics()
    gate = asyncio.Event()
    writer = _FakeWriter(gate=gate)
    pub = _publisher(writer, metrics)
    pub.notify(0)
    task = asyncio.create_task(pub.run())
    try:
        await _wait_until(lambda: writer.attempts == [0])
        pub.notify(1)
        pub.notify(2)
        pub.notify(3)
        gate.set()
        await _wait_until(lambda: writer.costs == [0, 3])
        await asyncio.sleep(0.05)
        assert writer.costs == [0, 3]
        assert writer.attempts == [0, 3]
    finally:
        await _stop(task)


async def test_the_same_value_gives_no_write() -> None:
    metrics = build_worker_metrics()
    writer = _FakeWriter()
    pub = _publisher(writer, metrics)
    task = asyncio.create_task(pub.run())
    try:
        pub.notify(2)
        await _wait_until(lambda: writer.costs == [2])
        pub.notify(2)
        await asyncio.sleep(0.05)
        assert writer.attempts == [2]
    finally:
        await _stop(task)


async def test_the_minimum_interval_is_kept() -> None:
    metrics = build_worker_metrics()
    writer = _FakeWriter()
    pub = _publisher(writer, metrics, min_interval_s=0.2)
    task = asyncio.create_task(pub.run())
    try:
        pub.notify(0)
        await _wait_until(lambda: writer.costs == [0])
        pub.notify(1)
        await _wait_until(lambda: writer.costs == [0, 1], timeout_s=2.0)
        assert writer.attempt_times[1] - writer.attempt_times[0] >= 0.19
    finally:
        await _stop(task)


async def test_a_failure_is_counted_and_retried() -> None:
    metrics = build_worker_metrics()
    writer = _FakeWriter(fail_times=2)
    pub = _publisher(writer, metrics)
    task = asyncio.create_task(pub.run())
    try:
        pub.notify(1)
        await _wait_until(lambda: writer.costs == [1])
        assert writer.attempts == [1, 1, 1]
        assert _count(metrics, "error") == 2.0
        assert _count(metrics, "ok") == 1.0
    finally:
        await _stop(task)


async def test_a_newer_value_replaces_a_failed_one() -> None:
    metrics = build_worker_metrics()
    writer = _FakeWriter(fail_costs=frozenset({1}))
    # The backoff timer cannot fire inside the test: only a new count can wake the retry.
    pub = _publisher(writer, metrics, retry_initial_s=10.0, retry_max_s=10.0)
    task = asyncio.create_task(pub.run())
    try:
        pub.notify(1)
        await _wait_until(lambda: writer.attempts == [1])
        pub.notify(2)
        await _wait_until(lambda: writer.costs == [2], timeout_s=2.0)
        assert writer.attempts == [1, 2]
    finally:
        await _stop(task)


async def test_a_writer_that_always_fails_never_makes_run_raise() -> None:
    metrics = build_worker_metrics()
    writer = _FakeWriter(always_fail=True)
    pub = _publisher(writer, metrics, retry_initial_s=0.001, retry_max_s=0.002)
    task = asyncio.create_task(pub.run())
    pub.notify(1)
    await _wait_until(lambda: len(writer.attempts) >= 5)
    assert not task.done()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert _count(metrics, "error") >= 5


async def test_the_retry_stops_after_a_good_write() -> None:
    metrics = build_worker_metrics()
    writer = _FakeWriter(fail_times=1)
    pub = _publisher(writer, metrics)
    task = asyncio.create_task(pub.run())
    try:
        pub.notify(4)
        await _wait_until(lambda: writer.costs == [4])
        await asyncio.sleep(0.1)
        assert writer.attempts == [4, 4]
    finally:
        await _stop(task)


async def test_aclose_closes_the_writer_and_hides_its_error() -> None:
    metrics = build_worker_metrics()
    writer = _FakeWriter(close_error=RuntimeError("close boom"))
    pub = _publisher(writer, metrics)
    await pub.aclose()
    assert writer.closed is True


async def test_the_write_counter_is_on_the_worker_registry() -> None:
    metrics = build_worker_metrics()
    writer = _FakeWriter()
    pub = _publisher(writer, metrics)
    task = asyncio.create_task(pub.run())
    try:
        pub.notify(0)
        await _wait_until(lambda: writer.costs == [0])
        assert _count(metrics, "ok") == 1.0
    finally:
        await _stop(task)
