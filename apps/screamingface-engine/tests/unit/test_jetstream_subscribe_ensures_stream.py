"""The shared-stream semantics (uniform executor, erd.md §5): ONE stream `url4-events` for
every run, declared once per connection, bound by subject `url4-cloud.<topic>`. A resume
cursor is a PRODUCER sequence — it maps to no stream position, so the consumer reads a
subject from its start and drops frames below the cursor, and an empty subject simply waits
rather than raising. Only a cursor above a TERMINAL first delivered frame is a reclaimed
stream (the subject holds nothing but the terminal frame the reclaim's `keep=1` kept) — a
live run's oldest frames can roll past the cursor too (the per-subject cap, a full store),
and that is not a reclaim, so the resume continues instead of raising."""

import asyncio
from collections.abc import AsyncGenerator, AsyncIterator
from contextlib import suppress
from types import SimpleNamespace
from typing import Any, cast

import pytest
from nats.js import JetStreamContext
from nats.js.api import AckPolicy, DeliverPolicy, DiscardPolicy, RetentionPolicy, StorageType
from nats.js.errors import NotFoundError

from screamingface_engine.adapters.jetstream import JetStreamConsumer, _broadcast_consumer_config
from url4.streaming.codec import encode
from url4.streaming.interfaces import StreamNotFoundError
from url4.streaming.protocol import (
    LogData,
    LogEvent,
    OutboundFrame,
    TerminatedData,
    TerminatedEvent,
    source_for,
)

pytestmark = pytest.mark.asyncio


def _frame(n: int) -> LogEvent:
    return LogEvent(
        id=f"e{n}",
        source=source_for("topic-a", "root"),
        subject="topic-a",
        data=LogData.at("INFO", f"msg-{n}"),
        sequence=str(n),
        sequencetype="Integer",
    )


def _terminal_frame(n: int) -> TerminatedEvent:
    return TerminatedEvent(
        id=f"e{n}",
        source=source_for("topic-a", "root"),
        subject="topic-a",
        data=TerminatedData(status="succeeded"),
        sequence=str(n),
        sequencetype="Integer",
    )


class _FakeMsg:
    """One delivered message, shaped like the `nats-py` message the adapter decodes.

    `stream_seq` is the STREAM sequence (has gaps in a shared stream); `producer_seq` is the
    number encoded into the frame itself (I-EV2) — the two are asserted apart deliberately.
    `frame` overrides the encoded payload (a `_terminal_frame` in place of the default
    `_frame`, a `LogEvent`) for the one case that must be terminal to mean anything.
    """

    def __init__(
        self,
        producer_seq: int,
        *,
        stream_seq: int | None = None,
        frame: OutboundFrame | None = None,
    ) -> None:
        self.data = encode(frame if frame is not None else _frame(producer_seq))
        self.metadata = SimpleNamespace(
            sequence=SimpleNamespace(stream=stream_seq if stream_seq is not None else producer_seq)
        )


class _FakeSub:
    def __init__(self, msgs: list[_FakeMsg], *, blocks: bool = False) -> None:
        self.unsubscribed = False
        self._msgs = msgs
        self._blocks = blocks

    @property
    def messages(self) -> AsyncIterator[_FakeMsg]:
        async def _iter() -> AsyncIterator[_FakeMsg]:
            for msg in self._msgs:
                yield msg
            if self._blocks:
                # An empty (or exhausted) subject on a live broker never ends the
                # subscription — it just has nothing pending. Block instead of returning,
                # so a test that asserts "does not raise" cannot pass by accident because
                # the fake ended the iteration for it.
                await asyncio.Event().wait()

        return _iter()

    async def unsubscribe(self) -> None:
        self.unsubscribed = True


