"""NATS JetStream adapter for the `EventConsumer`/`EventPublisher` ports
(`url4.streaming.interfaces`): the real, durable telemetry stream a run's frames travel over
between the Runner and the App. Subject and stream names are per-topic, derived by
`screamingface_engine.subjects.subject_for`/`stream_for` rather than reimplemented here."""

import asyncio
import logging
from collections.abc import AsyncIterator
from datetime import UTC, datetime

import nats
from nats.aio.client import Client
from nats.errors import Error as NatsError
from nats.js import JetStreamContext, api
from nats.js.api import AckPolicy, ConsumerConfig, DeliverPolicy, DiscardPolicy, StreamInfo
from nats.js.errors import APIError, BadRequestError, NotFoundError
from pydantic import ValidationError

from screamingface_engine import subjects
from screamingface_engine.subjects import owns_stream, stream_for, subject_for, topic_of
from url4.streaming.codec import decode, encode
from url4.streaming.interfaces import (
    EventConsumer,
    EventPublisher,
    StreamNotFoundError,
    validate_from_sequence,
)
from url4.streaming.protocol import OutboundFrame, TerminatedEvent

logger = logging.getLogger(__name__)

MAX_IN_FLIGHT_PUBLISHES = 1024
"""How many acknowledgements may be outstanding before `publish` parks on the semaphore.

Stated here rather than left to nats-py's default of 4000 because it is the memory bound this
module PROMISES, not an incidental library setting. It is also the whole stall defence: an
unreachable broker fills this window, `publish` then blocks, the Runner's drain stops, and its
event bridge fails at its own hard cap — bounded, and loudly.
"""


class DeferredPublishError(RuntimeError):
    """A publish this class already returned from was later rejected by the broker.

    Raised at the next `publish` or at `flush`, chained (`__cause__`) to the broker's own
    error. Wrapped rather than re-raised bare so the message says WHERE it surfaced: the
    frame that caused it is long gone by then, and a naked APIError at a later sequence
    number reads as a failure of the wrong frame.
    """


class QueueReadError(RuntimeError):
    """The stream tail could not be read — a TRANSIENT broker failure, not an answer.

    Distinct from "no frame" (which `last_frame` returns as `None`): this says the read
    itself failed — a `nats.errors.Error` that is not a JetStream `APIError` (a request
    timeout, a closed connection, a reconnect in flight). Callers that must not mistake
    "unreadable" for "empty" — the worker's claim-time dedupe gate — catch this and skip
    the claim, leaving the message for redelivery, instead of either acting on a phantom
    `None` or letting the error escape into a shared task group.
    """


# INVARIANT: `max_age` bounds the BYTES a run's frames occupy. It does NOT reclaim the stream
# object — JetStream expires messages and leaves the stream, its consumer state and its
# filestore directory in place, still holding the whole `max_bytes` reservation. Reclaiming a
# stream requires `delete_stream`, which is why reclamation is an explicit mechanism (the
# runner's own teardown, plus `_sweep_orphans` below) and not a retention setting.
DEFAULT_STREAM_MAX_AGE_S = 86_400.0
# INVARIANT: this is a RESERVATION, charged against the store the moment the stream is created
# and held even while the stream is empty. It therefore sets the concurrency ceiling directly:
# store_size / max_bytes. At the former 256 MiB against a 10Gi store that ceiling was 40 runs,
# and the 41st `add_stream` failed with 10047 — the outage this value was cut to fix.
DEFAULT_STREAM_MAX_BYTES = 50 * 1000 * 1000
# JetStream's `JSInsufficientResourcesErr`: the store cannot place another stream.
INSUFFICIENT_RESOURCES_ERR_CODE = 10047
# How long a terminated run's stream is kept before the sweep may reclaim it, so a client still
# draining the final frames is not cut off mid-read.
DEFAULT_ORPHAN_GRACE_S = 60.0
# How long an empty, unattached stream that NEVER received a message is kept before the sweep
# treats it as a run that never started. Far above pod scheduling + image pull, because the cost
# of being wrong is deleting a starting run's stream.
DEFAULT_NEVER_STARTED_S = 1_800.0
# Safety bound on the `streams_info` paging loop, far above any real broker's stream count.
_MAX_STREAM_PAGES = 100
# WHY bound the memo: it exists only to skip a round trip, so forgetting an entry costs one
# `add_stream` call. Left unbounded it is a per-topic set that grows for the process's lifetime.
_MAX_ENSURED_MEMO = 4096


