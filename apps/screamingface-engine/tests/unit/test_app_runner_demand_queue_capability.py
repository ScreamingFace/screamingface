"""The runner-demand sampler is installed only when the queue runner's queue can read buckets.

A `QueueJobRunner` is structurally a `DemandSource` over any queue. Over a queue without
`bucket_readings` it must get no sampler, so the App never logs a TypeError every tick.

FEATURE: runner pool autoscaling on claimable queue demand (spec D2, review finding F3).
"""

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from _fakes import RecordingJobRunner
from fastapi import FastAPI
from fastapi.testclient import TestClient

from screamingface_engine.adapters.queue_runner import QueueJobRunner
from screamingface_engine.app import create_app
from screamingface_engine.config import Settings
from screamingface_engine.runner_demand import RunnerDemandSampler
from screamingface_engine.runner_queue import BucketReading
from screamingface_engine.testing import InMemoryEventStream

SECRET = "runner-demand-wiring-secret-0123456789abcdef"
T0 = datetime(2026, 11, 10, 12, 0, 0, tzinfo=UTC)


def _app(
    *,
    sample_s: float = 5.0,
    stale_s: float = 30.0,
    job_runner: RecordingJobRunner | QueueJobRunner | None = None,
) -> FastAPI:
    settings = Settings(
        jwt_secret=SECRET, runner_demand_sample_s=sample_s, runner_demand_stale_s=stale_s
    )
    return create_app(
        settings, stream=InMemoryEventStream(), job_runner=job_runner, clock=lambda: T0
    )


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


class _ReadableQueue(_FakeQueue):
    """A fake queue that can read every bucket consumer, like the real `RunQueue`."""

    async def bucket_readings(self) -> list[BucketReading | None]:
        return [BucketReading(running=1, queued=0, max_ack_pending=4)]


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


def _runner(queue: _FakeQueue) -> QueueJobRunner:
    return QueueJobRunner(
        queue=queue,
        publisher=_FakePublisher(),
        control=_FakeControl(),
        clock=lambda: T0,
        capability_lifetime_s=100.0,
    )


def test_a_queue_runner_over_a_queue_without_bucket_readings_cannot_read_buckets() -> None:
    assert _runner(_FakeQueue()).reads_buckets is False


def test_a_queue_runner_over_a_readable_queue_reads_buckets() -> None:
    assert _runner(_ReadableQueue()).reads_buckets is True


def test_a_queue_runner_that_cannot_read_buckets_gets_no_sampler() -> None:
    app = _app(job_runner=_runner(_FakeQueue()))

    assert app.state.runner_demand is None
    with TestClient(app):
        assert app.state.runner_demand_task is None


def test_a_queue_runner_that_reads_buckets_gets_a_sampler() -> None:
    app = _app(job_runner=_runner(_ReadableQueue()))

    assert isinstance(app.state.runner_demand, RunnerDemandSampler)