class _FakeJetStream:
    """Records what the adapter asked for and answers like the broker would."""

    def __init__(self, *, purge_raises_not_found: bool = False) -> None:
        self.calls: list[str] = []
        self.add_stream_calls: list[Any] = []
        self.subscribe_calls: list[dict[str, Any]] = []
        self.purge_calls: list[dict[str, Any]] = []
        self.subs: list[_FakeSub] = []
        self._next_msgs: list[_FakeMsg] = []
        self._next_blocks = False
        self._purge_raises_not_found = purge_raises_not_found

    def script(self, msgs: list[_FakeMsg], *, blocks: bool = False) -> None:
        self._next_msgs = msgs
        self._next_blocks = blocks

    async def stream_info(self, name: str) -> object:
        # Like the broker: the stream is unknown until `add_stream` created it.
        if not self.add_stream_calls:
            raise NotFoundError(code=404, err_code=10059, description="stream not found")
        return object()

    async def add_stream(self, config: Any) -> object:
        self.calls.append("add_stream")
        self.add_stream_calls.append(config)
        return object()

    async def subscribe(self, subject: str, **kwargs: Any) -> _FakeSub:
        self.calls.append("subscribe")
        self.subscribe_calls.append({"subject": subject, **kwargs})
        sub = _FakeSub(self._next_msgs, blocks=self._next_blocks)
        self.subs.append(sub)
        return sub

    async def purge_stream(
        self, name: str, *, subject: str | None = None, keep: int | None = None
    ) -> bool:
        self.calls.append("purge_stream")
        self.purge_calls.append({"name": name, "subject": subject, "keep": keep})
        if self._purge_raises_not_found:
            raise NotFoundError
        return True


def _consumer(js: _FakeJetStream) -> JetStreamConsumer:
    stream = JetStreamConsumer("nats://unused:4222")
    stream._js = cast(JetStreamContext, js)  # noqa: SLF001
    return stream


async def test_subscribe_ensures_the_shared_stream_before_binding() -> None:
    js = _FakeJetStream()
    stream = _consumer(js)

    async for _ in stream.subscribe("topic-a"):  # pragma: no branch - drains an empty subject
        pass

    assert js.calls.count("add_stream") == 1
    assert js.calls.index("add_stream") < js.calls.index("subscribe")
    [call] = js.subscribe_calls
    assert call["subject"] == "url4-cloud.topic-a"
    assert call["stream"] == "url4-events"
    assert call["config"].ack_policy is AckPolicy.NONE
    assert call["config"].deliver_policy is DeliverPolicy.ALL


async def test_a_second_subscribe_on_the_same_consumer_does_not_redeclare() -> None:
    js = _FakeJetStream()
    stream = _consumer(js)

    async for _ in stream.subscribe("topic-a"):  # pragma: no branch
        pass
    async for _ in stream.subscribe("topic-a"):  # pragma: no branch
        pass

    assert js.calls.count("add_stream") == 1


async def test_resume_cursor_on_an_empty_subject_waits_instead_of_raising() -> None:
    js = _FakeJetStream()
    js.script([], blocks=True)
    stream = _consumer(js)

    gen = cast(AsyncGenerator[OutboundFrame], stream.subscribe("topic-a", from_sequence=3))
    task = asyncio.ensure_future(anext(gen))
    with pytest.raises(TimeoutError):
        await asyncio.wait_for(asyncio.shield(task), timeout=0.05)

    # It bound the subscription rather than raising `StreamNotFoundError` up front.
    assert js.calls.count("add_stream") == 1
    assert js.calls.index("add_stream") < js.calls.index("subscribe")

    task.cancel()
    with suppress(asyncio.CancelledError):
        await task
    await gen.aclose()


async def test_resume_whose_first_delivered_frame_is_above_the_cursor_raises() -> None:
    """Only when that first delivered frame is TERMINAL does an above-cursor gap mean a
    reclaimed subject (`JetStreamConsumer.subscribe`'s own I-EV2 comment) — see the module
    docstring for why a live run's non-terminal gap must NOT raise here."""
    js = _FakeJetStream()
    js.script([_FakeMsg(7, frame=_terminal_frame(7))])
    stream = _consumer(js)

    with pytest.raises(StreamNotFoundError):
        async for _ in stream.subscribe("topic-a", from_sequence=3):
            pass  # pragma: no cover - the generator raises before yielding


async def test_resume_above_the_cursor_on_a_non_terminal_frame_continues() -> None:
    """The companion case the module docstring names: a LIVE run can also lose its oldest
    frames (the per-subject cap, a full store, EV-D6/ans:Q11) and deliver its first frame
    above the cursor — that is not a reclaim, so the resume must continue from what is
    retained rather than raise."""
    js = _FakeJetStream()
    js.script([_FakeMsg(7)])
    stream = _consumer(js)

    sequences = [
        int(cast(str, frame.sequence))
        async for frame in stream.subscribe("topic-a", from_sequence=3)
    ]

    assert sequences == [7]


