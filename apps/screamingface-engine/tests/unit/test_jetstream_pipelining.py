"""`JetStreamPublisher` pipelines its publishes; `flush` is the durability barrier.

FEATURE: a cached DRACO burst must not overflow the Runner event bridge (OME-906). Awaiting
one broker acknowledgement per frame capped the drain at one round trip per frame — roughly
1000 frames/s — while the engine produced observation events at CPU speed. The bridge between
them cannot push back, because the engine's observer callback is synchronous, so it overflowed
its hard cap on a run that was entirely correct.

The unit suite has no broker, so these tests replace `_jetstream` with a fake context. The
real-broker behaviour is covered by the NATS-gated conformance parameters in `_fakes.py`.
"""

import asyncio
from datetime import UTC, datetime

import pytest

from screamingface_engine.adapters.jetstream import (
    DeferredPublishError,
    JetStreamPublisher,
)
from url4.streaming.protocol import LogData, LogEvent, OutboundFrame, SpanData, SpanEvent

TOPIC = "pipelining-topic"


class _FakeJetStream:
    """The slice of `JetStreamContext` the publisher uses, with acknowledgements under test
    control so a test can assert on the deferred window rather than on timing."""

    def __init__(self) -> None:
        self.subjects: list[str] = []
        self.futures: list[asyncio.Future[object]] = []

    async def publish_async(self, subject: str, payload: bytes) -> asyncio.Future[object]:
        self.subjects.append(subject)
        future: asyncio.Future[object] = asyncio.get_running_loop().create_future()
        self.futures.append(future)
        return future

    def settle_all(self) -> None:
        for future in self.futures:
            if not future.done():
                future.set_result(object())


def _publisher(fake: _FakeJetStream) -> JetStreamPublisher:
    publisher = JetStreamPublisher("nats://unused:4222")

    async def _fake_jetstream() -> _FakeJetStream:
        return fake

    # WHY monkeypatch the seam rather than the socket: the pipelining contract is about WHEN
    # this class waits, which is observable at the JetStream boundary and nowhere below it.
    publisher._jetstream = _fake_jetstream  # type: ignore[assignment,method-assign]
    return publisher


def _log(n: int) -> LogEvent:
    return LogEvent(
        id=f"e{n}",
        source="/trace/t/node/root",
        subject="t",
        data=LogData.at("INFO", f"msg-{n}"),
    )


def _span(n: int) -> SpanEvent:
    return SpanEvent(
        id=f"s{n}",
        source="/trace/t/node/n",
        subject="t",
        data=SpanData(name="chat", operation="chat", start=datetime(2026, 8, 20, tzinfo=UTC)),
    )


@pytest.mark.asyncio
async def test_publish_does_not_wait_for_the_acknowledgement() -> None:
    # INVARIANT: this is the whole fix. `publish` returns with the acknowledgement still
    # outstanding, so the drain rate stops being one broker round trip per frame.
    fake = _FakeJetStream()
    publisher = _publisher(fake)

    await publisher.publish(TOPIC, _log(0))

    assert len(fake.futures) == 1
    assert not fake.futures[0].done(), "publish must not have awaited the acknowledgement"


@pytest.mark.asyncio
async def test_many_frames_publish_without_a_single_acknowledgement() -> None:
    fake = _FakeJetStream()
    publisher = _publisher(fake)

    for i in range(50):
        await publisher.publish(TOPIC, _span(i))

    assert len(fake.subjects) == 50
    assert not any(f.done() for f in fake.futures)


@pytest.mark.asyncio
async def test_the_frames_reach_the_transport_in_call_order() -> None:
    """INVARIANT: order is why the pipeline lives in the transport and not in the caller.
    A task per frame would reach the socket in an unknown order, and the consumer finds gaps
    by the sequence the broker assigns from that order."""
    fake = _FakeJetStream()
    publisher = _publisher(fake)
    frames: list[OutboundFrame] = [_log(i) for i in range(5)]

    for frame in frames:
        await publisher.publish(TOPIC, frame)

    assert len(fake.subjects) == 5
    assert fake.subjects == [fake.subjects[0]] * 5, "one topic means one subject"


@pytest.mark.asyncio
async def test_a_rejected_acknowledgement_raises_on_the_next_publish() -> None:
    # STORY: as an operator, a broker that starts rejecting must stop the run promptly —
    # not after the whole in-flight window has drained.
    fake = _FakeJetStream()
    publisher = _publisher(fake)
    await publisher.publish(TOPIC, _log(0))
    fake.futures[0].set_exception(RuntimeError("maximum messages exceeded"))
    await asyncio.sleep(0)  # let the done callback run

    with pytest.raises(DeferredPublishError) as excinfo:
        await publisher.publish(TOPIC, _log(1))

    assert "maximum messages exceeded" in str(excinfo.value.__cause__)


@pytest.mark.asyncio
async def test_a_rejected_acknowledgement_raises_at_the_flush() -> None:
    fake = _FakeJetStream()
    publisher = _publisher(fake)
    await publisher.publish(TOPIC, _log(0))
    fake.futures[0].set_exception(RuntimeError("no stream response"))

    with pytest.raises(DeferredPublishError):
        await publisher.flush()


@pytest.mark.asyncio
async def test_the_flush_reports_a_failure_once_and_then_clears_it() -> None:
    """INVARIANT: every exit from a run still publishes its terminal frame. If `flush` kept
    re-raising, the `failed` arm's own publish-and-flush would raise too and the subscriber
    would wait forever for a frame that never came."""
    fake = _FakeJetStream()
    publisher = _publisher(fake)
    await publisher.publish(TOPIC, _log(0))
    fake.futures[0].set_exception(RuntimeError("rejected"))

    with pytest.raises(DeferredPublishError):
        await publisher.flush()

    await publisher.flush()  # must not raise the same failure again


@pytest.mark.asyncio
async def test_the_flush_waits_for_the_pending_acknowledgements() -> None:
    fake = _FakeJetStream()
    publisher = _publisher(fake)
    for i in range(3):
        await publisher.publish(TOPIC, _log(i))

    flushing = asyncio.ensure_future(publisher.flush())
    await asyncio.sleep(0)
    assert not flushing.done(), "flush returned while acknowledgements were still outstanding"

    fake.settle_all()
    await asyncio.wait_for(flushing, timeout=1.0)


@pytest.mark.asyncio
async def test_only_the_first_failure_is_reported() -> None:
    # WHY the first: it is the one that explains the run. A later rejection is usually the
    # same broker condition observed again.
    fake = _FakeJetStream()
    publisher = _publisher(fake)
    for i in range(2):
        await publisher.publish(TOPIC, _log(i))
    fake.futures[0].set_exception(RuntimeError("first"))
    fake.futures[1].set_exception(RuntimeError("second"))

    with pytest.raises(DeferredPublishError) as excinfo:
        await publisher.flush()

    assert "first" in str(excinfo.value.__cause__)


@pytest.mark.asyncio
async def test_a_cancelled_acknowledgement_is_not_a_failure() -> None:
    # A cancelled future carries no broker verdict. Treating it as a rejection would fail a
    # run on teardown, which is the shutdown path, not a defect.
    fake = _FakeJetStream()
    publisher = _publisher(fake)
    await publisher.publish(TOPIC, _log(0))
    fake.futures[0].cancel()
    await asyncio.sleep(0)

    await publisher.flush()
