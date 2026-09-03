"""The worker's Prometheus metrics (OME-1092): slots, claim latency, run duration,
redeliveries, and child exit codes.

The worker is a separate process from the App, so its metrics live on their own scrape
endpoint (`worker_metrics_port`), not on the App's /metrics. These tests pin the metric
handles and the instrumentation points: the slot gauges track the pool, the supervisor
records redeliveries and child exit codes (137 = OOM), and everything lives on a
per-process registry so tests never collide.
"""

import asyncio
import json
import time
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest

from screamingface_engine import job_env
from screamingface_engine.worker.loop import Worker
from screamingface_engine.worker.metrics import build_worker_metrics
from screamingface_engine.worker.supervisor import RunSupervisor
from url4.streaming.protocol import TerminatedData, TerminatedEvent, source_for

pytestmark = pytest.mark.asyncio


class _FakeMsg:
    def __init__(self, data: bytes, *, num_delivered: int = 1) -> None:
        self.data = data
        self.metadata = SimpleNamespace(timestamp=datetime.now(UTC), num_delivered=num_delivered)
        self.acked = False

    async def ack(self) -> None:
        self.acked = True

    async def in_progress(self) -> None:
        pass


class _FakePublisher:
    def __init__(self, last_frame: TerminatedEvent | None = None) -> None:
        self._last_frame = last_frame
        self.published: list[Any] = []

    async def last_frame(self, topic: str) -> TerminatedEvent | None:
        return self._last_frame

    async def ensure_stream(self, topic: str) -> None:
        pass

    async def publish(self, topic: str, event: Any) -> None:
        self.published.append(event)

    async def flush(self) -> None:
        pass


class _FakeProcess:
    def __init__(self, exit_code: int) -> None:
        self.returncode: int | None = exit_code
        self.stdout = None
        self.stderr = None

    async def wait(self) -> int:
        return self.returncode or 0

    def terminate(self) -> None:
        pass

    def kill(self) -> None:
        pass


def _message(topic: str) -> bytes:
    return json.dumps(
        {
            job_env.TOPIC: topic,
            job_env.EXPRESSION: "'hi'",
            job_env.JOB_DEADLINE_S: "60",
            job_env.STREAM_GRACE_S: "60",
        }
    ).encode()


def _terminal(topic: str) -> TerminatedEvent:
    return TerminatedEvent(
        id="t",
        source=source_for(topic),
        subject=topic,
        data=TerminatedData(status="succeeded"),  # type: ignore[arg-type]
    )


def _sample_values(metrics: Any, name: str) -> list[float]:
    return [
        sample.value
        for metric in metrics.registry.collect()
        for sample in metric.samples
        if sample.name == name
    ]


def test_the_worker_metrics_live_on_their_own_registry() -> None:
    metrics = build_worker_metrics()

    names = {sample.name for metric in metrics.registry.collect() for sample in metric.samples}
    assert "screamingface_engine_worker_slots_total" in names
    assert "screamingface_engine_worker_slots_busy" in names
    assert "screamingface_engine_worker_claim_latency_s_count" in names
    assert "screamingface_engine_worker_run_duration_s_count" in names
    assert "screamingface_engine_worker_redeliveries_total" in names
    assert "screamingface_engine_worker_started_total" in names
    assert "screamingface_engine_worker_drains_total" in names
    # The labeled counter has no samples until a label value is set; its shape is pinned
    # on the handle itself.
    assert metrics.child_exit_codes._labelnames == ("code",)  # noqa: SLF001


def test_the_worker_sets_its_slot_total_at_construction() -> None:
    metrics = build_worker_metrics()
    Worker(
        queue=_FakeQueue(),
        publisher=_FakePublisher(),
        slots=4,
        drain_grace_s=0.1,
        io_capacity=4,
        memory_budget_bytes=1024**3,
        metrics=metrics,
    )

    assert _sample_values(metrics, "screamingface_engine_worker_slots_total") == [4.0]


async def _wait_until(predicate: Any, timeout_s: float = 2.0) -> None:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout_s
    while not predicate():
        if loop.time() > deadline:
            raise AssertionError("condition not met in time")
        await asyncio.sleep(0.01)


