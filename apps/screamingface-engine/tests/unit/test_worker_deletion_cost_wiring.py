"""OME-1931 spec D2/D3 wiring: the worker feeds the pod-deletion-cost publisher from its busy
slot count, writes once at start, stops the writer at exit, and never lets a failing writer
change a run.

asyncio is strict here, so every async test carries its own `@pytest.mark.asyncio`: the file
also has sync settings tests, so there is no module-level pytestmark.
"""

import asyncio
import json
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest

from screamingface_engine import job_env
from screamingface_engine.config import Settings
from screamingface_engine.worker.deletion_cost import DeletionCostPublisher
from screamingface_engine.worker.loop import Worker
from screamingface_engine.worker.metrics import WorkerMetrics, build_worker_metrics


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
    def __init__(self) -> None:
        self.published: list[Any] = []

    async def last_frame(self, topic: str) -> None:
        return None

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


class _HangingProcess(_FakeProcess):
    """A child that stays alive until released."""

    def __init__(self) -> None:
        super().__init__(exit_code=0)
        self._released = asyncio.Event()

    async def wait(self) -> int:
        await self._released.wait()
        return self.returncode or 0

    def release(self) -> None:
        self._released.set()


class _FakeQueue:
    """A queue that returns the given batches, then empty batches."""

    def __init__(self, batches: list[list[_FakeMsg]] | None = None) -> None:
        self._batches = list(batches or [])

    async def release_held(self) -> int:
        return 0

    async def pull(self, batch: int, timeout_s: float) -> list[_FakeMsg]:
        if self._batches:
            return self._batches.pop(0)
        await asyncio.sleep(timeout_s)
        return []


def _message(topic: str) -> bytes:
    return json.dumps(
        {
            job_env.TOPIC: topic,
            job_env.EXPRESSION: "'hi'",
            job_env.JOB_DEADLINE_S: "60",
            job_env.STREAM_GRACE_S: "60",
        }
    ).encode()


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


class _FakeWriter:
    """Records the costs the publisher writes; can fail every write."""

    def __init__(self, *, always_fail: bool = False) -> None:
        self._always_fail = always_fail
        self.costs: list[int] = []
        self.attempts = 0
        self.closed = False

    async def write(self, cost: int) -> None:
        self.attempts += 1
        if self._always_fail:
            raise RuntimeError("no route to the API server")
        self.costs.append(cost)

    async def aclose(self) -> None:
        self.closed = True


class _RecordingPublisher(DeletionCostPublisher):
    """The real publisher with fast timings, plus a record of the calls the worker makes."""

    def __init__(self, writer: _FakeWriter, metrics: WorkerMetrics) -> None:
        super().__init__(
            writer,
            writes=metrics.deletion_cost_writes,
            min_interval_s=0.0,
            retry_initial_s=0.01,
            retry_max_s=0.02,
        )
        self.notified: list[int] = []
        self.run_started = False
        self.run_cancelled = False
        self.closed = False

    def notify(self, busy: int) -> None:
        self.notified.append(busy)
        super().notify(busy)

    async def run(self) -> None:
        self.run_started = True
        try:
            await super().run()
        except asyncio.CancelledError:
            self.run_cancelled = True
            raise

    async def aclose(self) -> None:
        self.closed = True
        await super().aclose()


def _worker(
    queue: _FakeQueue,
    publisher: _FakePublisher,
    metrics: WorkerMetrics,
    spawn: Any,
    deletion_cost: DeletionCostPublisher | None = None,
) -> Worker:
    return Worker(
        queue=queue,
        publisher=publisher,
        slots=2,
        drain_grace_s=0.05,
        io_capacity=4,
        memory_budget_bytes=1024**3,
        pull_timeout_s=0.05,
        spawn=spawn,
        metrics=metrics,
        deletion_cost=deletion_cost,
    )


async def _run_one(
    deletion_cost: DeletionCostPublisher | None, metrics: WorkerMetrics
) -> tuple[list[Any], _FakeMsg]:
    msg = _FakeMsg(_message("t-wire"))
    publisher = _FakePublisher()
    worker = _worker(
        _FakeQueue(batches=[[msg]]),
        publisher,
        metrics,
        _async_spawn(_FakeProcess(exit_code=1)),
        deletion_cost,
    )
    task = asyncio.create_task(worker.run())
    await _wait_until(lambda: msg.acked)
    await _wait_until(lambda: not worker._active)  # noqa: SLF001
    worker._draining.set()  # noqa: SLF001
    await asyncio.wait_for(task, timeout=5.0)
    return publisher.published, msg


def _frames(published: list[Any]) -> list[tuple[str, Any]]:
    return [
        (type(e).__name__, getattr(getattr(e, "data", None), "status", None)) for e in published
    ]