async def test_resume_skips_frames_below_the_cursor_and_yields_from_it() -> None:
    js = _FakeJetStream()
    js.script([_FakeMsg(n) for n in range(1, 6)])
    stream = _consumer(js)

    sequences = [
        int(cast(str, frame.sequence))
        async for frame in stream.subscribe("topic-a", from_sequence=3)
    ]

    assert sequences == [3, 4, 5]


async def test_frames_keep_the_producer_sequence_even_when_the_stream_sequence_differs() -> None:
    js = _FakeJetStream()
    js.script([_FakeMsg(n, stream_seq=100 + n) for n in range(1, 4)])
    stream = _consumer(js)

    sequences = [int(cast(str, frame.sequence)) async for frame in stream.subscribe("topic-a")]

    assert sequences == [1, 2, 3]


async def test_abandoning_the_iterator_unsubscribes() -> None:
    js = _FakeJetStream()
    js.script([_FakeMsg(n) for n in range(3)])
    stream = _consumer(js)

    # `subscribe` is typed as the AsyncIterator the port promises; the concrete object is the
    # async generator, and closing it is what abandoning an `async for` does.
    frames = cast(AsyncGenerator[OutboundFrame], stream.subscribe("topic-a"))
    await anext(frames)  # bind, then walk away mid-stream
    await frames.aclose()

    assert js.subs[0].unsubscribed is True


async def test_consumers_never_leave_frames_unacked() -> None:
    """REGRESSION (C2): the replay consumer must declare `ack_policy=none`.

    `subscribe()` with no callback is the nats-py path that acks NOTHING — under the EXPLICIT
    default every frame is redelivered after AckWait, and delivery stops outright once
    `max_ack_pending` (server default 1000) unacked messages accumulate, silently truncating any
    run over ~1000 frames. Nothing local reproduces that: short runs under 30s never redeliver.
    """
    config = _broadcast_consumer_config()

    assert config.ack_policy is AckPolicy.NONE
    assert config.deliver_policy is DeliverPolicy.ALL


async def test_the_stream_is_created_with_retention_limits() -> None:
    """REGRESSION (C3): an unbounded stream is the deployment's real scaling ceiling.

    JetStream's defaults are file storage with every limit infinite, so without these a single
    runaway expression can fill the NATS filestore and take every other run down with it.
    """
    js = _FakeJetStream()
    stream = _consumer(js)

    await stream.ensure_stream("t")

    config = js.add_stream_calls[0]
    assert config.name == "url4-events"
    assert list(config.subjects) == ["url4-cloud.*"]
    assert config.retention is RetentionPolicy.LIMITS
    assert config.discard is DiscardPolicy.OLD
    assert config.storage is StorageType.FILE
    assert config.max_age == 86_400.0
    assert config.max_bytes == 1024**3
    assert config.max_msgs_per_subject == 20_000
    assert config.max_msg_size == 2 * 1024**2
    assert config.duplicate_window == 120.0
    assert config.num_replicas == 1


async def test_delete_stream_purges_only_the_topics_subject_keeping_one_and_is_idempotent() -> None:
    """REGRESSION (C3): `purge` empties a subject but a run's terminal frame is the evidence the
    run is over — the worker's dedupe gate and the App's admission both read it on
    redelivery, so reclaiming a finished run must keep it. Idempotency matters because this is
    a DELETE, documented as such: a topic already reclaimed must be a 204, not a 500."""
    js = _FakeJetStream(purge_raises_not_found=True)
    stream = _consumer(js)

    await stream.delete_stream("t")
    await stream.delete_stream("t")  # already gone — must not raise

    assert js.purge_calls == [
        {"name": "url4-events", "subject": "url4-cloud.t", "keep": 1},
        {"name": "url4-events", "subject": "url4-cloud.t", "keep": 1},
    ]


async def test_purge_purges_only_the_topics_subject_with_no_keep() -> None:
    js = _FakeJetStream()
    stream = _consumer(js)

    await stream.purge("t")

    assert js.purge_calls == [{"name": "url4-events", "subject": "url4-cloud.t", "keep": None}]
