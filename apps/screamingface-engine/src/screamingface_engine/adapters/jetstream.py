"""NATS JetStream adapter for the `EventConsumer`/`EventPublisher` ports
(`url4.streaming.interfaces`): the real, durable telemetry stream a run's frames travel over
between the Runner and the App.

Every run shares ONE stream, `url4-events`; a run is its subject `url4-cloud.<topic>`
(`screamingface_engine.subjects.subject_for`). The sequence a subscriber sees is the PRODUCER
sequence carried in the frame, gap-free per topic (uniform executor, erd.md §5 I-EV1..I-EV4).
It is not the stream sequence: in a shared stream that one has gaps inside every run."""

import asyncio
import logging
from collections import Counter
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass
from enum import Enum
from typing import NoReturn

import nats
from nats.aio.client import Client
from nats.errors import Error as NatsError
from nats.js import JetStreamContext, api
from nats.js.api import (
    AckPolicy,
    ConsumerConfig,
    DeliverPolicy,
    DiscardPolicy,
    Header,
    RetentionPolicy,
    StorageType,
    StreamConfig,
    StreamInfo,
)
from nats.js.errors import APIError, NotFoundError
from pydantic import ValidationError

from screamingface_engine import subjects
from screamingface_engine.readiness import StreamNotReadyError
from screamingface_engine.subjects import owns_stream, subject_for
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

# JetStream's `JSStreamWrongLastSequenceErrF`: `Nats-Expected-Last-Subject-Sequence` did not
# match, i.e. another writer appended to the subject after this writer read its tail.
WRONG_LAST_SEQUENCE_ERR_CODE = 10071
# JetStream's `JSInsufficientResourcesErr`: the store cannot hold a stream this large.
INSUFFICIENT_RESOURCES_ERR_CODE = 10047
# JetStream's `JSStreamNameExistErr`: a stream of this name exists with a different config.
STREAM_NAME_IN_USE_ERR_CODE = 10058
# JetStream's `JSStreamSubjectOverlapErr`: another stream already captures some of these subjects.
SUBJECTS_OVERLAP_ERR_CODE = 10065
# JetStream's `JSStreamNotFoundErr`, as distinct from "no message on this subject" (10037).
STREAM_NOT_FOUND_ERR_CODE = 10059
MAX_CONDITIONAL_ATTEMPTS = 3
"""How often a non-child writer re-reads the tail after a conflict before it gives up (C7)."""
URL4_SEQ_HEADER = "Url4-Seq"
"""The frame's producer sequence as a NATS header — for operators and tools (erd.md §6)."""
# Safety bound on the `streams_info` paging loop, far above any real broker's stream count.
_MAX_STREAM_PAGES = 100


@dataclass(frozen=True)
class EventsStreamConfig:
    """The shared events stream (erd.md §5). Defaults are the chart defaults.

    `max_bytes` is NOT a per-run reservation any more: one stream holds every run, so the
    concurrency ceiling that per-run reservations set (store ÷ 50 MB) is gone. When the store is
    full, JetStream drops the OLDEST frames of any subject (ans:Q11), and a gauge reports it.
    """

    name: str = subjects.EVENTS_STREAM
    subjects: tuple[str, ...] = (f"{subjects.PREFIX}.*",)
    max_age_s: float = 86_400.0
    max_bytes: int = 1024**3
    max_msgs_per_subject: int = 20_000
    # A 1 MiB result body plus its JSON escaping and the envelope.
    max_msg_size: int = 2 * 1024**2
    duplicate_window_s: float = 120.0
    replicas: int = 1
    storage: StorageType = StorageType.FILE
    # The cap on a RETAINED (failed/timed_out) run's subject, applied by `trim_retained`
    # (OME-1462). Not broker config — `stream_config` never sends them — and not chart values:
    # the run child builds its publisher with these defaults (ledger D1).
    retained_max_msgs: int = 256
    retained_max_bytes: int = 1024**2

    def stream_config(self) -> StreamConfig:
        return StreamConfig(
            name=self.name,
            subjects=list(self.subjects),
            retention=RetentionPolicy.LIMITS,
            storage=self.storage,
            discard=DiscardPolicy.OLD,
            max_age=self.max_age_s,
            max_bytes=self.max_bytes,
            max_msgs_per_subject=self.max_msgs_per_subject,
            max_msg_size=self.max_msg_size,
            duplicate_window=self.duplicate_window_s,
            num_replicas=self.replicas,
        )


