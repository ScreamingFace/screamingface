"""Admission, `Retry-After` and `/metrics` read UNCLAIMED runs, end to end through a real
`RunQueue` (docs/spec/2026-11-10-queue-depth-unclaimed.md, D5–D7).

FEATURE: depth-based admission (OME-1091) and the queue gauges (OME-1092), on an honest depth.

WHY a real `RunQueue` here: the runner's own tests use a scripted queue whose `depth()` is
whatever the test says, so they cannot see WHAT the production queue counts. These tests
drive the runner over the production queue and a fake broker that holds RUNNING runs (delivered,
unacked) next to queued ones — the state in which the stream count and the backlog differ.
"""

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any

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
from nats.js.errors import NotFoundError

from screamingface_engine.adapters.queue_runner import QueueJobRunner
from screamingface_engine.metrics import build_metrics, register_queue_metrics
from screamingface_engine.runner_queue import RunQueue
from url4.streaming.interfaces import JobRunnerAtCapacity

T0 = datetime(2026, 11, 10, 9, 0, 0, tzinfo=UTC)
PREFIX = "url4-runq-drain"


class _Broker:
    """One bucket (`<PREFIX>.00`) whose consumer has delivered `running` runs (unacked) and
    has `queued` runs still waiting; the first waiting run is `head_age_s` old, the oldest
    RUNNING run `running_age_s` old."""

    def __init__(
        self, *, running: int, queued: int, head_age_s: float = 0.0, running_age_s: float = 0.0
    ) -> None:
        self.running = running
        self.queued = queued
        self.head_age_s = head_age_s
        self.running_age_s = running_age_s
        self.published: list[str] = []

    async def consumer_info(self, stream: str, consumer: str, timeout: Any = None) -> Any:
        if consumer != "url4-runners-00":
            raise NotFoundError(code=404, err_code=10014, description="consumer not found")
        return ConsumerInfo(
            name=consumer,
            stream_name=stream,
            config=ConsumerConfig(max_ack_pending=-1),
            created=T0,
            delivered=SequenceInfo(consumer_seq=self.running, stream_seq=self.running),
            num_ack_pending=self.running,
            num_pending=self.queued,
        )

    async def get_msg(
        self,
        stream_name: str,
        seq: int | None = None,
        subject: str | None = None,
        direct: bool | None = False,
        next: bool | None = False,  # noqa: A002 — nats-py's own parameter name
    ) -> RawStreamMsg:
        # The first message on the subject is the oldest RUNNING one; the head of the backlog
        # sits right after what the consumer delivered.
        if seq == self.running + 1 and self.queued:
            age = self.head_age_s
        elif seq == 1 and self.running:
            age = self.running_age_s
        else:
            raise NotFoundError(code=404, err_code=10037, description="no message found")
        return RawStreamMsg(
            subject=subject, seq=seq, time=datetime.now(UTC) - timedelta(seconds=age)
        )

    async def stream_info(self, name: str, subjects_filter: str | None = None) -> StreamInfo:
        held = self.running + self.queued
        return StreamInfo(
            config=StreamConfig(name=name),
            state=StreamState(
                messages=held,
                bytes=0,
                first_seq=1,
                last_seq=held,
                consumer_count=1,
                subjects={f"{PREFIX}.00": held} if subjects_filter else None,
            ),
        )

    # WHY the raw STREAM.INFO answer too: a real broker answers it, and it is what the OLD depth
    # read (the held count and the stream's first message — a RUNNING run). Modelling it keeps
    # these tests failing on the NUMBERS, not on a missing method, if depth ever regresses to
    # the stream count.
    _prefix = "$JS.API"

    async def _api_request(self, subject: str, req: bytes = b"", **_: Any) -> dict[str, Any]:
        first = datetime.now(UTC) - timedelta(seconds=self.running_age_s or self.head_age_s)
        return {"state": {"messages": self.running + self.queued, "first_ts": first.isoformat()}}

    async def add_stream(self, **kwargs: Any) -> object:
        return object()

    async def publish(
        self, subject: str, payload: bytes = b"", headers: dict[str, str] | None = None, **_: Any
    ) -> object:
        self.published.append(subject)
        return object()


class _Publisher:
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


class _Control:
    async def request(self, subject: str, payload: bytes, *, timeout: float) -> object:
        raise TimeoutError


def _runner(broker: _Broker, *, depth_ceiling: int) -> QueueJobRunner:
    # One bucket: every caller hashes to `<PREFIX>.00`, the bucket the broker models.
    queue = RunQueue("nats://unused:4222", stream=PREFIX, subject_prefix=PREFIX, bucket_count=1)

    async def _fake_jetstream() -> _Broker:
        return broker

    queue._jetstream = _fake_jetstream  # type: ignore[assignment,method-assign]
    return QueueJobRunner(
        queue=queue,
        publisher=_Publisher(),
        control=_Control(),
        clock=lambda: T0,
        capability_lifetime_s=100.0,
        depth_ceiling=depth_ceiling,
    )


@pytest.mark.asyncio
async def test_running_runs_do_not_count_toward_the_depth_ceiling() -> None:
    """Spec D6: the ceiling bounds the BACKLOG. 50 runs executing and none waiting is a
    busy fleet, not a full queue — the stream holds 50 messages, the backlog is 0."""
    broker = _Broker(running=50, queued=0, running_age_s=900.0)
    runner = _runner(broker, depth_ceiling=10)

    await runner.schedule("t-admitted", "'hi'", 60)

    assert broker.published == [f"{PREFIX}.00"]


@pytest.mark.asyncio
async def test_retry_after_comes_from_the_backlog_and_its_oldest_waiting_run() -> None:
    """Spec D7: 100 runs wait, the first of them for 600 s, behind 50 running runs that are
    900 s old. The drain rate is 100 / 600 per second, so the queue reaches the ceiling of
    10 in (100 - 10) / (100 / 600) = 540 s. The held count (150) and the running head
    (900 s) would give a different answer."""
    broker = _Broker(running=50, queued=100, head_age_s=600.0, running_age_s=900.0)
    runner = _runner(broker, depth_ceiling=10)

    with pytest.raises(JobRunnerAtCapacity) as exc:
        await runner.schedule("t-refused", "'hi'", 60)

    assert exc.value.active == 100
    assert exc.value.limit == 10
    # The age is read on the wall clock a moment after the fake stamped it, so the ceiling
    # can round up one second.
    assert exc.value.retry_after_s in (540, 541)
    assert broker.published == []


def test_the_queue_gauges_show_the_backlog_and_its_oldest_waiting_run() -> None:
    """Spec D5: `screamingface_engine_queue_depth` and `..._oldest_unclaimed_age_s` are what
    their names say — 2 waiting runs and the 30 s age of the first of them, not the 6 held
    messages and the 900 s age of a running run."""
    broker = _Broker(running=4, queued=2, head_age_s=30.0, running_age_s=900.0)
    runner = _runner(broker, depth_ceiling=10)
    asyncio.run(runner._refresh_if_stale())  # noqa: SLF001
    metrics = build_metrics()
    register_queue_metrics(metrics, lambda: runner)

    families = {family.name: family for family in metrics.registry.collect()}
    depth = families["screamingface_engine_queue_depth"]
    age = families["screamingface_engine_queue_oldest_unclaimed_age_s"]

    assert [sample.value for sample in depth.samples] == [2.0]
    assert [sample.value for sample in age.samples] == [pytest.approx(30.0, abs=2.0)]
    assert "unclaimed" in age.documentation
    assert "claimed" in depth.documentation