def _broadcast_consumer_config(from_sequence: int | None) -> ConsumerConfig:
    """The broadcast replay reader's config: replays from the start of the stream when
    `from_sequence` is None, else resumes at that 1-based stream sequence (attach/resume, spec
    §8).

    INVARIANT: `ack_policy` is NONE, and this is load-bearing rather than a default worth
    inheriting. These consumers are broadcast replay readers — nothing here can act on a
    redelivery, and the subscription is torn down and rebuilt from a sequence on re-attach, so
    acks buy nothing. Under the EXPLICIT default, `subscribe()` without a callback never acks
    anything (nats-py only auto-acks the callback path), which means every frame is redelivered
    after AckWait and delivery stops outright once `max_ack_pending` (server default 1000)
    unacked messages pile up — i.e. any run over ~1000 frames silently truncates mid-stream.

    The run queue's consumer is the OPPOSITE of this in every way that matters; it has its own
    builder in `runner_queue` (OME-1088).
    """
    if from_sequence is None:
        return ConsumerConfig(deliver_policy=DeliverPolicy.ALL, ack_policy=AckPolicy.NONE)
    return ConsumerConfig(
        deliver_policy=DeliverPolicy.BY_START_SEQUENCE,
        opt_start_seq=from_sequence,
        ack_policy=AckPolicy.NONE,
    )


