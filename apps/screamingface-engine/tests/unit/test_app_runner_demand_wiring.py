"""How the runner-demand sampler is wired into the App: its settings, when it exists, what it
samples at startup, and how its one process-wide task starts and stops.

FEATURE: runner pool autoscaling on claimable queue demand (spec D2).
"""

import asyncio
import time
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import Any

import pytest
from _fakes import RecordingJobRunner
from fastapi import FastAPI
from fastapi.testclient import TestClient

from screamingface_engine.adapters.queue_runner import QueueJobRunner
from screamingface_engine.app import _install_periodic, create_app
from screamingface_engine.config import Settings
from screamingface_engine.runner_demand import DemandSource, RunnerDemandSampler
from screamingface_engine.runner_queue import BucketReading
from screamingface_engine.testing import InMemoryEventStream

SECRET = "runner-demand-wiring-secret-0123456789abcdef"
T0 = datetime(2026, 11, 10, 12, 0, 0, tzinfo=UTC)
READINGS = [BucketReading(4, 4, 4), BucketReading(4, 0, 4), BucketReading(0, 1, 4), None]


class _DemandRunner(RecordingJobRunner):
    """A queue-backed fake: it answers `bucket_readings()` and counts the reads."""

    def __init__(self, error: Exception | None = None) -> None:
        super().__init__()
        self.error = error
        self.calls = 0

    async def bucket_readings(self) -> list[BucketReading | None]:
        self.calls += 1
        if self.error is not None:
            raise self.error
        return list(READINGS)


def _app(
    *,
    sample_s: float = 5.0,
    stale_s: float = 30.0,
    job_runner: RecordingJobRunner | None = None,
) -> FastAPI:
    settings = Settings(
        jwt_secret=SECRET, runner_demand_sample_s=sample_s, runner_demand_stale_s=stale_s
    )
    return create_app(
        settings, stream=InMemoryEventStream(), job_runner=job_runner, clock=lambda: T0
    )


def _wait_until(predicate: Callable[[], bool], timeout_s: float = 2.0) -> None:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.01)
    raise AssertionError("condition not met in time")


class _FakeQueue:
    def __init__(self, *, depth: int = 0, oldest_age: float | None = None) -> None:
        self._depth = depth
        self._oldest_age = oldest_age

    async def publish(
        self, message: bytes, *, identity: Mapping[str, str] | None = None, enqueued_at: Any = None
    ) -> None:
        raise NotImplementedError

    async def depth(self) -> int:
        return self._depth

    async def oldest_age(self) -> float | None:
        return self._oldest_age


class _FakePublisher:
    async def last_frame(self, topic: str) -> None:
        return None

    async def stream_exists(self, topic: str) -> bool:
        return False

    async def ensure_stream(self, topic: str) -> None:
        pass

    async def publish(self, topic: str, event: object) -> None:
        pass

    async def flush(self) -> None:
        pass


class _FakeControl:
    async def request(self, subject: str, payload: bytes, *, timeout: float) -> object:
        raise TimeoutError


def test_the_defaults_sample_every_five_seconds_and_go_stale_after_thirty() -> None:
    s = Settings(jwt_secret=SECRET)

    assert s.runner_demand_sample_s == 5.0
    assert s.runner_demand_stale_s == 30.0


def test_the_interval_is_read_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("URL4_CLOUD_RUNNER_DEMAND_SAMPLE_S", "10")

    assert Settings(jwt_secret=SECRET).runner_demand_sample_s == 10.0


def test_a_stale_window_under_two_samples_is_refused() -> None:
    with pytest.raises(ValueError, match="runner_demand_stale_s"):
        Settings(jwt_secret=SECRET, runner_demand_sample_s=20.0, runner_demand_stale_s=30.0)


def test_a_stale_window_of_exactly_two_samples_is_accepted() -> None:
    Settings(jwt_secret=SECRET, runner_demand_sample_s=15.0, runner_demand_stale_s=30.0)


def test_a_disabled_sampler_accepts_any_positive_stale_window() -> None:
    Settings(jwt_secret=SECRET, runner_demand_sample_s=0.0, runner_demand_stale_s=1.0)