class EventsStreamConfigError(RuntimeError):
    """The events stream cannot be declared as configured. Startup fails with this."""


READINESS_DIAL_TIMEOUT_S = 3.0
"""How long `check_ready` may spend establishing a connection before it answers NOT READY.

Sized BELOW the chart's `readinessProbe.timeoutSeconds` (5s) on purpose: the App must decide
and answer while the kubelet is still listening. If the kubelet times out first the handler is
NOT cancelled — Starlette has no way to — and the probes stack up on `_connect_lock` for the
duration of the outage. Answering "not ready" early is free: the next probe is `periodSeconds`
away and a slow dial is indistinguishable from an unreachable broker to everything downstream.
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


# The fields an operator may change on a live stream. `storage` and `retention` are fixed at
# creation; a mismatch there fails startup and names the field (erd.md §10).
_MUTABLE_FIELDS = (
    "max_bytes",
    "max_age",
    "max_msgs_per_subject",
    "max_msg_size",
    "duplicate_window",
    "num_replicas",
)
_IMMUTABLE_FIELDS = ("storage", "retention")


async def ensure_events_stream(
    js: JetStreamContext, config: EventsStreamConfig, *, update: bool
) -> None:
    """Create the events stream, or check (and with `update`, apply) its config.

    `update=True` is for the App and the worker at startup: they own the chart values, so a
    changed mutable limit is applied. `update=False` is the lazy path every other connection
    takes (a child, a test harness): it creates a missing stream but never rewrites a live one,
    so a process with default limits cannot shrink the operator's stream.
    """
    # WHY look before creating (kind K6/K12 finding): `add_stream` on an EXISTING stream makes the
    # server reserve its `max_bytes` a second time before it notices the config is identical, so
    # every restart of a process failed with 10047 once `max_bytes` exceeded half the store.
    # Only a missing stream is created; an existing one is reconciled.
    try:
        await js.stream_info(config.name)
    except NotFoundError:
        try:
            await js.add_stream(config.stream_config())
            return
        except APIError as exc:
            if update and exc.err_code == SUBJECTS_OVERLAP_ERR_CODE:
                if await _migrate_from_per_run_streams(js, config):
                    return
            # A racing process created it first (name in use): reconcile below.
            elif exc.err_code != STREAM_NAME_IN_USE_ERR_CODE:
                await _raise_declare_error(js, config, exc)
    await _reconcile(js, config, update=update)


async def _migrate_from_per_run_streams(js: JetStreamContext, config: EventsStreamConfig) -> bool:
    """Delete the former layout's per-run streams, then declare the shared stream ONCE more.

    True when this call created the stream; False when a racing process did (reconcile it).

    FEATURE (rollout, owner decision 2026-09-27): the App and the worker migrate the broker at
    startup, so a GitOps auto-sync upgrades with no hook and no manual purge. Frames of runs
    still in flight on a legacy stream are lost at the cut-over — accepted by the owner.
    INVARIANT: once the shared stream exists, JetStream refuses any stream overlapping it, so an
    old App still serving during the rollout cannot re-create a legacy stream after this.
    WHY exactly one retry: an overlap the purge cannot remove is a stranger's stream
    (`owns_stream` never deletes one), and a loop would only hide it.
    """
    deleted = await purge_legacy_streams(js, dry_run=False)
    logger.warning(
        "events stream %s: deleted %d legacy per-run stream(s) at startup",
        config.name,
        len(deleted),
    )
    try:
        await js.add_stream(config.stream_config())
    except APIError as exc:
        if exc.err_code != STREAM_NAME_IN_USE_ERR_CODE:
            await _raise_declare_error(js, config, exc)
        return False
    return True


async def _reconcile(js: JetStreamContext, config: EventsStreamConfig, *, update: bool) -> None:
    """Fail on a changed immutable field; with `update`, apply changed mutable limits."""
    wanted = config.stream_config()
    current = (await js.stream_info(config.name)).config
    for field in _IMMUTABLE_FIELDS:
        if getattr(current, field) != getattr(wanted, field):
            raise EventsStreamConfigError(
                f"events stream {config.name!r}: `{field}` is {getattr(current, field)} on the "
                f"broker but configured as {getattr(wanted, field)}; it cannot change on a live "
                f"stream — delete the stream during a drained rollout, or revert the setting"
            )
    if not update or all(getattr(current, f) == getattr(wanted, f) for f in _MUTABLE_FIELDS):
        return
    try:
        await js.update_stream(wanted)
    except APIError as exc:
        await _raise_declare_error(js, config, exc)
    logger.info("events stream %s: applied changed limits", config.name)


async def _raise_declare_error(
    js: JetStreamContext, config: EventsStreamConfig, exc: APIError
) -> NoReturn:
    """Raise the startup error for a declaration the broker refused: a named one when an
    operator can act on it, else the broker's own error."""
    if exc.err_code == INSUFFICIENT_RESOURCES_ERR_CODE:
        raise await _store_too_small(js, config) from exc
    if exc.err_code == SUBJECTS_OVERLAP_ERR_CODE:
        # WHY a startup failure with instructions: every per-run stream of the former layout
        # (`url4-cloud_<topic>`) captures one `url4-cloud.<topic>` subject, and JetStream refuses
        # a stream whose subjects overlap another's. So the legacy streams must be gone BEFORE
        # the first process of this version starts.
        raise EventsStreamConfigError(
            f"events stream {config.name!r}: its subjects {list(config.subjects)} overlap an "
            f"existing stream — a legacy per-run stream (the App and the worker delete those "
            f"at startup; `screamingface-engine admin purge-legacy-streams` does it by hand) "
            f"or another workload's stream on a shared broker, which must be moved"
        ) from exc
    raise exc


