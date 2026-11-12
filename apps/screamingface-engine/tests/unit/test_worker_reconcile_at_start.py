"""FEATURE OME-1314 D2 — a starting worker reconciles the consumers once, before the first pull.

The reconcile runs once in `Worker.run()`, before the claim loop pulls. It is never on the
subscription re-bind, so a rollout's old pods and new pods all write the same value, once.
"""

import asyncio

import pytest
from test_worker_claim import _FakePublisher, _FakeQueue, _wait_until, _worker

from screamingface_engine.runner_queue import RunQueue
from screamingface_engine.worker.loop import _ConsumerReconciler

pytestmark = pytest.mark.asyncio


class _ReconcilingQueue(_FakeQueue):
    def __init__(self) -> None:
        super().__init__()
        self.reconcile_calls = 0
        self.pulls_at_reconcile: int | None = None

    async def reconcile_consumers(self) -> int:
        self.reconcile_calls += 1
        if self.pulls_at_reconcile is None:
            self.pulls_at_reconcile = len(self.pull_calls)
        return 0


async def test_run_reconciles_once_before_the_first_pull() -> None:
    queue = _ReconcilingQueue()
    worker = _worker(queue, _FakePublisher(), slots=1)
    task = asyncio.create_task(worker.run())

    await _wait_until(lambda: len(queue.pull_calls) >= 3)
    worker._draining.set()  # noqa: SLF001
    await asyncio.wait_for(task, timeout=5.0)

    assert queue.reconcile_calls == 1
    assert queue.pulls_at_reconcile == 0


async def test_a_queue_without_reconcile_still_runs() -> None:
    queue = _FakeQueue()
    worker = _worker(queue, _FakePublisher(), slots=1)
    task = asyncio.create_task(worker.run())

    await _wait_until(lambda: len(queue.pull_calls) >= 1)
    worker._draining.set()  # noqa: SLF001
    await asyncio.wait_for(task, timeout=5.0)

    assert len(queue.pull_calls) >= 1  # wait_for re-raises if run() failed


def test_the_real_run_queue_is_a_reconciler() -> None:
    assert isinstance(RunQueue("nats://unused:4222"), _ConsumerReconciler)
    assert not isinstance(_FakeQueue(), _ConsumerReconciler)
