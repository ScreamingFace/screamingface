from collections.abc import AsyncGenerator
from types import SimpleNamespace
from typing import Any, cast

import pytest
from nats.js import JetStreamContext
from nats.js.errors import BadRequestError, NotFoundError

from screamingface_engine.adapters.jetstream import JetStreamConsumer
from url4.streaming.codec import encode
from url4.streaming.interfaces import StreamNotFoundError
from url4.streaming.protocol import LogData, LogEvent, OutboundFrame, source_for

pytestmark = pytest.mark.asyncio


class _FakeMsg:
    """One delivered message, shaped like the `nats-py` message the adapter decodes."""

    def __init__(self, n: int) -> None:
        self.data = encode(
            LogEvent(
                id=f"e{n}",
                source=source_for("topic-a", "root"),
                subject="topic-a",
                data=LogData.at("INFO", f"msg-{n}"),
            )
        )
        self.metadata = SimpleNamespace(sequence=SimpleNamespace(stream=n + 1))


class _FakeSub:
    def __init__(self, count: int = 0) -> None:
        self.unsubscribed = False
        self._count = count

    @property
    def messages(self) -> Any:
        async def _msgs() -> Any:
            for n in range(self._count):
                yield _FakeMsg(n)

        return _msgs()

    async def unsubscribe(self) -> None:
        self.unsubscribed = True


class _FakeJetStream:
    def __init__(self, messages_per_sub: int = 0) -> None:
        self.calls: list[str] = []
        self.subs: list[_FakeSub] = []
        self._messages_per_sub = messages_per_sub
        self._stream_declared = False

    async def stream_info(self, name: str) -> object:
        self.calls.append("stream_info")
        if not self._stream_declared:
            raise NotFoundError
        return object()

    async def add_stream(
        self,
        name: str,
        subjects: list[str],
        *,
        max_age: float | None = None,
        max_bytes: int | None = None,
        discard: object = None,
        **_: object,
    ) -> object:
        self.calls.append("add_stream")
        already = self._stream_declared
        self._stream_declared = True
        self.stream_limits = {"max_age": max_age, "max_bytes": max_bytes, "discard": discard}
        # Mirror the real broker: re-declaring an existing stream is a BadRequestError the
        # adapter's ensure_stream tolerates (`_declare` swallows it).
        if already:
            raise BadRequestError
        return object()

    async def subscribe(self, subject: str, **kwargs: Any) -> _FakeSub:
        self.calls.append("subscribe")
        sub = _FakeSub(self._messages_per_sub)
        self.subs.append(sub)
        return sub


@pytest.mark.anyio
async def test_subscribe_ensures_the_stream_before_binding_to_it() -> None:
    stream = JetStreamConsumer("nats://unused:4222")
    js = _FakeJetStream()
    stream._js = cast(JetStreamContext, js)

    async for _ in stream.subscribe("topic-a"):  # pragma: no branch - drains an empty stream
        pass

    assert js.calls == ["add_stream", "subscribe"]


@pytest.mark.anyio
async def test_resume_cursor_on_missing_stream_is_stream_not_found() -> None:
    """OME-1019: a resume cursor on a stream the Runner reclaimed is a typed error,
    not a silent re-creation. The fresh attach above keeps creating the stream."""
    stream = JetStreamConsumer("nats://unused:4222")
    js = _FakeJetStream()
    stream._js = cast(JetStreamContext, js)  # noqa: SLF001

    with pytest.raises(StreamNotFoundError):
        async for _ in stream.subscribe("topic-a", from_sequence=3):
            pass  # pragma: no cover - the generator raises before yielding

    assert js.calls == ["stream_info"]


@pytest.mark.anyio
async def test_resume_cursor_on_existing_stream_binds_without_recreating() -> None:
    stream = JetStreamConsumer("nats://unused:4222")
    js = _FakeJetStream()
    js._stream_declared = True  # the stream exists; re-declare will be a tolerated error
    stream._js = cast(JetStreamContext, js)  # noqa: SLF001

    async for _ in stream.subscribe("topic-a", from_sequence=3):  # pragma: no branch
        pass

    # The stream is probed (exists), the redundant declare is a tolerated round trip, and
    # the consumer binds from the cursor — no re-creation happens.
    assert js.calls == ["stream_info", "add_stream", "subscribe"]


@pytest.mark.anyio
async def test_abandoning_the_iterator_releases_the_subscription() -> None:
    """INVARIANT: a re-attach cancels the WS pump and a sync GET gives up at `sync_max_wait_s`,
    both mid-iteration. Leaving the push consumer bound would keep delivering into a queue
    nobody drains, once per attach, for the life of the NATS connection."""
    stream = JetStreamConsumer("nats://unused:4222")
    js = _FakeJetStream(messages_per_sub=3)
    stream._js = cast(JetStreamContext, js)

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
    from nats.js.api import AckPolicy

    from screamingface_engine.adapters.jetstream import _broadcast_consumer_config

    assert _broadcast_consumer_config(None).ack_policy is AckPolicy.NONE
    assert _broadcast_consumer_config(7).ack_policy is AckPolicy.NONE


async def test_streams_are_created_with_retention_limits() -> None:
    """REGRESSION (C3): an unbounded stream per run is the deployment's real scaling ceiling.

    JetStream's defaults are file storage with every limit infinite, so without these a single
    runaway expression can fill the NATS filestore and take every other run down with it.
    """
    js = _FakeJetStream()
    stream = JetStreamConsumer("nats://unused:4222")
    stream._js = cast(JetStreamContext, js)  # noqa: SLF001

    await stream.ensure_stream("t")

    limits = js.stream_limits
    assert limits["max_age"] and limits["max_age"] > 0
    assert limits["max_bytes"] and limits["max_bytes"] > 0
    assert limits["discard"] is not None


async def test_delete_stream_reclaims_the_stream_object_and_is_idempotent() -> None:
    """REGRESSION (C3): `purge` empties a stream but leaves the object, its consumer state and its
    filestore directory — so a purge-only teardown still adds one permanent stream per run.

    Idempotency matters because DELETE is documented as such: a topic already reclaimed must be a
    204, not a 500.
    """
    from nats.js.errors import NotFoundError

    class _DeletingJetStream(_FakeJetStream):
        def __init__(self) -> None:
            super().__init__()
            self.deleted: list[str] = []
            self.exists = True

        async def delete_stream(self, name: str) -> bool:
            if not self.exists:
                raise NotFoundError
            self.exists = False
            self.deleted.append(name)
            return True

    js = _DeletingJetStream()
    stream = JetStreamConsumer("nats://unused:4222")
    stream._js = cast(JetStreamContext, js)  # noqa: SLF001

    await stream.delete_stream("t")
    await stream.delete_stream("t")  # already gone — must not raise

    assert len(js.deleted) == 1
