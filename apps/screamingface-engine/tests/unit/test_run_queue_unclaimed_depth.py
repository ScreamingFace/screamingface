"""The run queue's depth counts UNCLAIMED runs, read from the per-bucket consumers.

FEATURE: an honest queue depth for admission, `Retry-After` and `/metrics`
(docs/spec/2026-11-10-queue-depth-unclaimed.md).

WHY this file exists: the queue stream is WorkQueue-retained and a worker acks a run only at
its END, so the stream's message count is queued + RUNNING. `depth()` returned that count and
`oldest_age()` the stream's first message, which is usually a running run. The exact backlog
lives on the per-bucket durable consumers (`url4-runners-<bb>`): `num_pending` is what no
worker has been handed yet.

The fake speaks nats-py's own types (`ConsumerInfo`, `RawStreamMsg`, `StreamInfo`), so a field
read from the wrong place fails here, not in production.
"""

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any

import nats.errors
import pytest
from nats.js.api import (
    ConsumerConfig,
    ConsumerInfo,
    RawStreamMsg,
    SequenceInfo,
    StreamConfig,
    StreamInfo,
    StreamState,
)
from nats.js.errors import NotFoundError, ServiceUnavailableError

from screamingface_engine.runner_queue import BucketReading, RunQueue

pytestmark = pytest.mark.asyncio

STREAM = "url4-runq-test"
PREFIX = "url4-runq-test"
NOW = datetime.now(UTC)


def _info(
    *,
    running: int | None,
    queued: int | None,
    max_ack_pending: int | None = 4,
    delivered_seq: int = 0,
) -> ConsumerInfo:
    return ConsumerInfo(
        name="ignored",
        stream_name=STREAM,
        config=ConsumerConfig(max_ack_pending=max_ack_pending),
        created=NOW,
        delivered=SequenceInfo(consumer_seq=delivered_seq, stream_seq=delivered_seq),
        num_ack_pending=running,
        num_pending=queued,
    )


class _FakeJetStream:
    """The read-only slice of `JetStreamContext` the depth reading uses.

    `consumers` maps consumer name → `ConsumerInfo` (absent = not found);
    `heads` maps (subject, start seq) → the first message's age in seconds (absent = not
    found); `subjects` is the stream's per-subject message count.
    """

    def __init__(
        self,
        consumers: dict[str, ConsumerInfo | BaseException],
        *,
        heads: dict[tuple[str, int], float] | None = None,
        subjects: dict[str, int] | None = None,
        messages: int = 0,
    ) -> None:
        self.consumers = consumers
        self.heads = heads or {}
        self.subjects = subjects or {}
        self.messages = messages
        self.consumer_info_calls: list[tuple[str, str]] = []
        self.get_msg_calls: list[tuple[str, int | None, str | None, bool | None]] = []
        self.stream_info_calls: list[tuple[str, str | None]] = []

    async def consumer_info(self, stream: str, consumer: str, timeout: Any = None) -> Any:
        self.consumer_info_calls.append((stream, consumer))
        await asyncio.sleep(0)
        found = self.consumers.get(consumer)
        if found is None:
            raise NotFoundError(code=404, err_code=10014, description="consumer not found")
        if isinstance(found, BaseException):
            raise found
        return found

    async def get_msg(
        self,
        stream_name: str,
        seq: int | None = None,
        subject: str | None = None,
        direct: bool | None = False,
        next: bool | None = False,  # noqa: A002 — nats-py's own parameter name
    ) -> RawStreamMsg:
        self.get_msg_calls.append((stream_name, seq, subject, next))
        age = self.heads.get((subject or "", seq or 0))
        if age is None:
            raise NotFoundError(code=404, err_code=10037, description="no message found")
        return RawStreamMsg(
            subject=subject, seq=seq, time=datetime.now(UTC) - timedelta(seconds=age)
        )

    async def stream_info(self, name: str, subjects_filter: str | None = None) -> StreamInfo:
        self.stream_info_calls.append((name, subjects_filter))
        return StreamInfo(
            config=StreamConfig(name=name),
            state=StreamState(
                messages=self.messages,
                bytes=0,
                first_seq=0,
                last_seq=0,
                consumer_count=0,
                subjects=dict(self.subjects) if subjects_filter else None,
            ),
        )

    # INVARIANT (spec D1): the App never creates or binds a consumer — a bind with the App's
    # settings would set the WORKER's `max_ack_pending`. Any such call fails the test.
    async def pull_subscribe(self, *args: Any, **kwargs: Any) -> Any:
        raise AssertionError("the depth reading must never bind a consumer")

    async def add_consumer(self, *args: Any, **kwargs: Any) -> Any:
        raise AssertionError("the depth reading must never create a consumer")


