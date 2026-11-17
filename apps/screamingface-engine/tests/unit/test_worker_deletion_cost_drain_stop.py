"""OME-1931 spec D2: the pod-deletion-cost writer task stops at the drain signal, so a retry never
goes out during the drain; and the composition helper builds the publisher only when the writer
exists. No network.

asyncio is strict here, so every async test carries its own `@pytest.mark.asyncio`: the file
also has sync tests, so there is no module-level pytestmark.
"""

import asyncio
import contextlib
import json
import logging
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest

from screamingface_engine import job_env
from screamingface_engine.config import Settings
from screamingface_engine.worker.deletion_cost import DeletionCostPublisher
from screamingface_engine.worker.loop import Worker, build_deletion_cost_publisher
from screamingface_engine.worker.metrics import build_worker_metrics

_KUBE_POD_LOGGER = "screamingface_engine.worker.kube_pod"


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


def _kube_pod_warnings(caplog: pytest.LogCaptureFixture) -> list[logging.LogRecord]:
    return [
        record
        for record in caplog.records
        if record.name == _KUBE_POD_LOGGER and record.levelno == logging.WARNING
    ]


@pytest.mark.asyncio
async def test_a_failing_writer_makes_no_attempt_after_the_drain_signal() -> None:
    metrics = build_worker_metrics()
    writer = _FakeWriter(always_fail=True)
    pub = DeletionCostPublisher(
        writer,
        writes=metrics.deletion_cost_writes,
        min_interval_s=0.0,
        retry_initial_s=0.01,
        retry_max_s=0.02,
    )
    proc = _HangingProcess()
    msg = _FakeMsg(_message("t-drain-stop"))
    worker = Worker(
        queue=_FakeQueue(batches=[[msg]]),
        publisher=_FakePublisher(),
        slots=2,
        drain_grace_s=5.0,
        io_capacity=4,
        memory_budget_bytes=1024**3,
        pull_timeout_s=0.05,
        spawn=_async_spawn(proc),
        metrics=metrics,
        deletion_cost=pub,
    )
    run_task = asyncio.create_task(worker.run())
    await _wait_until(lambda: bool(worker._supervisor._children))  # noqa: SLF001
    # The retries are active before the drain signal.
    await _wait_until(lambda: writer.attempts >= 3)

    worker._draining.set()  # noqa: SLF001
    # The claim loop sees the signal within one pull timeout (0.05 s).
    await asyncio.sleep(0.2)
    seen = writer.attempts
    await asyncio.sleep(0.3)

    assert writer.attempts == seen
    # The drain still waits for the hanging run, so without the fix the writer would still retry.
    assert not run_task.done()

    proc.release()
    await asyncio.wait_for(run_task, timeout=5.0)
    assert writer.closed


def test_the_composition_helper_gives_none_when_the_feature_is_off(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG)

    result = build_deletion_cost_publisher(
        Settings(worker_deletion_cost_enabled=False), {}, build_worker_metrics()
    )

    assert result is None
    assert _kube_pod_warnings(caplog) == []


def test_the_composition_helper_gives_none_and_one_warning_when_a_prerequisite_is_missing(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG)
    settings = Settings(
        worker_deletion_cost_enabled=True,
        worker_pod_name="url4-cloud-runner-abc",
        worker_pod_namespace="sf-fusion",
    )

    # No KUBERNETES_SERVICE_HOST, so the builder stops before any file access.
    result = build_deletion_cost_publisher(settings, {}, build_worker_metrics())

    assert result is None
    warnings = _kube_pod_warnings(caplog)
    assert len(warnings) == 1
    assert "KUBERNETES_SERVICE_HOST" in warnings[0].getMessage()


@pytest.mark.asyncio
async def test_the_composition_helper_wires_the_writer_to_the_worker_counter() -> None:
    metrics = build_worker_metrics()
    writer = _FakeWriter()

    pub = build_deletion_cost_publisher(
        Settings(worker_deletion_cost_enabled=True),
        {},
        metrics,
        build_writer=lambda settings, environ: writer,
    )

    assert isinstance(pub, DeletionCostPublisher)
    task = asyncio.create_task(pub.run())
    try:
        pub.notify(3)
        await _wait_until(lambda: writer.costs == [3])
        assert (
            metrics.registry.get_sample_value(
                "screamingface_engine_worker_deletion_cost_writes_total", {"outcome": "ok"}
            )
            == 1.0
        )
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
