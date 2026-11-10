"""`RunQueue.bucket_readings()`: one public `consumer_info` per bucket, read-only
(runner-pool autoscaling, plan change 2)."""

from types import SimpleNamespace
from typing import Any

import nats.errors
import pytest
from nats.js.errors import NotFoundError

from screamingface_engine import runner_queue
from screamingface_engine.runner_queue import BucketReading, RunQueue


class _FakeJetStream:
    """Serves `consumer_info` from a table; any bind or create by the App fails the test."""

    def __init__(self, infos: dict[str, Any]) -> None:
        self._infos = infos
        self.calls: list[tuple[str, str]] = []

    async def consumer_info(self, stream: str, consumer: str, timeout: float | None = None) -> Any:
        self.calls.append((stream, consumer))
        value = self._infos[consumer]
        if isinstance(value, BaseException):
            raise value
        return value

    async def pull_subscribe(self, *args: Any, **kwargs: Any) -> Any:
        raise AssertionError("the App must never bind a consumer")

    async def add_consumer(self, *args: Any, **kwargs: Any) -> Any:
        raise AssertionError("the App must never create a consumer")


def _info(running: int | None, queued: int | None, cap: int | None) -> SimpleNamespace:
    return SimpleNamespace(
        num_ack_pending=running,
        num_pending=queued,
        config=SimpleNamespace(max_ack_pending=cap),
    )


def _queue(fake: _FakeJetStream) -> RunQueue:
    queue = RunQueue("nats://unused:4222", stream="s", subject_prefix="q", bucket_count=3)

    async def _fake_jetstream() -> _FakeJetStream:
        return fake

    queue._jetstream = _fake_jetstream  # type: ignore[assignment,method-assign]
    return queue


@pytest.mark.asyncio
async def test_readings_follow_bucket_order_and_map_the_consumer_fields() -> None:
    fake = _FakeJetStream(
        {
            "url4-runners-00": _info(4, 2, 4),
            "url4-runners-01": _info(0, 0, 4),
            "url4-runners-02": _info(1, 5, 8),
        }
    )

    assert await _queue(fake).bucket_readings() == [
        BucketReading(running=4, queued=2, max_ack_pending=4),
        BucketReading(running=0, queued=0, max_ack_pending=4),
        BucketReading(running=1, queued=5, max_ack_pending=8),
    ]
    assert sorted(fake.calls) == [
        ("s", "url4-runners-00"),
        ("s", "url4-runners-01"),
        ("s", "url4-runners-02"),
    ]


@pytest.mark.asyncio
async def test_a_missing_server_field_reads_as_zero_and_a_missing_cap_as_no_cap() -> None:
    fake = _FakeJetStream(
        {
            "url4-runners-00": _info(None, None, None),
            "url4-runners-01": _info(None, None, None),
            "url4-runners-02": _info(None, None, None),
        }
    )

    readings = await _queue(fake).bucket_readings()

    assert all(
        reading == BucketReading(running=0, queued=0, max_ack_pending=-1) for reading in readings
    )


@pytest.mark.asyncio
async def test_an_unknown_consumer_reads_as_none() -> None:
    fake = _FakeJetStream(
        {
            "url4-runners-00": _info(4, 2, 4),
            "url4-runners-01": NotFoundError(
                code=404, err_code=10014, description="consumer not found"
            ),
            "url4-runners-02": _info(1, 5, 8),
        }
    )

    result = await _queue(fake).bucket_readings()

    assert result[1] is None
    assert isinstance(result[0], BucketReading)
    assert isinstance(result[2], BucketReading)


@pytest.mark.asyncio
async def test_any_other_broker_error_propagates() -> None:
    fake = _FakeJetStream(
        {
            "url4-runners-00": _info(4, 2, 4),
            "url4-runners-01": _info(0, 0, 4),
            "url4-runners-02": nats.errors.TimeoutError(),
        }
    )

    with pytest.raises(nats.errors.TimeoutError):
        await _queue(fake).bucket_readings()


@pytest.mark.asyncio
async def test_the_app_never_binds_or_creates_a_consumer() -> None:
    fake = _FakeJetStream(
        {
            "url4-runners-00": _info(4, 2, 4),
            "url4-runners-01": _info(0, 0, 4),
            "url4-runners-02": _info(1, 5, 8),
        }
    )

    await _queue(fake).bucket_readings()

    assert len(fake.calls) == 3


def test_the_reading_is_exported() -> None:
    assert "BucketReading" in runner_queue.__all__