def _queue(fake: _FakeJetStream, *, bucket_count: int = 3, ttl: float = 2.0) -> RunQueue:
    queue = RunQueue(
        "nats://unused:4222",
        stream=STREAM,
        subject_prefix=PREFIX,
        bucket_count=bucket_count,
        state_cache_ttl_s=ttl,
    )

    async def _fake_jetstream() -> _FakeJetStream:
        return fake

    queue._jetstream = _fake_jetstream  # type: ignore[assignment,method-assign]
    return queue


# --- bucket_readings: the shared raw reading ---------------------------------------------


async def test_bucket_readings_map_each_bucket_consumer_in_bucket_order() -> None:
    fake = _FakeJetStream(
        {
            "url4-runners-00": _info(running=4, queued=2, max_ack_pending=4),
            "url4-runners-01": _info(running=0, queued=0, max_ack_pending=8),
            "url4-runners-02": _info(running=1, queued=7, max_ack_pending=-1),
        }
    )

    readings = await _queue(fake).bucket_readings()

    assert readings == [
        BucketReading(running=4, queued=2, max_ack_pending=4),
        BucketReading(running=0, queued=0, max_ack_pending=8),
        BucketReading(running=1, queued=7, max_ack_pending=-1),
    ]
    assert sorted(fake.consumer_info_calls) == [
        (STREAM, "url4-runners-00"),
        (STREAM, "url4-runners-01"),
        (STREAM, "url4-runners-02"),
    ]


async def test_a_missing_consumer_reads_as_none_not_as_an_empty_bucket() -> None:
    """Cold start: no worker has bound bucket 01 yet. `None` keeps "unknown" apart from a
    bound bucket that is genuinely empty."""
    fake = _FakeJetStream(
        {
            "url4-runners-00": _info(running=0, queued=0),
            "url4-runners-02": _info(running=0, queued=1),
        }
    )

    readings = await _queue(fake).bucket_readings()

    assert readings[1] is None
    assert readings[0] == BucketReading(running=0, queued=0, max_ack_pending=4)


async def test_server_none_fields_read_as_zero_and_an_unset_cap_as_no_cap() -> None:
    fake = _FakeJetStream(
        {"url4-runners-00": _info(running=None, queued=None, max_ack_pending=None)}
    )

    readings = await _queue(fake, bucket_count=1).bucket_readings()

    assert readings == [BucketReading(running=0, queued=0, max_ack_pending=-1)]


async def test_a_broker_error_other_than_not_found_propagates() -> None:
    """Only "consumer not found" is a reading. A broker that cannot answer must surface —
    the admission path maps it to a retryable 503 — never read as an empty queue."""
    fake = _FakeJetStream({"url4-runners-00": ServiceUnavailableError()})

    with pytest.raises(ServiceUnavailableError):
        await _queue(fake, bucket_count=1).bucket_readings()
    with pytest.raises(nats.errors.Error):
        await _queue(fake, bucket_count=1).depth()


async def test_bucket_readings_reads_concurrently() -> None:
    """The fan-out is gathered: every request is in flight before the first answer."""
    started: list[str] = []
    gate = asyncio.Event()

    class _Gated(_FakeJetStream):
        async def consumer_info(self, stream: str, consumer: str, timeout: Any = None) -> Any:
            started.append(consumer)
            if len(started) == 3:
                gate.set()
            await asyncio.wait_for(gate.wait(), timeout=1.0)
            return _info(running=0, queued=0)

    readings = await _queue(_Gated({})).bucket_readings()

    assert len(readings) == 3 and len(started) == 3


# --- depth(): unclaimed runs ---------------------------------------------------------------


async def test_depth_counts_queued_runs_and_excludes_running_runs() -> None:
    """The bug: 4 running + 2 queued in A, 2 queued in C read as 8. The backlog is 4."""
    fake = _FakeJetStream(
        {
            "url4-runners-00": _info(running=4, queued=2, delivered_seq=4),
            "url4-runners-01": _info(running=0, queued=0),
            "url4-runners-02": _info(running=0, queued=2),
        },
        messages=8,
    )

    assert await _queue(fake).depth() == 4
    # Steady state (every consumer bound) sends no stream request at all.
    assert fake.stream_info_calls == []


async def test_a_bucket_with_no_consumer_contributes_its_subject_count() -> None:
    """Spec D2: no consumer means nothing on that subject was delivered, and WorkQueue
    retention keeps every message until an ack — so all of them wait. A cold start must
    never read as an empty queue."""
    fake = _FakeJetStream(
        {"url4-runners-00": _info(running=2, queued=1, delivered_seq=2)},
        subjects={f"{PREFIX}.00": 3, f"{PREFIX}.01": 5, f"{PREFIX}.02": 2},
    )

    assert await _queue(fake).depth() == 1 + 5 + 2
    assert fake.stream_info_calls == [(STREAM, f"{PREFIX}.>")]


async def test_cold_start_with_no_consumer_at_all_counts_every_message() -> None:
    fake = _FakeJetStream({}, subjects={f"{PREFIX}.01": 7})

    assert await _queue(fake).depth() == 7