async def _store_too_small(js: JetStreamContext, config: EventsStreamConfig) -> Exception:
    try:
        limits = (await js.account_info()).limits
        store = f"account max_storage={limits.max_storage}"
    except (APIError, NatsError):
        store = "store limit unreadable"
    return EventsStreamConfigError(
        f"events.maxBytes={config.max_bytes} does not fit the JetStream file store ({store}); "
        f"lower events.maxBytes or grow the NATS store"
    )


async def events_store_usage(js: JetStreamContext, config: EventsStreamConfig) -> tuple[int, float]:
    """(bytes held, bytes ÷ max_bytes) of the events stream, as the BROKER reports it.

    The ratio uses the broker's `max_bytes`, not `config`'s: the gauge must describe the stream
    that exists, even while a changed limit waits for the next startup.
    """
    info = await js.stream_info(config.name)
    used = info.state.bytes
    limit = info.config.max_bytes or 0
    return used, (used / limit if limit > 0 else 0.0)


async def purge_legacy_streams(
    js: JetStreamContext,
    *,
    dry_run: bool,
    run_queue_stream: str = subjects.RUN_QUEUE_STREAM,
) -> list[str]:
    """Delete every per-run stream (`url4-cloud_<topic>`) of the former layout.

    Run once after the drained rollout to the shared stream (erd.md §10). `owns_stream` is the
    same ownership rule the former sweep used: it never matches the run queue, the events stream
    (`url4-events` does not start with `url4-cloud_`), or a stranger's stream on a shared broker.
    """
    legacy = [
        name
        for info in await _all_streams(js)
        if (name := info.config.name) is not None
        and owns_stream(name, run_queue_stream=run_queue_stream)
    ]
    for name in legacy:
        # Name each one: this is destructive on a possibly shared broker, and this line is
        # the only forensic record an operator gets.
        logger.warning("%s legacy stream %s", "would delete" if dry_run else "deleting", name)
        if dry_run:
            continue
        try:
            await js.delete_stream(name)
        except NotFoundError:
            pass
        except APIError:
            # One undeletable stream must not stop the purge; the operator re-runs it.
            logger.warning("could not delete legacy stream %s", name, exc_info=True)
    return legacy


async def _all_streams(js: JetStreamContext) -> list[StreamInfo]:
    """Every stream on the broker, across pages.

    INVARIANT (REGRESSION I6): `streams_info()` is ONE request and the server caps a page at
    256 entries. A single call silently examines a subset.
    """
    infos: list[StreamInfo] = []
    for _ in range(_MAX_STREAM_PAGES):
        page = await js.streams_info(offset=len(infos))
        if not page:
            break
        infos.extend(page)
    return infos


def _producer_sequence(frame: OutboundFrame | None) -> int:
    return int(frame.sequence) if frame is not None and frame.sequence else 0