class _JetStreamConnection:
    """One lazily-opened NATS connection and the stream bookkeeping every binding needs.

    Consumer and publisher differ only in which direction they move frames; connecting,
    declaring the stream and closing are the same job, so they are written once here.
    """

    def __init__(
        self,
        nats_url: str,
        *,
        stream_max_age_s: float = DEFAULT_STREAM_MAX_AGE_S,
        stream_max_bytes: int = DEFAULT_STREAM_MAX_BYTES,
        orphan_grace_s: float = DEFAULT_ORPHAN_GRACE_S,
        never_started_s: float = DEFAULT_NEVER_STARTED_S,
        run_queue_stream: str = subjects.RUN_QUEUE_STREAM,
    ) -> None:
        self._url = nats_url
        self._stream_max_age_s = stream_max_age_s
        self._stream_max_bytes = stream_max_bytes
        self._orphan_grace_s = orphan_grace_s
        self._never_started_s = never_started_s
        # The queue stream THIS connection's sweep must never touch. Composition roots pass
        # the CONFIGURED name (`Settings.run_queue_stream`); the default keeps tests and the
        # default deployment on the constant. A sweep armed with a stale constant against a
        # renamed queue deletes the one stream an accepted run may not be lost from.
        self._run_queue_stream = run_queue_stream
        self._nc: Client | None = None
        self._js: JetStreamContext | None = None
        self._ensured: set[str] = set()
        self._connect_lock = asyncio.Lock()

    async def _jetstream(self) -> JetStreamContext:
        # WHY the lock and the second check inside it: `subscribe`/`publish` are called
        # concurrently (one WS pump per attached client, plus the sync-hold GET). Without it two
        # callers both observe `_js is None`, both connect, and one `Client` is overwritten while
        # still open — leaking its reader task and TLS pool for the life of the process, once per
        # racing pair. Re-checking under the lock is what makes the second caller reuse the first
        # connection instead of opening its own.
        js = self._js
        if js is not None and not self._is_closed():
            return js
        async with self._connect_lock:
            js = self._js
            if js is not None and not self._is_closed():
                return js
            nc = await nats.connect(self._url)
            self._nc = nc
            # The bound is inert for the consumer, which never publishes; declaring it once
            # here keeps the two bindings on one connection story.
            js = nc.jetstream(publish_async_max_pending=MAX_IN_FLIGHT_PUBLISHES)
            self._js = js
            # The declarations belonged to the connection that just died; the new one has none.
            self._ensured.clear()
            return js

    def _is_closed(self) -> bool:
        """Whether the cached connection is known-dead and must be rebuilt.

        WHY this exists: nats-py gives up after its reconnect budget is exhausted, and a handle
        cached for the process lifetime would fail every subsequent call with no path back. The
        control plane outlives any single NATS outage, so it has to be able to reconnect.

        A missing `_nc` is NOT closed: a `JetStreamContext` can be supplied without one going
        through `nats.connect` here, and treating that as dead would discard a perfectly live
        context and dial the broker instead.
        """
        nc = self._nc
        return nc is not None and nc.is_closed

    async def ensure_stream(self, topic: str) -> None:
        # WHY: `add_stream` on an existing stream is a round trip that ends in BadRequestError,
        # and every subscribe/attach/publish calls this. One instance owns one connection for
        # its whole life, so what it already declared over that connection stays declared.
        if topic in self._ensured:
            return
        js = await self._jetstream()
        try:
            await self._declare(js, topic)
        except APIError as exc:
            # WHY only this code: 10047 says the STORE is full, which a sweep can fix. Every other
            # API failure is about this request and retrying it would just fail the same way.
            if exc.err_code != INSUFFICIENT_RESOURCES_ERR_CODE:
                raise
            # INVARIANT: retry at most once, and only after the sweep actually freed something.
            # Retrying a sweep that reclaimed nothing is an infinite loop against a full store —
            # the caller has to see the real error instead of hanging.
            if await self._sweep_orphans(js) == 0:
                raise
            await self._declare(js, topic)
        if len(self._ensured) >= _MAX_ENSURED_MEMO:
            self._ensured.clear()
        self._ensured.add(topic)

    async def _declare(self, js: JetStreamContext, topic: str) -> None:
        """`add_stream`, tolerating a stream that is already declared."""
        try:
            await js.add_stream(
                name=stream_for(topic),
                subjects=[subject_for(topic)],
                max_age=self._stream_max_age_s,
                max_bytes=self._stream_max_bytes,
                discard=DiscardPolicy.OLD,
            )
        except BadRequestError:
            pass

    async def _sweep_orphans(self, js: JetStreamContext) -> int:
        """Reclaim streams whose run is over, returning how many were freed.

        WHY lazy rather than a background reaper: this runs only when the store is actually
        exhausted, so it costs nothing in the normal case and needs no scheduler, no leader
        election, and no extra RBAC. It is the backstop for runs whose pod died before its own
        teardown could run — an OOMKill or an eviction skips the runner's `finally` entirely.
        """
        freed: list[str] = []
        for info in await self._all_streams(js):
            name = info.config.name
            if name is None or not owns_stream(name, run_queue_stream=self._run_queue_stream):
                continue
            if not await self._is_orphan(js, info):
                continue
            try:
                await js.delete_stream(name)
            except NotFoundError:
                # REGRESSION (I2): NOT `continue`. Sweeps race — every runner pod and every
                # control-plane replica runs one — and this error means a CONCURRENT sweep
                # already reclaimed this stream. Its space is free either way, so not counting
                # it made the losing caller re-raise 10047 and fail a client for no reason.
                pass
            except APIError:
                # One undeletable stream must not abort the sweep and mask the 10047 that
                # triggered it; the remaining candidates are still worth trying.
                logger.warning("could not reclaim stream %s", name, exc_info=True)
                continue
            # The memo must not outlive the stream it remembers, or a re-run of this topic would
            # skip `add_stream` and publish into a stream that is no longer there.
            self._ensured.discard(topic_of(name))
            freed.append(name)
        if freed:
            # Name them: this is a destructive operation on a possibly shared broker, and this
            # list is the only forensic record an operator gets.
            logger.warning("reclaimed %d orphaned stream(s): %s", len(freed), ", ".join(freed))
        return len(freed)

    async def _all_streams(self, js: JetStreamContext) -> list[StreamInfo]:
        """Every stream on the broker, across pages.

        INVARIANT (REGRESSION I6): `streams_info()` is ONE request and the server caps a page at
        256 entries. A single call silently examines a subset, so an orphan past the boundary is
        invisible and the sweep reports nothing reclaimable while the store is full of it.
        """
        infos: list[StreamInfo] = []
        for _ in range(_MAX_STREAM_PAGES):
            page = await js.streams_info(offset=len(infos))
            if not page:
                break
            infos.extend(page)
        return infos

    async def _is_orphan(self, js: JetStreamContext, info: StreamInfo) -> bool:
        """Whether a stream is provably finished with, and so safe to delete.

        INVARIANT: deleting a stream destroys its consumers with it, cutting off every attached
        client. Both tests below therefore have to prove the run is OVER, never merely guess it.
        """
        state, name = info.state, info.config.name
        if state.messages == 0:
            # `max_age` emptied it, so there is nothing left to replay. `last_seq > 0` is
            # load-bearing: a stream created microseconds ago also reports zero messages, and
            # without this check the sweep would delete streams out from under starting runs.
            return state.last_seq > 0 or self._never_started(info)
        if name is None:
            return False
        return await self._terminated_before_grace(js, name)

    def _never_started(self, info: StreamInfo) -> bool:
        """Whether this stream's run never published anything and never will.

        INVARIANT (REGRESSION C1): `messages == 0, last_seq == 0` is not only the state of a
        stream created moments ago — it is the PERMANENT state of a topic whose runner never
        published a frame. The control plane declares the stream when a client attaches, BEFORE
        the Job is scheduled, so an ImagePullBackOff, a quota rejection, or a crash during world
        resolution strands a stream holding its whole `max_bytes` reservation, which `max_age`
        can never reclaim because there are no messages to expire. Treating that state as
        permanently-not-orphan left the sweep unable to clear the very outage it exists for.

        Two guards keep this off live runs: `created` is a SERVER-side timestamp (so no runner
        clock is trusted), and a non-zero `consumer_count` means somebody is attached and waiting.
        """
        created = info.created
        if created is None or info.state.consumer_count > 0:
            return False
        started = created if created.tzinfo is not None else created.replace(tzinfo=UTC)
        return (datetime.now(UTC) - started).total_seconds() > self._never_started_s

    async def _terminated_before_grace(self, js: JetStreamContext, name: str) -> bool:
        """Whether this stream's last frame is a terminal one, old enough to be safe to drop.

        This is what reclaims a run whose pod died between publishing its terminal frame and
        running its own teardown — an OOMKill or an eviction during the drain grace.
        """
        try:
            raw = await js.get_last_msg(name, subject_for(topic_of(name)))
            frame = decode(raw.data or b"")
        except (APIError, ValidationError):
            # Unreadable means unprovable, and unprovable means keep it.
            return False
        if not isinstance(frame, TerminatedEvent) or frame.time is None:
            return False
        ended = frame.time if frame.time.tzinfo is not None else frame.time.replace(tzinfo=UTC)
        return (datetime.now(UTC) - ended).total_seconds() > self._orphan_grace_s

    async def last_frame(self, topic: str) -> OutboundFrame | None:
        """The run's last published frame, or None when the stream is missing or empty.

        WHY this exists: the worker's dedupe check (a terminal frame already on the stream
        means the run is over — redelivery, cancel-before-claim, or stale) and its
        post-exit check (did the child publish its own terminal frame?) both need to read
        the stream's tail without subscribing. A missing stream, an empty stream, or an
        unreadable frame all read as None — the conservative direction for both checks.
        """
        try:
            js = await self._jetstream()
        except NatsError as exc:
            # The connect/declare path sits OUTSIDE the fetch's try below, so a dropped
            # broker — a failed reconnect raising a bare transport error — used to escape
            # `last_frame` unwrapped, bypassing every `except QueueReadError` guard the
            # callers rely on (review follow-up V-7 / pass-1 #11): unreadable is unreadable
            # however it was reached, so it gets the same typed translation. A JetStream
            # API verdict from the connect-time declare is translated the same way — it is
            # a config failure, and the retry-and-log shape it produces is both visible
            # and non-cascading.
            raise QueueReadError(f"queue backend unreachable for {topic}: {exc!r}") from exc
        try:
            raw = await js.get_last_msg(stream_for(topic), subject_for(topic))
        except APIError:
            # A missing stream or an empty one: a REAL answer — there is no last frame.
            return None
        except NatsError as exc:
            # Transport-level (not a JetStream API verdict): a request timeout, a closed
            # connection, a reconnect in flight. That is NOT "no frame" — translating it to
            # None would let the claim gate mistake an unreadable tail for "no terminal
            # frame" and execute a finished run a second time. Raise the typed error; the
            # callers that can safely wait catch it.
            raise QueueReadError(f"stream tail unreadable for {topic}: {exc!r}") from exc
        try:
            return decode(raw.data or b"")
        except ValidationError:
            return None

    async def stream_exists(self, topic: str) -> bool:
        """Whether the run's stream is declared on the broker.

        WHY this exists (OME-1090): the queue runner's `stop()` must tell a missing stream
        (a topic that was never attached, never scheduled — a no-op) apart from an empty
        one (a queued run whose tombstone must land), and `last_frame` deliberately
        collapses the two into None.
        """
        js = await self._jetstream()
        return await _stream_exists(js, topic)

    async def delete_stream(self, topic: str) -> None:
        """Drop a run's stream entirely, tolerating one that is already gone.

        INVARIANT: this is the only thing that reclaims a stream OBJECT. `purge_stream` empties a
        stream but leaves it, its consumer state and its filestore directory behind, so a
        purge-only teardown still adds one permanent stream to the NATS metaleader per run.
        """
        js = await self._jetstream()
        try:
            await js.delete_stream(stream_for(topic))
        except NotFoundError:
            pass
        self._ensured.discard(topic)

    async def close(self) -> None:
        if self._nc is not None:
            await self._nc.close()