async def test_held_is_the_stream_message_count_queued_plus_running() -> None:
    fake = _FakeJetStream(
        {"url4-runners-00": _info(running=4, queued=2, delivered_seq=4)}, messages=6
    )
    queue = _queue(fake, bucket_count=1)

    assert await queue.held() == 6
    assert await queue.depth() == 2


# --- oldest_age(): the oldest UNCLAIMED run ------------------------------------------------


async def test_oldest_age_is_the_oldest_undelivered_head_across_buckets() -> None:
    """A's head after delivered seq 4 waited 30 s; C's head (nothing delivered yet) waited
    50 s. The running runs in A are older still — they must not count."""
    fake = _FakeJetStream(
        {
            "url4-runners-00": _info(running=4, queued=2, delivered_seq=4),
            "url4-runners-01": _info(running=0, queued=0, delivered_seq=9),
            "url4-runners-02": _info(running=0, queued=2, delivered_seq=0),
        },
        heads={(f"{PREFIX}.00", 5): 30.0, (f"{PREFIX}.02", 1): 50.0},
    )

    age = await _queue(fake).oldest_age()

    assert age == pytest.approx(50.0, abs=2.0)
    # Each read starts right after what the consumer delivered, on its own subject, and asks
    # for the NEXT message there; an empty bucket is not read at all.
    assert sorted(fake.get_msg_calls) == [
        (STREAM, 1, f"{PREFIX}.02", True),
        (STREAM, 5, f"{PREFIX}.00", True),
    ]


async def test_a_bucket_with_no_consumer_is_read_from_its_first_message() -> None:
    fake = _FakeJetStream(
        {"url4-runners-00": _info(running=1, queued=0, delivered_seq=3)},
        subjects={f"{PREFIX}.00": 1, f"{PREFIX}.01": 2},
        heads={(f"{PREFIX}.01", 1): 12.0},
    )

    age = await _queue(fake, bucket_count=2).oldest_age()

    assert age == pytest.approx(12.0, abs=2.0)
    assert fake.get_msg_calls == [(STREAM, 1, f"{PREFIX}.01", True)]


async def test_nothing_unclaimed_has_no_age_and_reads_no_message() -> None:
    fake = _FakeJetStream(
        {
            "url4-runners-00": _info(running=4, queued=0, delivered_seq=4),
            "url4-runners-01": _info(running=0, queued=0),
            "url4-runners-02": _info(running=2, queued=0, delivered_seq=7),
        },
        messages=6,
    )

    assert await _queue(fake).oldest_age() is None
    assert fake.get_msg_calls == []


async def test_a_head_claimed_between_the_two_reads_is_skipped() -> None:
    """Race: a worker took C's head after `consumer_info` and before `get_msg`. That bucket
    gives no timestamp; the others still do."""
    fake = _FakeJetStream(
        {
            "url4-runners-00": _info(running=0, queued=1, delivered_seq=0),
            "url4-runners-01": _info(running=0, queued=1, delivered_seq=0),
        },
        heads={(f"{PREFIX}.00", 1): 8.0},
    )

    age = await _queue(fake, bucket_count=2).oldest_age()

    assert age == pytest.approx(8.0, abs=2.0)


async def test_every_head_raced_away_reads_as_no_age() -> None:
    fake = _FakeJetStream({"url4-runners-00": _info(running=0, queued=1)})

    assert await _queue(fake, bucket_count=1).oldest_age() is None


async def test_a_get_msg_broker_error_propagates() -> None:
    class _Broken(_FakeJetStream):
        async def get_msg(self, *args: Any, **kwargs: Any) -> RawStreamMsg:
            raise ServiceUnavailableError()

    fake = _Broken({"url4-runners-00": _info(running=0, queued=1)})

    with pytest.raises(ServiceUnavailableError):
        await _queue(fake, bucket_count=1).oldest_age()


# --- caching (spec D8) ---------------------------------------------------------------------


async def test_depth_and_oldest_age_share_one_cached_reading() -> None:
    fake = _FakeJetStream(
        {"url4-runners-00": _info(running=0, queued=2)}, heads={(f"{PREFIX}.00", 1): 5.0}
    )
    queue = _queue(fake, bucket_count=1)

    assert await queue.depth() == 2
    assert await queue.oldest_age() is not None
    assert await queue.depth() == 2

    assert len(fake.consumer_info_calls) == 1
    assert len(fake.get_msg_calls) == 1


async def test_the_unclaimed_reading_expires_after_the_ttl() -> None:
    fake = _FakeJetStream({"url4-runners-00": _info(running=0, queued=1)})
    queue = _queue(fake, bucket_count=1, ttl=0.0)

    assert await queue.depth() == 1
    fake.consumers["url4-runners-00"] = _info(running=1, queued=0, delivered_seq=1)
    assert await queue.depth() == 0
    assert len(fake.consumer_info_calls) == 2