@pytest.mark.asyncio
async def test_notify_gets_the_busy_count_after_a_claim_and_after_a_run_ends() -> None:
    metrics = build_worker_metrics()
    proc = _HangingProcess()
    pub = _RecordingPublisher(_FakeWriter(), metrics)
    worker = _worker(
        _FakeQueue(batches=[[_FakeMsg(_message("t-busy"))]]),
        _FakePublisher(),
        metrics,
        _async_spawn(proc),
        pub,
    )

    async with asyncio.TaskGroup() as tg:
        claim = tg.create_task(worker._claim_loop(tg))  # noqa: SLF001
        await _wait_until(lambda: bool(worker._supervisor._children))  # noqa: SLF001
        assert pub.notified[0] == 1
        proc.release()
        await _wait_until(lambda: pub.notified[-1] == 0)
        worker._draining.set()  # noqa: SLF001
        await claim


@pytest.mark.asyncio
async def test_no_notify_after_the_drain_signal() -> None:
    metrics = build_worker_metrics()
    proc = _HangingProcess()
    pub = _RecordingPublisher(_FakeWriter(), metrics)
    worker = _worker(
        _FakeQueue(batches=[[_FakeMsg(_message("t-drain"))]]),
        _FakePublisher(),
        metrics,
        _async_spawn(proc),
        pub,
    )

    async with asyncio.TaskGroup() as tg:
        claim = tg.create_task(worker._claim_loop(tg))  # noqa: SLF001
        await _wait_until(lambda: bool(worker._supervisor._children))  # noqa: SLF001
        worker._draining.set()  # noqa: SLF001
        seen = len(pub.notified)
        proc.release()
        await claim

    assert len(pub.notified) == seen


@pytest.mark.asyncio
async def test_the_worker_writes_at_start_and_stops_the_writer_at_exit() -> None:
    metrics = build_worker_metrics()
    writer = _FakeWriter()
    pub = _RecordingPublisher(writer, metrics)
    msg = _FakeMsg(_message("t-start"))
    worker = _worker(
        _FakeQueue(batches=[[msg]]),
        _FakePublisher(),
        metrics,
        _async_spawn(_FakeProcess(exit_code=1)),
        pub,
    )

    task = asyncio.create_task(worker.run())
    await _wait_until(lambda: msg.acked)
    await _wait_until(lambda: not worker._active)  # noqa: SLF001
    await _wait_until(lambda: bool(writer.costs) and writer.costs[-1] == 0)
    worker._draining.set()  # noqa: SLF001
    await asyncio.wait_for(task, timeout=5.0)

    # The start write (spec D2) happens before any claim.
    assert pub.notified[0] == 0
    assert 1 in pub.notified
    assert pub.run_started
    assert pub.run_cancelled
    assert pub.closed
    assert writer.closed


@pytest.mark.asyncio
async def test_a_writer_that_always_fails_does_not_change_the_run() -> None:
    baseline_frames, baseline_msg = await _run_one(None, build_worker_metrics())

    metrics = build_worker_metrics()
    writer = _FakeWriter(always_fail=True)
    failing_frames, failing_msg = await _run_one(_RecordingPublisher(writer, metrics), metrics)

    assert _frames(failing_frames) == _frames(baseline_frames)
    assert baseline_msg.acked
    assert failing_msg.acked
    assert writer.attempts >= 1
    error_writes = metrics.registry.get_sample_value(
        "screamingface_engine_worker_deletion_cost_writes_total", {"outcome": "error"}
    )
    assert error_writes is not None
    assert error_writes >= 1


@pytest.mark.asyncio
async def test_a_worker_without_a_publisher_runs_as_before() -> None:
    metrics = build_worker_metrics()
    _, msg = await _run_one(None, metrics)

    assert msg.acked
    assert metrics.registry.get_sample_value("screamingface_engine_worker_slots_busy") == 0.0
    assert (
        metrics.registry.get_sample_value(
            "screamingface_engine_worker_deletion_cost_writes_total", {"outcome": "ok"}
        )
        is None
    )


def test_the_settings_default_to_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("URL4_CLOUD_WORKER_DELETION_COST_ENABLED", raising=False)
    monkeypatch.delenv("URL4_CLOUD_WORKER_POD_NAME", raising=False)
    monkeypatch.delenv("URL4_CLOUD_WORKER_POD_NAMESPACE", raising=False)

    s = Settings()

    assert s.worker_deletion_cost_enabled is False
    assert s.worker_pod_name is None
    assert s.worker_pod_namespace is None


def test_the_env_names_map_to_the_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("URL4_CLOUD_WORKER_DELETION_COST_ENABLED", "true")
    monkeypatch.setenv("URL4_CLOUD_WORKER_POD_NAME", "url4-cloud-runner-abc")
    monkeypatch.setenv("URL4_CLOUD_WORKER_POD_NAMESPACE", "sf-fusion")

    s = Settings()

    assert s.worker_deletion_cost_enabled is True
    assert s.worker_pod_name == "url4-cloud-runner-abc"
    assert s.worker_pod_namespace == "sf-fusion"
