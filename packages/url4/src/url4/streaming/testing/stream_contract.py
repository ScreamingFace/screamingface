from __future__ import annotations

import asyncio
import uuid
from collections.abc import Callable

from url4.streaming.interfaces import EventStream
from url4.streaming.protocol import LogData, LogEvent, OutboundFrame
from url4.streaming.testing.collect import TAKE_TIMEOUT_S, take

EventStreamFactory = Callable[[], EventStream]


def _unique_topic() -> str:
    """A fresh topic per check.

    INVARIANT: each of `_CHECKS` gets its own topic, not a shared constant. Against
    `InMemoryEventStream` a shared name was harmless — `make_bus()` returns a fresh Python object
    with private state per check. Against a real broker the topic names a PERSISTENT server-side
    stream, so a shared name let a later check inherit frames an earlier check already published
    (sequences and bodies both collided) — invisible until the contract suite ran against real
    JetStream for the first time.
    """
    return f"stream-contract-{uuid.uuid4().hex[:12]}"


def _frame(topic: str, n: int) -> LogEvent:
    return LogEvent(
        id=f"contract-{n}",
        source="/trace/contract/node/root",
        subject=topic,
        data=LogData.at("INFO", f"body-{n}"),
    )


def _body(frame: OutboundFrame) -> str:
    assert isinstance(frame, LogEvent), f"expected a LogEvent back, got {type(frame).__name__}"
    return frame.data.body


async def _take(
    stream: EventStream, topic: str, n: int, from_sequence: int | None = None
) -> list[OutboundFrame]:
    try:
        return await take(stream, topic, n, from_sequence)
    except TimeoutError as exc:  # pragma: no cover - only on a non-conforming adapter
        raise AssertionError(
            f"subscribe(from_sequence={from_sequence!r}) did not deliver {n} frames "
            f"within {TAKE_TIMEOUT_S}s — a stalled subscription looks identical to an idle "
            f"healthy one"
        ) from exc


async def _sequence_is_one_based_and_monotonic(stream: EventStream, topic: str) -> None:
    # WHY ensure_stream first: production never publishes without it. The App always attaches a
    # subscriber (which ensures the stream) before a run is scheduled — "a run must never be
    # scheduled before a subscriber is attached" — so `publish` standing alone is not itself part
    # of the contract; only `InMemoryEventStream` happens to self-ensure inside `publish`, which
    # let this gap through until a real broker (which does not) ran this check.
    await stream.ensure_stream(topic)
    for i in range(3):
        await stream.publish(topic, _frame(topic, i))
    got = await _take(stream, topic, 3)
    sequences = [f.sequence for f in got]
    assert sequences == ["1", "2", "3"], (
        f"stream sequences must be 1-based and monotonic (docs/protocol.md §6), got {sequences}"
    )
    assert [_body(f) for f in got] == ["body-0", "body-1", "body-2"], "frames must arrive in order"


async def _replay_from_sequence_is_inclusive_then_live(stream: EventStream, topic: str) -> None:
    await stream.ensure_stream(topic)
    for i in range(3):
        await stream.publish(topic, _frame(topic, i))
    replayed = await _take(stream, topic, 2, from_sequence=2)
    assert [_body(f) for f in replayed] == ["body-1", "body-2"], (
        f"from_sequence must be inclusive, got {[_body(f) for f in replayed]}"
    )

    live: list[OutboundFrame] = []

    async def _follow() -> None:
        async for event in stream.subscribe(topic, 4):
            live.append(event)
            return

    follower = asyncio.ensure_future(_follow())
    await asyncio.sleep(0)
    await stream.publish(topic, _frame(topic, 99))
    try:
        await asyncio.wait_for(follower, timeout=TAKE_TIMEOUT_S)
    except TimeoutError as exc:  # pragma: no cover - only on a non-conforming adapter
        follower.cancel()
        raise AssertionError(
            "a replay subscription must continue LIVE past the replayed gap — this one never "
            "delivered a frame published after it attached"
        ) from exc
    assert [_body(f) for f in live] == ["body-99"], f"expected the live frame, got {live}"