def _async_spawn(proc: _FakeProcess) -> Any:
    """A spawn callable that returns a fixed fake process."""

    async def _spawn(*args: Any, **kwargs: Any) -> _FakeProcess:
        return proc

    return _spawn


@pytest.mark.asyncio
async def test_a_claimed_run_records_redelivery_and_the_child_exit_code() -> None:
    """A redelivered message (num_delivered > 1) and a child that exits 137 (OOM) must both
    be visible on the worker's metrics."""
    metrics = build_worker_metrics()
    publisher = _FakePublisher()
    supervisor = RunSupervisor(
        publisher=publisher,
        spawn=_async_spawn(_FakeProcess(exit_code=137)),
        memory_budget_bytes=1024**3,
        io_capacity=4,
        draining=asyncio.Event(),
        terminating=asyncio.Event(),
        children=set(),
        children_by_topic={},
        cancelled=set(),
        metrics=metrics,
    )

    await supervisor.supervise(_FakeMsg(_message("t-oom"), num_delivered=2))

    assert _sample_values(metrics, "screamingface_engine_worker_redeliveries_total") == [1.0]
    exit_samples = [
        sample
        for metric in metrics.registry.collect()
        for sample in metric.samples
        if sample.name == "screamingface_engine_worker_child_exit_codes_total"
    ]
    assert {s.labels["code"] for s in exit_samples} == {"137"}
    assert sum(s.value for s in exit_samples) == 1.0
    # The run-duration histogram observed one run.
    assert _sample_values(metrics, "screamingface_engine_worker_run_duration_s_count") == [1.0]


@pytest.mark.asyncio
async def test_a_first_delivery_is_not_counted_as_a_redelivery() -> None:
    metrics = build_worker_metrics()
    publisher = _FakePublisher(last_frame=_terminal("t-first"))
    supervisor = RunSupervisor(
        publisher=publisher,
        spawn=_async_spawn(_FakeProcess(exit_code=0)),
        memory_budget_bytes=1024**3,
        io_capacity=4,
        draining=asyncio.Event(),
        terminating=asyncio.Event(),
        children=set(),
        children_by_topic={},
        cancelled=set(),
        metrics=metrics,
    )

    await supervisor.supervise(_FakeMsg(_message("t-first"), num_delivered=1))

    assert _sample_values(metrics, "screamingface_engine_worker_redeliveries_total") == [0.0]


class _FakeQueue:
    """A queue that returns one message, then empty batches."""

    def __init__(self, batches: list[list[_FakeMsg]] | None = None) -> None:
        self._batches = list(batches or [])

    async def pull(self, batch: int, timeout_s: float) -> list[_FakeMsg]:
        if self._batches:
            return self._batches.pop(0)
        await asyncio.sleep(timeout_s)
        return []


@pytest.mark.asyncio
async def test_the_claim_loop_tracks_busy_slots() -> None:
    metrics = build_worker_metrics()
    queue = _FakeQueue(batches=[[_FakeMsg(_message("t-busy"))]])
    worker = Worker(
        queue=queue,
        publisher=_FakePublisher(),
        slots=2,
        drain_grace_s=0.05,
        io_capacity=4,
        memory_budget_bytes=1024**3,
        pull_timeout_s=0.05,
        spawn=_async_spawn(_FakeProcess(exit_code=0)),
        metrics=metrics,
    )

    async with asyncio.TaskGroup() as tg:
        claim = tg.create_task(worker._claim_loop(tg))  # noqa: SLF001
        await asyncio.sleep(0.1)
        worker._draining.set()  # noqa: SLF001
        await claim

    # The claim loop observed at least one pull (the claim-latency histogram has a sample).
    assert _sample_values(metrics, "screamingface_engine_worker_claim_latency_s_count")[0] >= 1.0
    assert _sample_values(metrics, "screamingface_engine_worker_drains_total") == [1.0]


@pytest.mark.asyncio
class _HangingProcess(_FakeProcess):
    """A child that stays alive until released — the mid-run state the busy-slot gauge
    must reflect."""

    def __init__(self) -> None:
        super().__init__(exit_code=0)
        self._released = asyncio.Event()

    async def wait(self) -> int:
        await self._released.wait()
        return self.returncode or 0

    def release(self) -> None:
        self._released.set()