def _broadcast_consumer_config() -> ConsumerConfig:
    """The broadcast replay reader's config: every retained frame of ONE subject, from its start.

    A resume cursor is a PRODUCER sequence, which maps to no stream position, so resume reads
    the subject from its start and drops the frames below the cursor (C8). The scan is bounded
    by `max_msgs_per_subject`.

    INVARIANT: `ack_policy` is NONE, and this is load-bearing rather than a default worth
    inheriting. These consumers are broadcast replay readers — nothing here can act on a
    redelivery, and the subscription is torn down and rebuilt on re-attach, so acks buy
    nothing. Under the EXPLICIT default, `subscribe()` without a callback never acks anything
    (nats-py only auto-acks the callback path), which means every frame is redelivered after
    AckWait and delivery stops outright once `max_ack_pending` (server default 1000) unacked
    messages pile up — i.e. any run over ~1000 frames silently truncates mid-stream.

    The run queue's consumer is the OPPOSITE of this in every way that matters; it has its own
    builder in `runner_queue` (OME-1088).
    """
    return ConsumerConfig(deliver_policy=DeliverPolicy.ALL, ack_policy=AckPolicy.NONE)


class _JetStreamConnection:
    """One lazily-opened NATS connection and the stream bookkeeping every binding needs.

    Consumer and publisher differ only in which direction they move frames; connecting,
    declaring the stream and closing are the same job, so they are written once here.
    """

    def __init__(self, nats_url: str, *, events: EventsStreamConfig | None = None) -> None:
        self._url = nats_url
        self._events = events if events is not None else EventsStreamConfig()
        self._nc: Client | None = None
        self._js: JetStreamContext | None = None
        self._declared = False
        self._connect_lock = asyncio.Lock()
        # Read by the metrics collectors (sync, at scrape time); written by the async paths.
        self.store_snapshot: tuple[int, float] | None = None
        self.subject_purges = 0

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
            # The declaration belonged to the connection that just died; re-check on this one.
            self._declared = False
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

    async def check_ready(self) -> None:
        """Report whether THIS binding can reach its broker (OME-942); raise if it cannot.

        Serves `/readyz`, which the chart's readinessProbe targets. A pod whose own NATS
        connection is dead cannot bridge a run's frames, so it should leave the Service's
        endpoints rather than stay in rotation.

        SCOPE, stated exactly (review round 2): this reports on the connection the object it is
        called on owns, and on nothing else. `app.state.stream` is the JetStream CONSUMER, so
        `/readyz` covers the App's frame bridge. The queue runner (`QueueJobRunner`) holds
        SEPARATE connections — `RunQueue`, `JetStreamPublisher`, `ControlClient` — and is not
        probed here. Widening the probe to those would widen the blast radius of a broker
        outage, which is an availability trade the owner has not signed off (ledger D7).

        WHY `is_connected` and NOT `_is_closed`: nats-py keeps the client object alive and
        retrying for its whole reconnect budget, and only then marks it closed. `is_closed`
        alone therefore reports READY throughout an outage — the entire window the probe
        exists to cover.

        WHY no `account_info()` round trip: a kubelet probes every `periodSeconds` forever, so
        an RPC here would put a broker round trip on that timer for every pod of every
        deployment. `Client` already maintains this state; reading it is the cheap, honest
        check.

        WHY the dial is BOUNDED (review round 2): `_jetstream()` dials when `_js` is None or
        the cached client is closed — exactly the outage the probe exists for — and nats-py
        retries `max_reconnect_attempts` servers, `reconnect_time_wait` apart, before raising
        `NoServersError`. Unbounded, one probe parks far past the kubelet's `timeoutSeconds`;
        Starlette does not cancel the handler when the kubelet gives up, so the next probe
        queues on `_connect_lock` behind it and pending handlers accumulate for the whole
        outage — on the loop that pumps every WebSocket. `wait_for` cancels the dial, which
        unwinds `async with self._connect_lock` and leaves the next probe its own budget.

        INVARIANT: every transport failure is translated into `StreamNotReadyError`, whose
        message is a FIXED literal. It reaches an unauthenticated caller through `/readyz`, so
        neither `self._url` (free-form operator input; `nats://user:pass@host` is the standard
        nats-py auth form) nor the broker's own exception text may appear in it. The detail is
        chained as `__cause__` and logged by `stream_readiness`, server-side.
        """
        try:
            await asyncio.wait_for(self._jetstream(), timeout=READINESS_DIAL_TIMEOUT_S)
        except TimeoutError as exc:
            raise StreamNotReadyError("event stream broker dial timed out") from exc
        except (OSError, NatsError) as exc:
            raise StreamNotReadyError("event stream broker is unreachable") from exc
        nc = self._nc
        # A missing client is NOT unready, for the same reason `_is_closed` says so: a
        # `JetStreamContext` can be supplied without going through `nats.connect`, and calling
        # that down would report a live injected context as an outage.
        if nc is not None and not nc.is_connected:
            raise StreamNotReadyError("event stream broker is not connected")

    async def ensure_stream(self, topic: str) -> None:
        """Make sure the SHARED stream exists. `topic` is part of the port and unused here:
        a topic is a subject, and a subject needs no declaration."""
        del topic
        if self._declared:
            return
        await ensure_events_stream(await self._jetstream(), self._events, update=False)
        self._declared = True

    async def declare_events_stream(self) -> None:
        """Startup declaration by a process that owns the configured limits (App, worker):
        create the stream, apply changed mutable limits, fail on an immutable mismatch."""
        await ensure_events_stream(await self._jetstream(), self._events, update=True)
        self._declared = True

    async def refresh_store_usage(self) -> tuple[int, float]:
        """Read the events stream's (bytes, utilization) and cache it for the next scrape."""
        self.store_snapshot = await events_store_usage(await self._jetstream(), self._events)
        return self.store_snapshot

    async def _tail(self, topic: str) -> tuple[int, OutboundFrame | None]:
        """(stream sequence, frame) of the subject's last message; `(0, None)` when it has none.

        The stream sequence is what `Nats-Expected-Last-Subject-Sequence` compares; the frame
        carries the producer sequence the next writer continues from.
        """
        raw = await self._last_message(topic)
        if raw is None:
            return 0, None
        try:
            return raw.seq or 0, decode(raw.data or b"")
        except ValidationError:
            return raw.seq or 0, None

    async def _last_message(self, topic: str) -> api.RawStreamMsg | None:
        try:
            js = await self._jetstream()
            return await js.get_last_msg(self._events.name, subject_for(topic))
        except APIError as exc:
            # A JetStream verdict: no message on this subject, or no stream yet — both a REAL
            # answer, "no frame". (`NotFoundError` is an `APIError`.)
            if exc.err_code == STREAM_NOT_FOUND_ERR_CODE:
                await self.ensure_stream(topic)
            return None
        except NatsError as exc:
            # Transport-level, during the connect or the read: a request timeout, a closed
            # connection, a reconnect in flight (review V-7). That is NOT "no frame" —
            # translating it to None would let the claim gate mistake an unreadable tail for
            # "no terminal frame" and execute a finished run a second time.
            raise QueueReadError(f"stream tail unreadable for {topic}: {exc!r}") from exc

    async def last_frame(self, topic: str) -> OutboundFrame | None:
        """The run's last published frame, or None when its subject holds none.

        WHY this exists: the worker's dedupe check (a terminal frame already on the subject
        means the run is over — redelivery, cancel-before-claim, or stale) and its post-exit
        check (did the child publish its own terminal frame?) both need to read the tail
        without subscribing. An empty subject or an unreadable frame reads as None — the
        conservative direction for both checks. A TRANSPORT failure raises `QueueReadError`.
        """
        _, frame = await self._tail(topic)
        return frame

    async def delete_stream(self, topic: str) -> None:
        """Reclaim a finished run: purge its subject, KEEPING the last (terminal) frame.

        WHY keep one frame: a run's terminal frame is the evidence that it is over — the
        worker's dedupe gate reads it on redelivery, and App admission reads it to free the
        caller's slot. Under the former layout the evidence was also "the stream is gone";
        a shared stream has no per-run object whose absence could say that, and an empty
        subject looks exactly like a run still in the queue. `max_age` removes the kept frame.
        """
        js = await self._jetstream()
        try:
            await js.purge_stream(self._events.name, subject=subject_for(topic), keep=1)
        except NotFoundError:
            return
        self.subject_purges += 1

    async def trim_retained(self, topic: str) -> None:
        """Cap a RETAINED run's subject: its newest `retained_max_msgs` frames, then its newest
        `retained_max_bytes` of payload — always keeping the terminal frame (OME-1462).

        FEATURE: failed-run post-mortem (OME-946) on a budget. Owner decision 2026-10-02: a
        per-subject cap, no separate stream. Uncapped, a retained subject held up to
        `max_msgs_per_subject` frames of up to `max_msg_size` each, and in a failure storm the
        `discard=OLD` eviction that followed hit OTHER runs' terminal frames — the ones the
        worker's dedupe gate and App admission read.

        WHY two purges: the broker applies a message cap in one call (`keep`) but has no byte
        form of it. The byte cap is computed from a scan of the survivors — at most
        `retained_max_msgs` reads, on the detached reclaim task — and applied as a purge below
        a stream sequence, filtered to this subject.

        INVARIANT: no other subject is touched (every purge carries the subject filter), and
        the subject's last frame always survives (`retained_cut`).
        """
        js = await self._jetstream()
        subject = subject_for(topic)
        cap = self._events
        try:
            await js.purge_stream(cap.name, subject=subject, keep=cap.retained_max_msgs)
        except NotFoundError:
            return
        sizes = await self._subject_sizes(js, subject, limit=cap.retained_max_msgs)
        cut = retained_cut(sizes, cap.retained_max_bytes)
        if cut is not None:
            await js.purge_stream(cap.name, subject=subject, seq=cut)
        logger.info(
            "capped the retained subject of %s: %d frame(s) scanned, cut below %s",
            topic,
            len(sizes),
            cut,
        )

    async def _subject_sizes(
        self, js: JetStreamContext, subject: str, *, limit: int
    ) -> list[tuple[int, int]]:
        """(stream sequence, payload bytes) of the subject's frames, oldest first, at most
        `limit` of them — the subject was just trimmed to that many, so the bound is a guard."""
        sizes: list[tuple[int, int]] = []
        seq = 1
        for _ in range(limit):
            try:
                msg = await js.get_msg(self._events.name, seq=seq, subject=subject, next=True)
            except NotFoundError:
                break
            msg_seq = msg.seq or seq
            sizes.append((msg_seq, len(msg.data or b"")))
            seq = msg_seq + 1
        return sizes

    async def close(self) -> None:
        if self._nc is not None:
            await self._nc.close()