def test_a_negative_interval_or_a_zero_stale_window_is_refused() -> None:
    with pytest.raises(ValueError):
        Settings(jwt_secret=SECRET, runner_demand_sample_s=-1.0)
    with pytest.raises(ValueError):
        Settings(jwt_secret=SECRET, runner_demand_stale_s=0.0)


def test_a_demand_source_runner_gets_a_sampler() -> None:
    app = _app(job_runner=_DemandRunner())

    assert isinstance(app.state.runner_demand, RunnerDemandSampler)
    assert app.state.runner_demand.stale_s == 30.0


def test_a_real_queue_runner_is_a_demand_source() -> None:
    runner = QueueJobRunner(
        queue=_FakeQueue(),
        publisher=_FakePublisher(),
        control=_FakeControl(),
        clock=lambda: T0,
        capability_lifetime_s=100.0,
    )

    assert isinstance(runner, DemandSource)


def test_a_zero_interval_disables_the_sampler() -> None:
    assert _app(sample_s=0.0, job_runner=_DemandRunner()).state.runner_demand is None


def test_a_runner_without_bucket_readings_gets_no_sampler() -> None:
    assert _app(job_runner=RecordingJobRunner()).state.runner_demand is None


def test_a_stream_only_app_gets_no_sampler_and_no_task() -> None:
    app = _app(job_runner=None)

    with TestClient(app):
        assert app.state.runner_demand is None
        assert app.state.runner_demand_task is None


def test_the_sampler_samples_once_at_startup() -> None:
    runner = _DemandRunner()
    app = _app(sample_s=60.0, stale_s=120.0, job_runner=runner)

    with TestClient(app):
        _wait_until(lambda: runner.calls >= 1)
        assert app.state.runner_demand.snapshot() is not None
        task = app.state.runner_demand_task
        assert isinstance(task, asyncio.Task)
        assert not task.done()

    assert app.state.runner_demand_task.done()


def test_a_failed_startup_sample_keeps_the_task_alive() -> None:
    runner = _DemandRunner(error=RuntimeError("broker down"))
    app = _app(sample_s=60.0, stale_s=120.0, job_runner=runner)

    with TestClient(app):
        _wait_until(lambda: runner.calls >= 1)
        assert app.state.runner_demand.snapshot() is None
        assert not app.state.runner_demand_task.done()


def test_the_endpoint_serves_the_startup_sample() -> None:
    runner = _DemandRunner()
    app = _app(sample_s=60.0, stale_s=120.0, job_runner=runner)

    with TestClient(app) as client:
        _wait_until(lambda: app.state.runner_demand.snapshot() is not None)
        r = client.get("/runner-demand")

    assert r.status_code == 200
    assert r.json()["demand"] == 9
    assert r.json()["age_s"] == 0.0


def test_the_metrics_scrape_exports_the_demand_gauges() -> None:
    runner = _DemandRunner()
    app = _app(sample_s=60.0, stale_s=120.0, job_runner=runner)

    with TestClient(app) as client:
        _wait_until(lambda: app.state.runner_demand.snapshot() is not None)
        assert "screamingface_engine_runner_demand 9.0" in client.get("/metrics").text


def test_install_periodic_does_not_sweep_at_start_by_default() -> None:
    app = FastAPI()
    calls: list[int] = []

    async def _sweep() -> None:
        calls.append(1)

    _install_periodic(
        app,
        task_attr="probe_task",
        tick_s=3600.0,
        sweep=_sweep,
        failure_message="probe failed",
        on_start=lambda: None,
    )

    with TestClient(app):
        time.sleep(0.1)
        assert calls == []


def test_install_periodic_sweeps_once_at_start_when_asked() -> None:
    app = FastAPI()
    calls: list[int] = []

    async def _sweep() -> None:
        calls.append(1)

    _install_periodic(
        app,
        task_attr="probe_task",
        tick_s=3600.0,
        sweep=_sweep,
        failure_message="probe failed",
        on_start=lambda: None,
        sweep_on_start=True,
    )

    with TestClient(app):
        _wait_until(lambda: calls == [1])
