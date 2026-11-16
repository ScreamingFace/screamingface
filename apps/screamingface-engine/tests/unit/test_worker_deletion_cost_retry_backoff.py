"""OME-1931 spec D3: the retry backoff of the pod-deletion-cost publisher doubles and stops at its
maximum, and a count that arrived during a good write does not skip the backoff of the next failed
write. No network: the writer is a fake.
"""

import asyncio
import contextlib

import pytest

from screamingface_engine.worker.deletion_cost import DeletionCostPublisher
from screamingface_engine.worker.metrics import build_worker_metrics

pytestmark = pytest.mark.asyncio


class _ScriptedWriter:
    def __init__(
        self,
        *,
        fail_costs: frozenset[int] = frozenset(),
        always_fail: bool = False,
        first_gate: asyncio.Event | None = None,
    ) -> None:
        self._fail_costs = fail_costs
        self._always_fail = always_fail
        self._first_gate = first_gate
        self.attempts: list[int] = []
        self.attempt_times: list[float] = []
        self.costs: list[int] = []

    async def write(self, cost: int) -> None:
        self.attempts.append(cost)
        self.attempt_times.append(asyncio.get_running_loop().time())
        if self._first_gate is not None and len(self.attempts) == 1:
            await self._first_gate.wait()
        if self._always_fail or cost in self._fail_costs:
            raise RuntimeError("boom")
        self.costs.append(cost)

    async def aclose(self) -> None:
        pass


async def _wait_until(predicate, timeout_s: float = 2.0) -> None:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout_s
    while not predicate():
        if loop.time() > deadline:
            raise AssertionError("condition not met in time")
        await asyncio.sleep(0.005)


async def _stop(task: asyncio.Task) -> None:
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task


async def test_a_count_during_a_good_write_does_not_skip_the_next_backoff() -> None:
    metrics = build_worker_metrics()
    gate = asyncio.Event()
    writer = _ScriptedWriter(fail_costs=frozenset({2}), first_gate=gate)
    pub = DeletionCostPublisher(
        writer,
        writes=metrics.deletion_cost_writes,
        min_interval_s=0.0,
        retry_initial_s=0.3,
        retry_max_s=0.3,
    )
    task = asyncio.create_task(pub.run())
    try:
        pub.notify(1)
        await _wait_until(lambda: writer.attempts == [1])
        # Arrives while write(1) is in flight: must not wake the backoff of write(2).
        pub.notify(2)
        gate.set()
        await _wait_until(lambda: len(writer.attempts) >= 3, timeout_s=2.0)
        assert writer.attempts[:3] == [1, 2, 2]
        assert writer.costs == [1]
        assert writer.attempt_times[2] - writer.attempt_times[1] >= 0.25
    finally:
        await _stop(task)


async def test_the_backoff_doubles_and_stops_at_the_maximum() -> None:
    metrics = build_worker_metrics()
    writer = _ScriptedWriter(always_fail=True)
    pub = DeletionCostPublisher(
        writer,
        writes=metrics.deletion_cost_writes,
        min_interval_s=0.0,
        retry_initial_s=0.04,
        retry_max_s=0.08,
    )
    task = asyncio.create_task(pub.run())
    try:
        pub.notify(1)
        await _wait_until(lambda: len(writer.attempts) >= 7, timeout_s=3.0)
        t = writer.attempt_times[:7]
        gaps = [b - a for a, b in zip(t, t[1:])]
        # Expected waits: 0.04, 0.08, 0.08, 0.08, 0.08, 0.08 (uncapped doubling: 0.16, 0.32, ...).
        assert gaps[0] >= 0.035
        assert gaps[1] >= 0.075
        assert all(g >= 0.075 for g in gaps[2:])
        assert all(g < 0.15 for g in gaps[2:])
    finally:
        await _stop(task)
