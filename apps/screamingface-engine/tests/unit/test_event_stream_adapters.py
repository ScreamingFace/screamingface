from datetime import datetime

import pytest
from _fakes import take

from screamingface_engine.adapters.jetstream import JetStreamConsumer, JetStreamPublisher
from screamingface_engine.testing import InMemoryEventStream
from url4.streaming.interfaces import EventConsumer, EventPublisher, StreamNotFoundError
from url4.streaming.protocol import LogData, LogEvent, SpanData, SpanEvent

TOPIC = "cap-topic"


def _log_event(n: int) -> LogEvent:
    return LogEvent(
        id=f"e{n}",
        source="/trace/t/node/root",
        subject="t",
        data=LogData(severity_number=9, severity_text="INFO", body=f"msg-{n}"),
    )


@pytest.mark.asyncio
async def test_resume_cursor_on_missing_stream_is_stream_not_found() -> None:
    """OME-1019: a resume cursor with no stream to resume from is a RECLAIMED stream.

    Fresh attaches may create the stream; a resume cursor never can — that is exactly
    the signal the bridge uses to answer `stream_reclaimed`.
    """
    stream = InMemoryEventStream()
    with pytest.raises(StreamNotFoundError):
        async for _ in stream.subscribe("never-created", from_sequence=3):
            pass  # pragma: no cover - the generator raises before yielding


@pytest.mark.asyncio
async def test_fresh_attach_on_missing_stream_creates_and_delivers() -> None:
    """The fresh-attach side of the rule: cursor None creates the stream and delivers."""
    stream = InMemoryEventStream()
    frames = stream.subscribe("fresh-topic", None)
    try:
        first = anext(frames)
        await stream.publish("fresh-topic", _log_event(1))
        frame = await first
        assert frame is not None
    finally:
        await frames.aclose()


@pytest.mark.asyncio
async def test_publish_subscribe_round_trips_in_order() -> None:
    stream = InMemoryEventStream()
    for i in range(3):
        await stream.publish(TOPIC, _log_event(i))
    got = await take(stream, TOPIC, 3)
    bodies = []
    for ev in got:
        assert isinstance(ev, LogEvent)
        bodies.append(ev.data.body)
    assert bodies == ["msg-0", "msg-1", "msg-2"]
    assert [ev.id for ev in got] == ["e0", "e1", "e2"]


@pytest.mark.asyncio
async def test_gen_ai_aliases_survive_the_codec() -> None:
    stream = InMemoryEventStream()
    span = SpanEvent(
        id="s1",
        source="/trace/t/node/n",
        data=SpanData(
            name="chat",
            operation="chat",
            input_tokens=1200,
            output_tokens=340,
            start=datetime(2026, 7, 21, 9, 0, 0),
        ),
    )
    await stream.publish(TOPIC, span)
    got = await take(stream, TOPIC, 1)
    ev = got[0]
    assert isinstance(ev, SpanEvent)
    assert ev.data.input_tokens == 1200
    assert ev.data.output_tokens == 340
    assert ev.data.operation == "chat"


def test_the_read_side_implementations_satisfy_the_consumer_port() -> None:
    assert isinstance(InMemoryEventStream(), EventConsumer)
    assert isinstance(JetStreamConsumer("nats://localhost:4222"), EventConsumer)


def test_the_runners_publisher_satisfies_the_publisher_port() -> None:
    publisher = JetStreamPublisher("nats://localhost:4222")
    assert isinstance(publisher, EventPublisher)
    assert not isinstance(publisher, EventConsumer)