async def _stream_exists(js: JetStreamContext, topic: str) -> bool:
    """Whether the Run's stream is still declared on the broker.

    `stream_info` on a missing stream raises NotFoundError; any other failure propagates.
    """
    try:
        await js.stream_info(stream_for(topic))
    except NotFoundError:
        return False
    return True


class JetStreamConsumer(_JetStreamConnection, EventConsumer):
    """The App-side consumer: subscribes to a run's JetStream subject and decodes frames back
    into `OutboundFrame`s, optionally resuming from a given sequence."""

    async def subscribe(
        self, topic: str, from_sequence: int | None = None
    ) -> AsyncIterator[OutboundFrame]:
        validate_from_sequence(from_sequence)
        js = await self._jetstream()
        if from_sequence is not None and not await _stream_exists(js, topic):
            # A resume cursor with no stream to resume from: the Run finished and the
            # Runner reclaimed the stream (spec §6 S2, OME-1019). The bridge turns this
            # into a typed `stream_reclaimed` error frame. A FRESH attach (cursor None)
            # still creates the stream — it legitimately precedes the Run's first publish.
            raise StreamNotFoundError(topic)
        await self.ensure_stream(topic)
        sub = await js.subscribe(
            subject_for(topic),
            stream=stream_for(topic),
            config=_broadcast_consumer_config(from_sequence),
        )
        # WHY: the caller may abandon this generator mid-run (a re-attach cancels the WS pump, a
        # sync GET gives up at `sync_max_wait_s`). Without the unsubscribe the push consumer keeps
        # delivering into a queue nobody drains, for the life of the connection.
        try:
            async for msg in sub.messages:
                yield decode(msg.data, sequence=msg.metadata.sequence.stream)
        finally:
            await sub.unsubscribe()

    async def purge(self, topic: str) -> None:
        # Idempotent by contract: `InMemoryEventStream.purge` creates-then-empties an unknown
        # topic and returns, so purging one that was never published to must not raise here
        # either. Without the guard `purge_stream` raises NotFoundError and the DELETE route
        # turns a 204 into a 500 — a divergence only a real broker would ever show.
        js = await self._jetstream()
        try:
            await js.purge_stream(stream_for(topic))
        except NotFoundError:
            pass