def retained_cut(sizes: Sequence[tuple[int, int]], max_bytes: int) -> int | None:
    """The stream sequence a retained subject keeps from, or None when it already fits.

    `sizes` is the subject's (stream sequence, payload bytes), oldest first. Walking back from
    the tail, frames are kept while their total stays within `max_bytes`; the first frame that
    would overflow it is where the cut goes.

    INVARIANT: the last frame — the run's terminal frame — is kept even when it alone exceeds
    the budget; dedupe and admission read it, so it is the one frame a cap may never cost.
    """
    if not sizes:
        return None
    keep_from, total = sizes[-1][0], sizes[-1][1]
    for seq, size in reversed(sizes[:-1]):
        if total + size > max_bytes:
            break
        keep_from, total = seq, total + size
    return keep_from if keep_from != sizes[0][0] else None


class JetStreamConsumer(_JetStreamConnection, EventConsumer):
    """The App-side consumer: reads one run's subject of the shared stream and decodes frames
    back into `OutboundFrame`s, optionally resuming from a producer sequence."""

    async def subscribe(
        self, topic: str, from_sequence: int | None = None
    ) -> AsyncIterator[OutboundFrame]:
        validate_from_sequence(from_sequence)
        js = await self._jetstream()
        await self.ensure_stream(topic)
        sub = await js.subscribe(
            subject_for(topic), stream=self._events.name, config=_broadcast_consumer_config()
        )
        cursor = 1 if from_sequence is None else from_sequence
        first = True
        # WHY: the caller may abandon this generator mid-run (a re-attach cancels the WS pump, a
        # sync GET gives up at `sync_max_wait_s`). Without the unsubscribe the push consumer keeps
        # delivering into a queue nobody drains, for the life of the connection.
        try:
            async for msg in sub.messages:
                # INVARIANT (I-EV2): no sequence override. The frame carries the producer
                # sequence; the stream sequence has gaps inside a run in a shared stream.
                frame = decode(msg.data)
                sequence = _producer_sequence(frame)
                if (
                    first
                    and from_sequence is not None
                    and sequence > from_sequence
                    and isinstance(frame, TerminatedEvent)
                ):
                    # The subject holds only the terminal frame the reclaim kept (`keep=1`):
                    # the run is over and the frames the cursor points at are gone. The bridge
                    # turns this into `stream_reclaimed`, and the client stops reconnecting.
                    #
                    # WHY only then: a LIVE run can also lose its oldest frames — the per-run
                    # cap or a full store drops them (EV-D6, ans:Q11). That run is not over, so
                    # the resume continues at the earliest retained frame, like a stream that
                    # rolled over.
                    raise StreamNotFoundError(topic)
                first = False
                if sequence < cursor:
                    continue
                yield frame
        finally:
            await sub.unsubscribe()

    async def purge(self, topic: str) -> None:
        """Drop every retained frame of the run's subject. Idempotent."""
        js = await self._jetstream()
        try:
            await js.purge_stream(self._events.name, subject=subject_for(topic))
        except NotFoundError:
            return
        self.subject_purges += 1