@pytest.mark.asyncio
async def test_the_busy_slot_gauge_counts_the_just_claimed_batch() -> None:
    """The gauge used to be set BEFORE the newly-claimed tasks registered — a scrape in
    that window under-reported utilization by the just-claimed batch, biasing capacity
    dashboards LOW at the moments of highest throughput. It now reflects the post-claim
    state: while a claimed run is in flight, the gauge shows it."""
    metrics = build_worker_metrics()
    proc = _HangingProcess()
    queue = _FakeQueue(batches=[[_FakeMsg(_message("t-busy2"))]])
    worker = Worker(
        queue=queue,
        publisher=_FakePublisher(),
        slots=2,
        drain_grace_s=0.05,
        io_capacity=4,
        memory_budget_bytes=1024**3,
        pull_timeout_s=0.05,
        spawn=_async_spawn(proc),
        metrics=metrics,
    )

    async with asyncio.TaskGroup() as tg:
        claim = tg.create_task(worker._claim_loop(tg))  # noqa: SLF001
        await _wait_until(lambda: bool(worker._supervisor._children))  # noqa: SLF001
        assert _sample_values(metrics, "screamingface_engine_worker_slots_busy") == [1.0]
        proc.release()
        worker._draining.set()  # noqa: SLF001
        await claim


@pytest.mark.asyncio
async def test_the_claim_loop_stamps_its_last_attempt() -> None:
    """The loop-liveness signal (review follow-up): a wedged claim loop with a live scrape
    thread passes a /metrics liveness probe, so the probe is backed by a gauge that stops
    advancing when the loop is stuck. Every pull attempt stamps it."""
    metrics = build_worker_metrics()
    queue = _FakeQueue(batches=[[_FakeMsg(_message("t-attempt"))]])
    worker = Worker(
        queue=queue,
        publisher=_FakePublisher(),
        slots=2,
        drain_grace_s=0.05,
        io_capacity=4,
        memory_budget_bytes=1024**3,
        pull_timeout_s=0.05,
        spawn=_async_spawn(_FakeProcess(exit_code=0)),
        metrics=metrics,
    )

    async with asyncio.TaskGroup() as tg:
        claim = tg.create_task(worker._claim_loop(tg))  # noqa: SLF001
        name = "screamingface_engine_worker_last_claim_attempt_unix_seconds"

        def _stamped() -> bool:
            values = _sample_values(metrics, name)
            return bool(values) and values[0] > 0

        await _wait_until(_stamped)
        worker._draining.set()  # noqa: SLF001
        await claim

    stamped = _sample_values(metrics, name)[0]
    assert time.time() - stamped < 5.0


async def test_a_pull_failure_increments_the_failure_counter() -> None:
    """V-5: the liveness stamp advances on every pull ATTEMPT, so a claim loop whose
    pulls keep failing still looks alive — the failure counter is the operator's signal
    that the worker's broker path needs attention. A caught pull error must increment it
    and the loop must keep going."""
    import nats

    metrics = build_worker_metrics()

    class _FailingOnceQueue(_FakeQueue):
        def __init__(self) -> None:
            super().__init__(batches=[[_FakeMsg(_message("t-fail"))]])
            self.failed = False

        async def pull(self, batch: int, timeout_s: float) -> list[_FakeMsg]:
            if not self.failed:
                self.failed = True
                raise nats.errors.Error("transient broker blip")
            return await super().pull(batch, timeout_s)

    queue = _FailingOnceQueue()
    worker = Worker(
        queue=queue,
        publisher=_FakePublisher(),
        slots=2,
        drain_grace_s=0.05,
        io_capacity=4,
        memory_budget_bytes=1024**3,
        pull_timeout_s=0.05,
        spawn=_async_spawn(_FakeProcess(exit_code=0)),
        metrics=metrics,
    )

    async with asyncio.TaskGroup() as tg:
        claim = tg.create_task(worker._claim_loop(tg))  # noqa: SLF001
        name = "screamingface_engine_worker_pull_failures_total"

        def _counted() -> bool:
            values = _sample_values(metrics, name)
            return bool(values) and values[0] >= 1

        await _wait_until(_counted)
        worker._draining.set()  # noqa: SLF001
        await claim

    assert _sample_values(metrics, name)[0] == 1, "the caught failure must be counted"