class JetStreamPublisher(_JetStreamConnection, EventPublisher):
    """The App-side publisher. Only the mock runner writes to a topic in a real deployment —
    the real Runner has its own copy, because the two deployables may not import each other.

    Publishes are PIPELINED: `publish` returns once the frame is written to the connection,
    and `flush` waits for the acknowledgements.

    WHY (OME-906): awaiting one acknowledgement per frame capped the drain at one broker round
    trip per frame, while the engine produced observation events at CPU speed. A cached DRACO
    burst therefore overflowed the Runner's event bridge — which cannot push back, because the
    engine's observer callback is synchronous — and a correct Evaluation failed.

    INVARIANT: exactly ONE task calls `publish`. `publish_async` writes to the connection
    inside the call, so a single caller hands the broker the frames in call order, and the
    broker assigns its stream sequence from that order. Two tasks void it, and the SDK finds
    gaps by exactly that sequence. This is also why the pipeline lives HERE and not in the
    lifecycle: a task per frame would bound the window just as well and lose the ordering.
    """

    def __init__(
        self,
        nats_url: str,
        *,
        stream_max_age_s: float = DEFAULT_STREAM_MAX_AGE_S,
        stream_max_bytes: int = DEFAULT_STREAM_MAX_BYTES,
        orphan_grace_s: float = DEFAULT_ORPHAN_GRACE_S,
        never_started_s: float = DEFAULT_NEVER_STARTED_S,
        run_queue_stream: str = subjects.RUN_QUEUE_STREAM,
    ) -> None:
        # Forwarded explicitly rather than through `**kwargs`: the base takes one `int` among
        # its floats, so a single widened annotation cannot type-check, and the alternative
        # was a `type: ignore` over the whole call.
        super().__init__(
            nats_url,
            stream_max_age_s=stream_max_age_s,
            stream_max_bytes=stream_max_bytes,
            orphan_grace_s=orphan_grace_s,
            never_started_s=never_started_s,
            run_queue_stream=run_queue_stream,
        )
        # A dict used as an ORDERED set. Insertion order is publish order, and `_reap` keeps
        # the first failure — meaning the one on the earliest-published frame. A plain `set`
        # iterates by hash, which made "first" whichever future it happened to yield and only
        # showed up as a test that passed alone and failed in suite order.
        self._acks: dict[asyncio.Future[api.PubAck], None] = {}
        self._deferred_failure: BaseException | None = None

    async def publish(self, topic: str, event: OutboundFrame) -> None:
        js = await self._jetstream()
        # Fail fast: a broker that started rejecting stops the run now, rather than after the
        # whole in-flight window drains.
        self._reap()
        self._raise_deferred()
        ack = await js.publish_async(subject_for(topic), encode(event))
        self._acks[ack] = None

    async def flush(self) -> None:
        if self._acks:
            await asyncio.wait(tuple(self._acks))
        self._reap()
        self._raise_deferred()

    def _reap(self) -> None:
        """Harvest every settled acknowledgement: drop it and keep the first rejection.

        WHY reaping rather than an `add_done_callback`: a callback runs through
        `loop.call_soon`, so a failure recorded there is not yet visible to a `flush` that
        happens not to await — correctness would depend on callback scheduling order. Reading
        the futures directly makes both paths deterministic.

        INVARIANT: `_acks` stays bounded. Every `publish` reaps before it adds, and `flush`
        reaps all, so it never outgrows the in-flight window
        (`MAX_IN_FLIGHT_PUBLISHES`) that nats-py's own semaphore enforces.

        Reading `exception()` here is also what stops asyncio's "exception was never
        retrieved" warning on a future nothing awaits.
        """
        for ack in tuple(self._acks):
            if not ack.done():
                continue
            del self._acks[ack]
            if ack.cancelled():
                # No broker verdict. Treating teardown as a rejection would fail a run on
                # the shutdown path.
                continue
            exc = ack.exception()
            if exc is not None and self._deferred_failure is None:
                self._deferred_failure = exc

    def _raise_deferred(self) -> None:
        """Report a recorded failure once, then forget it.

        INVARIANT: clearing is required, not tidiness. `run` reaches its `failed` arm through
        this raise, and that arm publishes AND flushes the terminal frame — if the failure
        persisted, that flush would raise too and the subscriber would wait forever for the
        one frame it is guaranteed.
        """
        exc, self._deferred_failure = self._deferred_failure, None
        if exc is not None:
            raise DeferredPublishError(
                "a JetStream publish was rejected after it returned"
            ) from exc


__all__ = ["DeferredPublishError", "JetStreamConsumer", "JetStreamPublisher", "QueueReadError"]