class JetStreamPublisher(_JetStreamConnection, EventPublisher):
    """The publisher. Two kinds of writer use it, told apart by the frame:

    - A SEQUENCED frame comes from the url4 producer in the run child — the only writer while
      the run is live (I-EV3). It is PIPELINED: `publish` returns once the frame is written to
      the connection, and `flush` waits for the acknowledgements.
    - An UNSEQUENCED frame comes from a writer that is not the child — the supervisor's
      classification, the App's queued-cancel tombstone, the max-deliveries advisor. It goes
      through :meth:`publish_next`: a conditional append at the subject's last sequence + 1.

    WHY pipelined (OME-906): awaiting one acknowledgement per frame capped the drain at one
    broker round trip per frame, while the engine produced observation events at CPU speed. A
    cached DRACO burst therefore overflowed the Runner's event bridge — which cannot push back,
    because the engine's observer callback is synchronous — and a correct Evaluation failed.

    INVARIANT: exactly ONE task publishes sequenced frames per topic. `publish_async` writes to
    the connection inside the call, so a single caller hands the broker the frames in call order.
    """

    def __init__(
        self,
        nats_url: str,
        *,
        events: EventsStreamConfig | None = None,
        writer: str = "app",
    ) -> None:
        super().__init__(nats_url, events=events)
        # The metric label for this publisher's unsequenced (non-child) frames (C7).
        self._writer = writer
        # A dict used as an ORDERED set. Insertion order is publish order, and `_reap` keeps
        # the first failure — meaning the one on the earliest-published frame. A plain `set`
        # iterates by hash, which made "first" whichever future it happened to yield and only
        # showed up as a test that passed alone and failed in suite order.
        self._acks: dict[asyncio.Future[api.PubAck], None] = {}
        self._deferred_failure: BaseException | None = None
        # Per topic: the producer sequence already on the subject when this run started. See
        # `_rebase`. An entry lives from a run's first frame to its terminal frame.
        self._offsets: dict[str, int] = {}
        # Topics whose subject already ended when this publisher's run started (a queued-cancel
        # tombstone that won the race against the claim): their frames are dropped (I-EV4).
        self._ended: set[str] = set()
        self.publish_conflicts: Counter[str] = Counter()

    async def publish(self, topic: str, event: OutboundFrame) -> None:
        if event.sequence is None:
            # WHY route rather than refuse: the port numbers frames for a caller that does not
            # (`EventPublisher.publish`, and the url4 conformance contract publishes unsequenced
            # frames), and every non-child writer here builds its frame unsequenced. The url4
            # producer in the child ALWAYS sequences, so the pipelined path stays the child's.
            await self.publish_next(topic, event)
            return
        js = await self._jetstream()
        # Fail fast: a broker that started rejecting stops the run now, rather than after the
        # whole in-flight window drains.
        self._reap()
        self._raise_deferred()
        sequence = await self._rebase(topic, int(event.sequence))
        if sequence is None:
            return
        if sequence != int(event.sequence):
            event = event.model_copy(update={"sequence": str(sequence)})
        ack = await js.publish_async(
            subject_for(topic), encode(event), headers=_headers(topic, sequence)
        )
        self._acks[ack] = None
        if isinstance(event, TerminatedEvent):
            self._offsets.pop(topic, None)

    async def _rebase(self, topic: str, producer_sequence: int) -> int | None:
        """The subject sequence for a frame the url4 producer numbered `producer_sequence`, or
        None when the frame must be dropped because the subject already ended.

        WHY: the producer numbers every run from 1, but a topic can run twice — the queue
        redelivers a run whose worker died (`max_deliver=2`). The second child must continue
        the subject (k+1, k+2, …) instead of writing 1..n again: the client drops a sequence
        at or below its cursor as a duplicate, and `Nats-Msg-Id = <topic>:<seq>` would make the
        broker drop it too. So the FIRST frame this publisher stores for a run reads what the
        subject holds and offsets the run by it — at producer sequence 1, or later when that
        frame never got out (its tail read failed and the run's failed arm publishes next).

        A terminal tail at that point means the run was cancelled before it started (the App's
        tombstone won the race against the claim): nothing may follow it (I-EV4).

        The pending acks are drained first: a frame of an EARLIER run on this publisher may
        still be in flight, and the tail read must see it.
        """
        if producer_sequence == 1 or topic not in self._offsets:
            await self.flush()
            self._ended.discard(topic)
            _, last = await self._tail(topic)
            if isinstance(last, TerminatedEvent):
                self._ended.add(topic)
                logger.warning("%s already ended; dropping this run's frames", topic)
            self._offsets[topic] = _producer_sequence(last) - (producer_sequence - 1)
        if topic in self._ended:
            return None
        return producer_sequence + self._offsets[topic]

    async def publish_next(
        self, topic: str, event: OutboundFrame, *, writer: str | None = None
    ) -> bool:
        """Append `event` at the subject's last sequence + 1, unless the run already ended.

        Returns True when the frame was written. For a writer that is not the child (I-EV3):
        it reads the tail, writes `last + 1` under `Nats-Expected-Last-Subject-Sequence`, and on
        a conflict (another writer appended in between) reads again — max
        `MAX_CONDITIONAL_ATTEMPTS` times. It writes nothing after a terminal frame (I-EV4).

        After the last conflict it logs and returns False; the caller acks its queue message
        anyway, because the run already has, or will get, a terminal frame from another writer,
        or `max_age` expiry (C7).
        """
        label = writer or self._writer
        await self.ensure_stream(topic)
        unique_id = False
        for _ in range(MAX_CONDITIONAL_ATTEMPTS):
            stream_sequence, last = await self._tail(topic)
            if isinstance(last, TerminatedEvent):
                return False
            outcome = await self._append_once(
                topic, event, after=(stream_sequence, last), unique_id=unique_id
            )
            if outcome is _Append.WRITTEN:
                return True
            if outcome is _Append.CONFLICT:
                self.publish_conflicts[label] += 1
            else:
                unique_id = True
        logger.error(
            "gave up appending %s to %s after %d attempts",
            event.type,
            topic,
            MAX_CONDITIONAL_ATTEMPTS,
        )
        return False

    async def _append_once(
        self,
        topic: str,
        event: OutboundFrame,
        *,
        after: tuple[int, OutboundFrame | None],
        unique_id: bool,
    ) -> "_Append":
        """One conditional append of :meth:`publish_next`, right after the tail `after`
        (its stream sequence and its frame)."""
        stream_sequence, last = after
        sequence = _producer_sequence(last) + 1
        frame = event.model_copy(update={"sequence": str(sequence), "sequencetype": "Integer"})
        headers = _headers(topic, sequence)
        if unique_id:
            headers[Header.MSG_ID] = f"{topic}:{sequence}:{event.id}"
        headers[Header.EXPECTED_LAST_SUBJECT_SEQUENCE] = str(stream_sequence)
        js = await self._jetstream()
        try:
            ack = await js.publish(subject_for(topic), encode(frame), headers=headers)
        except APIError as exc:
            if exc.err_code != WRONG_LAST_SEQUENCE_ERR_CODE:
                raise
            return _Append.CONFLICT
        if not ack.duplicate:
            return _Append.WRITTEN
        # WHY a duplicate ack needs a second look: the broker checks `Nats-Msg-Id` BEFORE the
        # expected sequence, and answers a duplicate with a success on the wire while storing
        # nothing. Two causes, told apart by the tail:
        # - it moved: a late child frame took `last + 1` first, under the same id — a conflict
        #   like any other;
        # - it did not: nobody wrote, and the id matched a frame a purge removed inside the
        #   duplicate window (a purge rewinds the count). Retry under an id unique to this frame.
        moved, _ = await self._tail(topic)
        return _Append.CONFLICT if moved != stream_sequence else _Append.ID_REUSED

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


class _Append(Enum):
    """The outcome of one conditional append attempt."""

    WRITTEN = "written"
    CONFLICT = "conflict"
    ID_REUSED = "id_reused"


def _headers(topic: str, sequence: int) -> dict[str, str]:
    # `Nats-Msg-Id` makes a retried publish of the same frame a no-op inside the stream's
    # duplicate window (EV-D5).
    return {Header.MSG_ID: f"{topic}:{sequence}", URL4_SEQ_HEADER: str(sequence)}


__all__ = [
    "DeferredPublishError",
    "EventsStreamConfig",
    "EventsStreamConfigError",
    "JetStreamConsumer",
    "JetStreamPublisher",
    "QueueReadError",
    "ensure_events_stream",
    "events_store_usage",
    "purge_legacy_streams",
    "retained_cut",
]
