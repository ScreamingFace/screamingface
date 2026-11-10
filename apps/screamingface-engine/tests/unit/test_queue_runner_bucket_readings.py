"""QueueJobRunner.bucket_readings (runner-pool autoscaling, spec D1): the runner hands back the
queue's per-bucket readings, reads no admission state, and refuses a queue that cannot read
buckets.
"""

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

import pytest

from screamingface_engine.adapters.queue_runner import QueueJobRunner
from screamingface_engine.runner_queue import BucketReading

T0 = datetime(2026, 11, 10, 12, 0, 0, tzinfo=UTC)


class _FakeQueue:
    def __init__(self, *, depth: int = 0, oldest_age: float | None = None) -> None:
        self._depth = depth
        self._oldest_age = oldest_age
        self.depth_calls = 0

    async def publish(
        self, message: bytes, *, identity: Mapping[str, str] | None = None, enqueued_at: Any = None
    ) -> None:
        raise NotImplementedError

    async def depth(self) -> int:
        self.depth_calls += 1
        return self._depth

    async def oldest_age(self) -> float | None:
        return self._oldest_age


class _ReadingQueue(_FakeQueue):
    def __init__(self, readings: list[BucketReading | None]) -> None:
        super().__init__()
        self.readings = readings
        self.reading_calls = 0

    async def bucket_readings(self) -> list[BucketReading | None]:
        self.reading_calls += 1
        return list(self.readings)


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


@pytest.mark.asyncio
async def test_the_runner_hands_back_the_queues_readings() -> None:
    readings = [BucketReading(running=4, queued=2, max_ack_pending=4), None]
    queue = _ReadingQueue(readings)

    assert await _runner(queue).bucket_readings() == readings
    assert queue.reading_calls == 1


@pytest.mark.asyncio
async def test_the_reading_touches_no_admission_state() -> None:
    queue = _ReadingQueue([None])
    runner = _runner(queue)
    before = runner.queue_snapshot()

    await runner.bucket_readings()

    assert runner.queue_snapshot() == before == (None, None)
    assert queue.depth_calls == 0


@pytest.mark.asyncio
async def test_a_queue_that_cannot_read_buckets_raises_type_error() -> None:
    with pytest.raises(TypeError):
        await _runner(_FakeQueue()).bucket_readings()