async def _from_sequence_below_one_is_rejected(stream: EventStream, topic: str) -> None:
    for bad in (0, -1):
        try:
            agen = stream.subscribe(topic, bad)
            await agen.__anext__()
        except ValueError:
            continue
        except Exception as exc:  # noqa: BLE001 - any other failure is still a contract breach
            raise AssertionError(
                f"subscribe(from_sequence={bad}) must raise ValueError, raised "
                f"{type(exc).__name__}: {exc}"
            ) from exc
        raise AssertionError(
            f"subscribe(from_sequence={bad}) must raise ValueError — 'None' means from the start, "
            f"and accepting {bad} silently replays the whole stream"
        )


async def _purge_drops_frames(stream: EventStream, topic: str) -> None:
    await stream.ensure_stream(topic)
    for i in range(2):
        await stream.publish(topic, _frame(topic, i))
    await stream.purge(topic)
    await stream.publish(topic, _frame(topic, 7))
    got = await _take(stream, topic, 1)
    assert _body(got[0]) == "body-7", f"purge must drop buffered frames, got {_body(got[0])!r}"


async def _reclaim_keeps_counting(stream: EventStream, topic: str) -> None:
    # WHY on `delete_stream` and not on `purge`: the reclaim is the one teardown that runs on a
    # live system (the runner's grace, `DELETE /`), so it is where a rewound counter would reuse
    # a sequence a client cursor already passed. A broker adapter whose sequence is the
    # PRODUCER's (the shared events stream) keeps the counter by keeping the run's last frame;
    # an in-process log keeps it in memory. Either way the next frame continues the count.
    await stream.ensure_stream(topic)
    for i in range(2):
        await stream.publish(topic, _frame(topic, i))
    await stream.delete_stream(topic)
    await stream.publish(topic, _frame(topic, 7))
    got = await _take(stream, topic, 1, from_sequence=3)
    assert _body(got[0]) == "body-7", f"expected the post-reclaim frame, got {_body(got[0])!r}"
    assert got[0].sequence == "3", (
        f"the reclaim must NOT rewind the stream counter (a reused sequence would break replay), "
        f"got {got[0].sequence}"
    )


async def _subscribe_before_first_publish_works(stream: EventStream, topic: str) -> None:
    # WHY ensure_stream here rather than relying on `subscribe`'s own internal ensure to have
    # completed by the time we publish: `asyncio.sleep(0)` below gives the follower task exactly
    # one scheduling turn, which is enough for a zero-latency in-memory adapter but not for one
    # doing real network I/O — its OWN ensure_stream call may still be in flight when we publish,
    # and a stream that does not exist yet rejects the publish outright (a broker error, not a
    # ordering race). Ensuring it here first removes that dependency: a genuinely conforming
    # subscribe-before-publish adapter still needs no further synchronization, because a fresh
    # subscription (no from_sequence given) replays the WHOLE stream from the start once its
    # consumer registers — it does not need to have registered before the publish happens.
    await stream.ensure_stream(topic)
    frames: list[OutboundFrame] = []

    async def _follow() -> None:
        async for event in stream.subscribe(topic):
            frames.append(event)
            return

    follower = asyncio.ensure_future(_follow())
    await asyncio.sleep(0)
    await stream.publish(topic, _frame(topic, 5))
    try:
        await asyncio.wait_for(follower, timeout=TAKE_TIMEOUT_S)
    except TimeoutError as exc:  # pragma: no cover - only on a non-conforming adapter
        follower.cancel()
        raise AssertionError(
            "subscribing before the first publish must work — the 428 interest gate makes it the "
            "normal ordering, so the stream has to be ensured rather than merely bound"
        ) from exc
    assert [_body(f) for f in frames] == ["body-5"]


async def _ensure_stream_is_idempotent(stream: EventStream, topic: str) -> None:
    await stream.ensure_stream(topic)
    await stream.ensure_stream(topic)
    await stream.publish(topic, _frame(topic, 1))
    got = await _take(stream, topic, 1)
    assert got[0].sequence == "1"


_CHECKS = (
    _ensure_stream_is_idempotent,
    _sequence_is_one_based_and_monotonic,
    _replay_from_sequence_is_inclusive_then_live,
    _from_sequence_below_one_is_rejected,
    _purge_drops_frames,
    _reclaim_keeps_counting,
    _subscribe_before_first_publish_works,
)


async def assert_stream_conformance(make_bus: EventStreamFactory) -> None:
    for check in _CHECKS:
        try:
            await check(make_bus(), _unique_topic())
        except AssertionError as exc:
            raise AssertionError(
                f"EventStream contract '{check.__name__.strip('_')}': {exc}"
            ) from exc


__all__ = ["EventStreamFactory", "assert_stream_conformance"]
