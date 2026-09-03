"""Bridges an accepted WebSocket connection to an `EventConsumer` stream and an
optional `JobRunner`, per the `url4.streaming.protocol` wire contract: inbound
attach/stop frames drive (re)subscription and job control, outbound stream
events and heartbeats are multiplexed onto the socket through a single writer.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from collections.abc import Callable
from datetime import datetime
from typing import Protocol
from uuid import uuid4

from fastapi import WebSocket, WebSocketDisconnect
from pydantic import ValidationError

from screamingface_engine import notices
from url4.streaming.codec import encode
from url4.streaming.interfaces import EventConsumer, JobRunner, StreamNotFoundError
from url4.streaming.protocol import (
    AttachEvent,
    CachePolicy,
    ErrorData,
    ErrorEvent,
    HeartbeatEvent,
    InboundFrameAdapter,
    OutboundFrame,
    StopEvent,
    source_for,
)

Clock = Callable[[], datetime]

_InboundEvent = AttachEvent | StopEvent

_logger = logging.getLogger(__name__)


def _closure_of(cause: BaseException) -> str:
    """Name how a connection ended, in the terms that separate its possible causes.

    WHY this is worth recording: a dropped Run stream reaches the researcher as one
    message no matter what caused it. The close code is what tells an oversized frame
    (1009, the client refusing what we sent) apart from a proxy draining a listener or a
    Pod going away (1006/1001), and the App is the only place that observes it — the
    client cannot report a close it never received.
    """

    if isinstance(cause, WebSocketDisconnect):
        reason = f" {cause.reason!r}" if cause.reason else ""
        return f"client close {cause.code}{reason}"
    return f"send failed: {type(cause).__name__}"


class TopicSession(Protocol):
    """The per-topic session state a bridge reads, writes and registers itself with.

    A port, not an import of the concrete registry: what a bridge needs is somewhere that outlives
    ONE connection — first-attach-wins has to hold across a reconnect and across two sockets on the
    same topic, which a per-connection object cannot express — and nothing more specific than that.
    """

    def declare_cache_policy(self, topic: str, policy: CachePolicy | None) -> bool:
        """Record ``policy`` for ``topic`` if nothing is recorded yet; ``False`` if it conflicts."""
        ...

    def cache_policy_for(self, topic: str) -> CachePolicy | None:
        """The intent standing for ``topic``, or ``None`` when none was declared."""
        ...

    def add_notifier(self, topic: str, notify: Callable[[OutboundFrame], None]) -> None:
        """Register this connection as a destination for out-of-band frames on ``topic``."""
        ...

    def remove_notifier(self, topic: str, notify: Callable[[OutboundFrame], None]) -> None:
        """Withdraw a destination registered by :meth:`add_notifier`."""
        ...


async def _send(ws: WebSocket, event: OutboundFrame) -> None:
    # WHY: through the codec, not `model_dump_json` — the outbound wire convention is decided
    # in one place, so the WS binding and the NATS binding cannot emit different JSON for one
    # frame.
    await ws.send_text(encode(event).decode())


def _heartbeat(topic: str, clock: Clock) -> HeartbeatEvent:
    return HeartbeatEvent(id=uuid4().hex, source=source_for(topic), subject=topic, time=clock())


def _error(topic: str, clock: Clock, code: str, message: str, ref_id: str | None) -> ErrorEvent:
    return ErrorEvent(
        id=uuid4().hex,
        source=source_for(topic),
        subject=topic,
        time=clock(),
        data=ErrorData(code=code, message=message, ref_id=ref_id),
    )


def _parse_inbound(raw: str) -> _InboundEvent | None:
    """Decode a raw inbound WS text frame into an attach/stop event.

    Returns None (rather than raising) on anything unparseable or failing schema
    validation, so the caller can turn it into an `invalid_frame` error event
    instead of tearing down the connection.
    """
    try:
        return InboundFrameAdapter.validate_json(raw)
    except ValidationError:
        return None


# How many frames may sit undelivered for ONE connection before the pump stops draining the
# stream. Sized to absorb an ordinary burst (a fan-out node finishing many spans at once) without
# letting a stalled reader accumulate a run's entire history in memory.
OUTBOUND_QUEUE_MAX_FRAMES = 1024


class Bridge:
    """Owns the lifecycle of one WS connection: an inbound task that parses attach/stop
    frames and drives (re)subscription to the topic's event stream, and an outbound
    writer that drains a shared queue to the socket, falling back to heartbeats when
    the queue is idle. Either side failing (disconnect, send error) stops the other.
    """

    def __init__(
        self,
        ws: WebSocket,
        stream: EventConsumer,
        topic: str,
        *,
        job_runner: JobRunner | None,
        sessions: TopicSession,
        clock: Clock,
        heartbeat_s: float,
    ) -> None:
        self._ws = ws
        self._stream = stream
        self._topic = topic
        self._job_runner = job_runner
        self._sessions = sessions
        self._clock = clock
        self._heartbeat_s = heartbeat_s
        # INVARIANT: bounded. `_pump` awaits `put`, so a full queue is BACKPRESSURE — the pump
        # stops draining the stream until the client catches up, instead of buffering the run's
        # whole frame history in this process's heap. An unbounded queue turns one slow or stalled
        # reader (a paused browser tab, a stalled TCP window) into unbounded server memory, and
        # every attached client has its own queue.
        self._out: asyncio.Queue[OutboundFrame] = asyncio.Queue(maxsize=OUTBOUND_QUEUE_MAX_FRAMES)
        self._stop = asyncio.Event()
        self._sub: asyncio.Task[None] | None = None
        # Enough to attribute a drop without keeping any of the run's payload: how the
        # socket ended, how long it lasted, and whether it was carrying work or idling.
        # A long connection with only heartbeats reads as an idle cut; a short one that
        # ended right after real frames reads as the peer refusing what it was sent.
        self._closure = "no close observed"
        self._frames_sent = 0
        self._heartbeats_sent = 0

    def _offer(self, frame: OutboundFrame) -> None:
        """Queue an advisory frame, dropping it if the client is already too far behind.

        WHY dropping is right here and blocking is not: these are nacks and notices produced from
        the inbound task and from a done-callback, neither of which may block. A full queue
        already means the client is not reading, so a nack it would receive 1024 frames from now
        has no value — and `put_nowait` on a BOUNDED queue raises QueueFull, which in a
        done-callback is swallowed and in `_inbound` would tear down the connection.
        """
        try:
            self._out.put_nowait(frame)
        except asyncio.QueueFull:
            pass

    async def run(self) -> None:
        """Run the connection until it ends, then cancel and drain both tasks.

        Blocks for the connection's whole lifetime: either the inbound task
        observes a disconnect or the writer fails to send, and both paths set
        `_stop`, which is the only way this coroutine returns.

        The connection is registered as a notice destination for its topic for exactly this
        window, and withdrawn in `finally`. That is what lets a REST handler — which has no socket
        of its own and, in a deployed App, no publisher either — tell an attached client that
        something it declared was overridden. `_offer` is the sink because it is already the
        non-blocking, drop-if-behind path every other advisory frame takes.
        """
        self._sessions.add_notifier(self._topic, self._offer)
        opened = time.monotonic()
        inbound = asyncio.ensure_future(self._inbound())
        writer = asyncio.ensure_future(self._writer())
        try:
            await self._stop.wait()
        finally:
            self._sessions.remove_notifier(self._topic, self._offer)
            await self._teardown(inbound, writer)
            _logger.info(
                "ws stream ended topic=%s duration_s=%.1f frames=%d heartbeats=%d outcome=%s",
                self._topic,
                time.monotonic() - opened,
                self._frames_sent,
                self._heartbeats_sent,
                self._closure,
            )

    async def _inbound(self) -> None:
        # INVARIANT: `_stop` is set in `finally` regardless of how this loop exits, so
        # a client disconnect here always unblocks `run()` and tears down `_writer`.
        try:
            while True:
                event = _parse_inbound(await self._ws.receive_text())
                if event is None:
                    self._offer(
                        _error(
                            self._topic,
                            self._clock,
                            "invalid_frame",
                            "unparseable or invalid inbound frame",
                            None,
                        )
                    )
                    continue
                await self._handle(event)
        except WebSocketDisconnect as exc:
            self._closure = _closure_of(exc)
        finally:
            self._stop.set()

    async def _handle(self, event: _InboundEvent) -> None:
        """Dispatch a validated inbound frame: attach (re)subscribes the stream from
        the given cursor, stop delegates to the job runner if one is configured, or
        else queues an `unsupported` error frame.
        """
        if isinstance(event, AttachEvent):
            _logger.info(
                "ws attach topic=%s from_sequence=%s",
                self._topic,
                event.data.from_sequence,
            )
            # ORDER MATTERS, and only in this direction: the declaration is recorded before the
            # subscription is (re)started, so a run cannot be scheduled — nor a replayed frame
            # delivered — under a policy the session state has not seen yet.
            self._declare_cache(event.data.cache)
            self._resubscribe(event.data.from_sequence)
        elif isinstance(event, StopEvent):
            if self._job_runner is not None:
                await self._job_runner.stop(self._topic)
            else:
                self._offer(
                    _error(
                        self._topic,
                        self._clock,
                        "unsupported",
                        "stop not supported: no job runner configured",
                        event.id,
                    )
                )

    def _declare_cache(self, policy: CachePolicy | None) -> None:
        """Carry the attach frame's cache intent into the topic's session state.

        FIRST ATTACH WINS (spec §5.2). A re-attach — a reconnect, a `from_sequence` resume, or a
        second socket on the same topic — does NOT restate the policy: the run's aigateway calls
        may already have executed under the standing one, so accepting a change mid-run would make
        the run's cache behaviour unreproducible after the fact.

        WHY it warns rather than nacks: the frame is otherwise perfectly valid and its
        resubscription is honoured in full, so refusing it would cost the client its replay over a
        directive about cost. `warn` says the intent was dropped, loudly enough to debug "I asked
        for no caching and something still cached" and quietly enough not to break the resume.
        """
        if self._sessions.declare_cache_policy(self._topic, policy):
            return
        self._offer(
            notices.warn(
                self._topic,
                self._clock,
                "the run's cache policy is fixed by its first attach; this re-attach declared a "
                "different one and it was ignored",
                {
                    "cache.declared": notices.rendered(policy),
                    "cache.effective": notices.rendered(
                        self._sessions.cache_policy_for(self._topic)
                    ),
                },
            )
        )

    def _resubscribe(self, cursor: int | None) -> None:
        # WHY: an attach mid-connection (e.g. client resuming after a gap) replaces
        # the running subscription rather than layering a second one, so at most one
        # pump task is ever forwarding events into `_out`.
        if self._sub is not None:
            self._sub.cancel()
        sub = asyncio.ensure_future(self._pump(cursor))
        sub.add_done_callback(self._on_pump_done)
        self._sub = sub

    def _on_pump_done(self, task: asyncio.Task[None]) -> None:
        # WHY: a cancellation here means `_resubscribe` (or teardown) intentionally
        # replaced/stopped this pump — not a failure — so it is not reported.
        if task.cancelled():
            return
        exc = task.exception()
        if exc is None:
            return
        if isinstance(exc, StreamNotFoundError):
            # OME-1019: a resume cursor with no stream is FINAL — the Run finished and the
            # Runner reclaimed the stream (grace elapsed). Typed, so a reconnecting client
            # stops instead of treating it as a transient `stream_failed`.
            self._offer(
                _error(
                    self._topic,
                    self._clock,
                    "stream_reclaimed",
                    "this run's stream was reclaimed: the run finished and the reclaim "
                    "grace elapsed before this client re-attached; no further frames will "
                    "arrive",
                    None,
                )
            )
            return
        self._offer(
            _error(
                self._topic,
                self._clock,
                "stream_failed",
                f"the topic subscription failed ({type(exc).__name__}); re-attach to resume",
                None,
            )
        )

    async def _pump(self, cursor: int | None) -> None:
        """Forward stream events for `_topic`, from `cursor` onward, into `_out`."""
        async for event in self._stream.subscribe(self._topic, cursor):
            await self._out.put(event)

    async def _writer(self) -> None:
        try:
            while not self._stop.is_set():
                if not await self._try_send(await self._next()):
                    break
        finally:
            self._stop.set()

    async def _next(self) -> OutboundFrame:
        # WHY: the timeout is what turns an idle `_out` queue into a heartbeat
        # cadence — without it, a quiet topic would leave the socket silent long
        # enough for intermediaries (proxies, load balancers) to consider it dead.
        try:
            return await asyncio.wait_for(self._out.get(), timeout=self._heartbeat_s)
        except TimeoutError:
            return _heartbeat(self._topic, self._clock)

    async def _try_send(self, event: OutboundFrame) -> bool:
        """Send one frame; return False (rather than raising) on disconnect so the
        writer loop can stop cleanly instead of propagating a send error.
        """
        try:
            await _send(self._ws, event)
        except (WebSocketDisconnect, RuntimeError) as exc:
            self._closure = _closure_of(exc)
            return False
        # Counted on the way OUT, not on creation: only a frame that actually left the
        # socket says anything about what the peer received before it went away.
        if isinstance(event, HeartbeatEvent):
            self._heartbeats_sent += 1
        else:
            self._frames_sent += 1
        return True

    async def _teardown(self, *tasks: asyncio.Task[None]) -> None:
        # INVARIANT: the active pump subscription (`_sub`) is always cancelled here
        # alongside the inbound/writer tasks passed in, so `run()` never returns
        # while a subscription is still forwarding events into `_out`.
        pending = [task for task in (self._sub, *tasks) if task is not None]
        for task in pending:
            task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await asyncio.gather(*pending, return_exceptions=True)


async def run_bridge(
    ws: WebSocket,
    stream: EventConsumer,
    topic: str,
    *,
    job_runner: JobRunner | None,
    sessions: TopicSession,
    clock: Clock,
    heartbeat_s: float,
) -> None:
    """Construct a `Bridge` for an already-accepted socket and run it to completion.

    The public entry point for the WS endpoint; blocks until the connection ends
    (client disconnect or an unrecoverable send failure).
    """
    await Bridge(
        ws,
        stream,
        topic,
        job_runner=job_runner,
        sessions=sessions,
        clock=clock,
        heartbeat_s=heartbeat_s,
    ).run()
