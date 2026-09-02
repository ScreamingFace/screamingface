"""The queue-backed `JobRunner` (OME-1090): status is a pure function of the run's own
event stream plus capability validity, and cancellation is queue-aware.

OME-1086 replaces the Kubernetes Job with a durable queue + worker pool. This adapter is
the App's half of that replacement: `schedule()` publishes the run to the queue,
`stop()` writes a `Terminated(stopped)` tombstone for a queued run and reaches a running
one over a core NATS control subject, and `status()`/`exists()` read the run's event
stream instead of a Job.

WHY status is a pure function of the stream: the stream is the one record every replica
can read and the worker already writes — a terminal frame IS the run's outcome, a
`StartedEvent` without one means running, and neither with an unexpired capability means
the run is accepted but not yet started (queued). `JobStatus.scheduled` already means
exactly that, so the port needs no new member, and OME-1059's conflation (a Job that
exists but never starts) is retired structurally: a run that sat queued past its
capability lifetime reads `not_found`, not a phantom `scheduled`.

WHY cancellation is two paths: a queued run has no worker to ask, so the App writes the
tombstone itself and the worker later claims the message, sees the terminal frame, acks,
and never executes — no message deletion by sequence, and the App never learns the
message's sequence. A running run is owned by exactly one worker, so the App asks over
`url4.runctl.<topic>`; only the owner replies (and SIGTERMs its child, which ends in the
worker's own `Terminated(stopped)`), and no reply within a short timeout means "not
running here", falling back to the tombstone.

LAYERING: a shared leaf — it imports only the shared leaves (`runner_queue`, `subjects`,
`adapters.jetstream`), the abstract port, and the broker client, so both the control
plane and the worker half may import it.
"""

from __future__ import annotations

import asyncio
import logging
import math
import time
import uuid
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime
from typing import Any, Protocol

import nats
from nats.aio.client import Client
from nats.aio.msg import Msg
from nats.errors import NoRespondersError

from screamingface_engine.adapters.jetstream import QueueReadError
from screamingface_engine.ports import IdentityAwareJobRunner
from screamingface_engine.runner_queue import (
    DEFAULT_CALLER_INFLIGHT_CAP,
    DEFAULT_DEPTH_CEILING,
    DEFAULT_IO_CONCURRENCY,
    DEFAULT_STATE_CACHE_TTL_S,
    caller_key,
    encode_message,
)
from screamingface_engine.subjects import control_subject_for
from url4.streaming.interfaces import JobRunnerAtCapacity, JobStatus, job_name
from url4.streaming.protocol import (
    CachePolicy,
    ErrorInfo,
    OutboundFrame,
    TerminatedData,
    TerminatedEvent,
    source_for,
)

logger = logging.getLogger(__name__)

# The named reason on the App's queued-cancel tombstone. The worker's control-cancel frame
# uses the same code (`worker.supervisor.CANCELLED`), so a client sees one reason whether
# the cancel landed before or after the claim.
CANCELLED = "cancelled"
# How long `stop()` waits for a worker to answer the control request before reading "not
# running here". The worker's reply is a local NATS round trip; a second is far beyond it
# and far below the client's patience for a DELETE.
CONTROL_TIMEOUT_S = 1.0

# The sentinel `_read_tail` returns for an UNREADABLE stream tail — distinct from "no
# frame" and from "a terminal frame", because an unreadable broker answers neither
# question. Every caller treats it as UNKNOWN: no tombstone, no state change (review
# follow-up P2-10).
_UNREADABLE_TAIL = object()


class _Queue(Protocol):
    """The slice of ``RunQueue`` the queue runner uses."""

    async def publish(
        self, message: bytes, *, identity: Mapping[str, str] | None = None
    ) -> None: ...

    async def depth(self) -> int: ...

    async def oldest_age(self) -> float | None: ...


class _Publisher(Protocol):
    """The slice of ``JetStreamPublisher`` the queue runner uses."""

    async def last_frame(self, topic: str) -> OutboundFrame | None: ...

    async def stream_exists(self, topic: str) -> bool: ...

    async def ensure_stream(self, topic: str) -> None: ...

    async def publish(self, topic: str, event: OutboundFrame) -> None: ...

    async def flush(self) -> None: ...


class _ControlClient(Protocol):
    """The slice of a core NATS client the queue runner uses for the control request."""

    async def request(self, subject: str, payload: bytes, *, timeout: float) -> Any: ...


class ControlClient:
    """A lazy core-NATS client for the run-control request/reply channel.

    WHY lazy, like ``RunQueue``'s own connection: the factory constructs the queue runner
    synchronously at App build time, and nothing may dial the broker until the first
    request actually needs it. The lock and the re-check under it are the same
    single-connection story as ``_JetStreamConnection._jetstream``.
    """

    def __init__(self, nats_url: str) -> None:
        self._url = nats_url
        self._nc: Client | None = None
        self._lock = asyncio.Lock()

    async def _client(self) -> Client:
        nc = self._nc
        if nc is not None and not nc.is_closed:
            return nc
        async with self._lock:
            nc = self._nc
            if nc is not None and not nc.is_closed:
                return nc
            nc = await nats.connect(self._url)
            self._nc = nc
            return nc

    async def request(self, subject: str, payload: bytes = b"", *, timeout: float) -> Msg:
        nc = await self._client()
        return await nc.request(subject, payload, timeout=timeout)

    async def close(self) -> None:
        if self._nc is not None:
            await self._nc.close()


class QueueJobRunner(IdentityAwareJobRunner):
    """Implements `JobRunner` over the durable run queue and the run's own event stream.

    ``queue``, ``publisher`` and ``control`` are injected (the factory builds the real
    ``RunQueue``, ``JetStreamPublisher`` and ``ControlClient``; tests hand in fakes).
    ``clock`` and ``capability_lifetime_s`` are the capability-validity inputs: a run with
    no stream evidence is ``scheduled`` while its capability is unexpired and ``not_found``
    once it has expired.

    INVARIANT: the schedule-time record is in-memory, like ``InProcessJobRunner._tasks`` —
    this is not a new store. The terminal and running rows of the status table read the
    event stream and are correct across App replicas; the scheduled/not_found boundary
    uses the local record, and a replica that never scheduled the topic answers
    ``not_found``, which is the conservative direction for the reaper.
    """

    def __init__(
        self,
        *,
        queue: _Queue,
        publisher: _Publisher,
        control: _ControlClient,
        clock: Callable[[], datetime],
        capability_lifetime_s: float,
        control_timeout_s: float = CONTROL_TIMEOUT_S,
        io_concurrency: int = DEFAULT_IO_CONCURRENCY,
        extra_models: Callable[[], Sequence[str]] | None = None,
        # FEATURE (OME-1091): depth-based admission. The queue refuses a run when its depth is
        # at the ceiling — the substrate is saturated, and the REST edge maps the refusal to
        # 503 + a `Retry-After` derived from the drain estimate.
        depth_ceiling: int = DEFAULT_DEPTH_CEILING,
        # FEATURE (OME-1091): the per-caller in-flight cap — how many of one caller's runs may
        # be admitted at once, so one caller's 9-candidate evaluation cannot occupy every slot.
        caller_inflight_cap: int = DEFAULT_CALLER_INFLIGHT_CAP,
        # FEATURE (OME-1091): how long a depth reading stays fresh before the next refresh. The
        # queue itself caches its `stream_info` reading; this is the runner's own window, which
        # is what the reservation counter covers.
        state_cache_ttl_s: float = DEFAULT_STATE_CACHE_TTL_S,
    ) -> None:
        self._queue = queue
        self._publisher = publisher
        self._control = control
        self._clock = clock
        self._capability_lifetime_s = capability_lifetime_s
        self._control_timeout_s = control_timeout_s
        self._io_concurrency = io_concurrency
        # WHY a callable and not a snapshot (OME-880): the admitted-model overlay grows
        # while the app runs, and a model admitted a second ago must reach the very next
        # run — the same rule as `K8sJobRunner._extra_models`.
        self._extra_models = extra_models
        self._depth_ceiling = depth_ceiling
        self._caller_inflight_cap = caller_inflight_cap
        self._state_cache_ttl_s = state_cache_ttl_s
        # topic → when this replica accepted it. The capability-validity input for the
        # scheduled/not_found boundary; pruned on each schedule so it stays bounded by the
        # topics accepted within one capability lifetime.
        self._scheduled_at: dict[str, datetime] = {}
        # FEATURE (OME-1091): the OME-1065 cache-plus-reservation shape, carried over. The
        # counted resource changed (quota headroom → queue depth); the race did not. `_reserved`
        # counts runs admitted since the last refresh — it closes the read-modify-write race
        # when two `schedule()` calls land in one refresh window. The lock makes refresh +
        # check + reserve atomic.
        self._depth_snapshot: int | None = None
        self._oldest_age: float | None = None
        self._depth_cache_time: float | None = None
        self._reserved = 0
        self._admission_lock = asyncio.Lock()
        # The per-caller in-flight tracking: caller → {topic: admitted_at}, plus the reverse
        # index for the observed-terminal decrement. A run counts until the runner sees its
        # terminal frame (the reaper's polls, a re-schedule pre-check) or its capability
        # expires — the runner cannot observe a finish any other way.
        self._in_flight_by_caller: dict[str, dict[str, datetime]] = {}
        self._caller_of_topic: dict[str, str] = {}

    # --- the JobRunner port ----------------------------------------------------------------

    async def schedule(
        self,
        topic: str,
        url4: str,
        deadline_s: int,
        *,
        traceparent: str | None = None,
        credential: str | None = None,
        profile: str | None = None,
        identity: Mapping[str, str] | None = None,
        cache: CachePolicy | None = None,
    ) -> str:
        """Publish the run to the queue and return its job name.

        `credential` is accepted for port compatibility and DELIBERATELY DROPPED, exactly
        as `K8sJobRunner` drops it: the queue message carries the caller's verified
        identity, never a bearer token (see the k8s adapter's module INVARIANT).

        The broker deduplicates a retried submission of the same topic within
        `duplicate_window` (`Nats-Msg-Id` is the topic), which is the queue's
        `JobAlreadyExists` equivalent — the REST pre-check's 409 and the broker's dedupe
        collapse a race into one run.

        Raises:
            JobRunnerAtCapacity: the queue is at its depth ceiling, or the caller has too
                many runs in flight (503 + `Retry-After` at the REST edge).
        """
        await self._admit_or_raise(identity, topic)
        try:
            message = encode_message(
                topic,
                url4,
                deadline_s,
                traceparent=traceparent,
                profile=profile,
                identity=identity,
                cache=cache,
                io_concurrency=self._io_concurrency,
                extra_models=() if self._extra_models is None else self._extra_models(),
            )
            await self._queue.publish(message, identity=identity)
        except Exception:
            # The reservation was for a run that was not durably accepted — release it so the
            # next schedule in this window is not refused for a run that never queued.
            await self._release_reservation(topic)
            raise
        self._scheduled_at[topic] = self._clock()
        return job_name(topic)

    async def stop(self, topic: str) -> None:
        """Stop the run: reach a running one over the control subject, else tombstone a
        queued one. Idempotent — unknown and already-terminal topics are no-ops.

        WHY the tombstone comes BEFORE the final control re-ask, not after the first
        ask: nothing orders `stop()` against a worker's claim — the worker can claim the
        queued message in the window between the first ask's timeout and a tombstone
        written afterwards, and its claim-time gate reads the stream exactly once,
        before spawning. Writing the marker FIRST closes that window by construction:
        a claim that lands after it sees the frame at its gate and never executes. The
        re-ask then reaches a worker that claimed BEFORE the marker (it registers the
        topic before spawning, so it answers): the cancel is enacted, and the worker's
        own terminal publish is suppressed by `_publish_if_needed`'s stream re-read —
        the tombstone stays the run's single terminal frame on every interleave. The
        residual race needs a worker stalled longer than `control_timeout_s` between
        fetch and registration — pathological, and its claim-time gate still catches
        the tombstone once it proceeds. A stream that already ends in a terminal frame,
        or that does not exist at all (never attached, never scheduled), is untouched.

        WHY the tail is RE-READ between the ask and the tombstone (review follow-up):
        the first read is one control-timeout old by then, and nothing orders `stop()`
        against the run itself — a fast run can claim, execute, and publish
        `Terminated(succeeded)` entirely inside the ask's window. Writing the tombstone
        after that appended `stopped` AFTER the real outcome, and `status()` — a
        last-frame read on an append-only stream — reported a succeeded run as stopped,
        forever. The re-read sees the success frame and returns; the residual window
        (success landing between the re-read and the publish) is two broker round trips
        wide, and the confirmation ask below still reaches a live worker, whose own
        publish is suppressed by `_publish_if_needed`'s re-read.

        WHY an unreadable tail RAISES and does not no-op (review follow-ups P2-10 then
        V-2/V-3): an unreadable tail is UNKNOWN — neither terminal nor missing — so
        answering either way would stop a run that might be running or fail to stop one
        that needs stopping. The first P2-10 fix made this a SILENT no-op, which the
        reaper read as a successful reap (deadline popped, `reaped_total` incremented,
        "orphan run reaped" logged) for a run it never touched — the original bug with
        telemetry asserting the opposite — and which let `DELETE /` fall through to
        deleting the stream of a possibly-live run. The typed raise keeps "no state
        change" while making the unknown HONEST: the REST edge answers 503 (retryable),
        and the reaper's existing guard re-arms the deadline, so a retried stop once the
        broker is readable reaches the truth.
        """
        frame = await self._read_tail(topic)
        if frame is _UNREADABLE_TAIL:
            raise QueueReadError(f"stream tail unreadable for {topic}: run state unknown")
        if isinstance(frame, TerminatedEvent):
            return
        if await self._request_control(topic):
            return
        # The ask's window is where a run can finish — and where the tail can become
        # unreadable. Either way the marker is not written: a run that finished during the
        # ask keeps its real outcome, and an unknown tail is never trusted with a state
        # change.
        if await self._tombstone_queued_run(topic):
            # The confirmation pass: a worker that claimed between the first ask and the
            # tombstone answers THIS ask (registration precedes spawn), enacts the cancel,
            # and skips its own terminal frame — the tombstone is the one frame either way.
            await self._request_control(topic)

    async def _tombstone_queued_run(self, topic: str) -> bool:
        """Write the queued-cancel marker unless the run finished (or vanished, or went
        unreadable) in the ask window; True when a marker was written.

        The re-read is the overwrite guard: the first read is one control-timeout old by
        now, and a run that completed during the ask must keep its real outcome.
        """
        frame = await self._read_tail(topic)
        if frame is _UNREADABLE_TAIL or isinstance(frame, TerminatedEvent):
            return False
        if frame is None and not await self._publisher.stream_exists(topic):
            return False
        await self._publish_tombstone(topic)
        return True

    async def _read_tail(self, topic: str) -> TerminatedEvent | None | object:
        """The run's stream tail, or the `_UNREADABLE_TAIL` sentinel when the broker
        cannot be read.

        WHY a sentinel and not a raise (review follow-up P2-10): `JetStreamPublisher.
        last_frame` translates a transport-level read failure to `QueueReadError` so the
        caller can distinguish "no frame" from "could not read" — the two have opposite
        meanings for every terminal-frame decision. Every App-side caller (stop, status,
        the reaper through them) treats the sentinel as UNKNOWN and takes no action.
        """
        try:
            return await self._publisher.last_frame(topic)
        except QueueReadError:
            logger.warning("stream tail unreadable for %s; treating as unknown", topic)
            return _UNREADABLE_TAIL

    async def exists(self, topic: str) -> bool:
        """Whether a run is live: scheduled (queued) or running.

        A terminal run does not exist — the reaper's contract, which is what keeps an
        audience-loss stop from landing a second terminal frame on a finished run.
        """
        return await self.status(topic) in ("scheduled", "running")

    async def status(self, topic: str) -> JobStatus:
        """The run's status, derived from its event stream plus capability validity.

        | Evidence on the run's event stream | Status |
        | terminal frame present | its outcome |
        | StartedEvent, no terminal frame | running |
        | neither, capability unexpired | scheduled |
        | neither, capability expired | not_found |

        Any non-terminal frame counts as running evidence: the runner publishes
        `StartedEvent` first, so a log/span/cost frame means the run started, whatever it
        is doing now.

        WHY an unreadable tail RAISES (review follow-ups P2-10 then V-2/V-3): the first
        fix answered ``running`` — assumed alive — reasoning only about the reaper. But
        ``exists()`` is this same status, and ``POST /`` used it to answer 409 "a run
        already exists" for a BRAND-NEW topic on a transient blip: a definitive false
        claim clients do not retry. Unknown is not a state, for any consumer. The typed
        raise lets each caller answer honestly — the REST edge 503s (retryable, no state
        change), and the reaper's guard re-arms for the next sweep.
        """
        frame = await self._read_tail(topic)
        if isinstance(frame, TerminatedEvent):
            # The run is over — release the caller's in-flight slot so the cap reflects what
            # is actually running, not what once was. Guarded against a stale observation of a
            # PRIOR run of a re-scheduled topic (see `_forget_in_flight`).
            self._forget_in_flight(topic, frame)
            return frame.data.status
        if frame is _UNREADABLE_TAIL:
            raise QueueReadError(f"stream tail unreadable for {topic}: run state unknown")
        if frame is not None:
            return "running"
        return "scheduled" if self._capability_valid(topic) else "not_found"

    async def queue_depth(self) -> int:
        """How many runs are queued — the position notice's input (OME-1090)."""
        return await self._queue.depth()

    async def aclose(self) -> None:
        """Close the control connection. The queue and publisher own their own connections
        and are closed by their own owners; this runner created only the control client."""
        close = getattr(self._control, "close", None)
        if close is not None:
            await close()

    # --- the two cancel paths --------------------------------------------------------------

    async def _request_control(self, topic: str) -> bool:
        """Ask `url4.runctl.<topic>` whether a worker owns the run; True when one replied.

        A reply means the owner is SIGTERMing its child right now — the run's
        `Terminated(stopped)` is on its way from the worker, so the caller must not also
        write a tombstone. A timeout (or a broker that never delivers) reads as "not
        running here".
        """
        try:
            await self._control.request(
                control_subject_for(topic), b"", timeout=self._control_timeout_s
            )
            return True
        except (TimeoutError, NoRespondersError):
            # A timeout is "nobody replied in time". `NoRespondersError` is the SAME
            # answer delivered faster: the broker itself reports that NOTHING is
            # subscribed to `url4.runctl.*` — a pool scaled to zero, mid-rollout, or a
            # worker that is down. nats-py raises it whenever the server advertises
            # headers (`no_responders`), and it is NOT a `TimeoutError` subclass, so
            # leaving it uncaught 500s `DELETE /` instead of tombstoning the queued run.
            return False

    async def _publish_tombstone(self, topic: str) -> None:
        """Write `Terminated(stopped)` to the run's stream — the queued-cancel path.

        The worker later claims the run's message, sees this frame, acks, and never
        executes. The frame is a root frame (``source`` is the run's own), so a client
        attached to the run sees it as the run's outcome, exactly like the worker's own
        terminal frames.
        """
        await self._publisher.ensure_stream(topic)
        await self._publisher.publish(
            topic,
            TerminatedEvent(
                id=uuid.uuid4().hex,
                source=source_for(topic),
                subject=topic,
                time=self._clock(),
                data=TerminatedData(
                    status="stopped",
                    error=ErrorInfo(
                        code=CANCELLED,
                        message="the run was cancelled before it started",
                    ),
                ),
            ),
        )
        await self._publisher.flush()

    # --- depth-based admission (OME-1091) ---------------------------------------------------

    async def _admit_or_raise(self, identity: Mapping[str, str] | None, topic: str) -> None:
        """Admission gate: refresh the depth snapshot, refuse if the queue is at the ceiling
        or the caller is at its in-flight cap, else reserve.

        Raises:
            JobRunnerAtCapacity: the queue is at its depth ceiling, or the caller has too
                many runs in flight. The exception carries the drain estimate so the REST edge
                can derive `Retry-After`.
        """
        caller = caller_key(identity)
        async with self._admission_lock:
            self._prune()
            await self._refresh_if_stale()
            if (
                self._depth_snapshot is not None
                and self._depth_snapshot + self._reserved >= self._depth_ceiling
            ):
                raise JobRunnerAtCapacity(
                    self._depth_snapshot + self._reserved,
                    self._depth_ceiling,
                    retry_after_s=self._drain_estimate_s(),
                )
            count = len(self._in_flight_by_caller.get(caller, {}))
            if count >= self._caller_inflight_cap:
                raise JobRunnerAtCapacity(
                    count, self._caller_inflight_cap, retry_after_s=self._drain_estimate_s()
                )
            self._reserved += 1
            self._in_flight_by_caller.setdefault(caller, {})[topic] = self._clock()
            self._caller_of_topic[topic] = caller

    async def _release_reservation(self, topic: str) -> None:
        """Release a reservation whose run was not durably accepted (a publish failure)."""
        async with self._admission_lock:
            # WHY the floor: `_refresh_if_stale` RESETS the counter on every refresh, and
            # the refresh can land between this run's reserve and its release (a sibling
            # `schedule()` raced it). Decrementing from the reset baseline drove the counter
            # to -1, under-counting depth FOREVER after — one extra run past the ceiling on
            # every subsequent admission check. A release below zero is the refresh having
            # already accounted for this reservation; clamp, and the counter stays honest.
            self._reserved = max(0, self._reserved - 1)
            self._forget_in_flight(topic)

    async def _refresh_if_stale(self) -> None:
        """Re-read the queue's depth and oldest-message age when the cache is stale.

        The queue itself caches its `stream_info` reading (~2s), so this is one cheap read;
        the runner's own window is what the reservation counter covers. The depth now reflects
        everything older than the window, so the window's reservations are reset — the counter
        only covers the gap between refreshes.
        """
        now = time.monotonic()
        if (
            self._depth_cache_time is not None
            and now - self._depth_cache_time < self._state_cache_ttl_s
        ):
            return
        self._depth_snapshot = await self._queue.depth()
        self._oldest_age = await self._queue.oldest_age()
        self._depth_cache_time = now
        self._reserved = 0

    def _drain_estimate_s(self) -> int | None:
        """Seconds until the queue drains below the ceiling, from the pool's observed
        throughput — the `Retry-After` the REST edge forwards.

        The oldest message's wait implies the drain rate: in a FIFO queue at depth `d` whose
        oldest message has waited `age`, the pool drains at about `d / age` per second, so the
        queue reaches the ceiling in `(depth - ceiling) / rate` seconds. `None` when there is
        no basis (no depth, no age) — the caller falls back to the constant 1.
        """
        depth = self._depth_snapshot
        age = self._oldest_age
        if depth is None or age is None or depth <= 0 or age <= 0:
            return None
        rate = depth / age
        retry = (depth - self._depth_ceiling) / rate
        return max(1, math.ceil(retry))

    def _forget_in_flight(self, topic: str, frame: TerminatedEvent | None = None) -> None:
        """Drop a topic from the per-caller in-flight tracking: the run is over (a terminal
        frame was observed), was never admitted (a publish failure), or its capability expired.

        ``frame`` guards the observed-terminal path against a stale observation: a topic
        re-scheduled after its first run finished still shows the FIRST run's terminal frame,
        and forgetting on that sighting would release the SECOND run's slot. A frame older
        than a tracked admission is that stale sighting and is ignored — checked PER CALLER,
        because more than one caller can hold the topic (below).

        WHY every caller and not `_caller_of_topic[topic]`: admission OVERWRITES that
        mapping when a re-scheduled topic is admitted under a second identity, so the
        first caller's entry would never be reached again — `_prune` routes through here
        too — and that caller permanently loses one of its in-flight slots, surfacing
        eventually as spurious 503s for a caller whose runs have all finished.
        """
        for by_caller in self._in_flight_by_caller.values():
            admitted_at = by_caller.get(topic)
            if admitted_at is None:
                continue
            if frame is not None and frame.time is not None and frame.time < admitted_at:
                continue  # a stale sighting of the FIRST run — this admission is still live
            by_caller.pop(topic, None)
        if not any(topic in topics for topics in self._in_flight_by_caller.values()):
            self._caller_of_topic.pop(topic, None)
        # Drop callers left with no in-flight topics — the cleanup the single-caller path
        # always did, so the map stays bounded by callers with live runs.
        for caller in [c for c, topics in self._in_flight_by_caller.items() if not topics]:
            del self._in_flight_by_caller[caller]

    # --- capability validity ---------------------------------------------------------------

    def _capability_valid(self, topic: str) -> bool:
        """Whether the run's capability is still valid: accepted within
        `capability_lifetime_s`, on this replica's clock.

        A topic this replica never scheduled has no capability to speak of — `not_found`,
        the conservative answer for the reaper.
        """
        scheduled_at = self._scheduled_at.get(topic)
        if scheduled_at is None:
            return False
        return (self._clock() - scheduled_at).total_seconds() < self._capability_lifetime_s

    def _prune(self) -> None:
        """Drop schedule records whose capability has expired, so the dict stays bounded by
        the topics accepted within one capability lifetime — and release their in-flight
        slots, so the per-caller cap reflects only live runs."""
        now = self._clock()
        expired = [
            topic
            for topic, at in self._scheduled_at.items()
            if (now - at).total_seconds() >= self._capability_lifetime_s
        ]
        for topic in expired:
            del self._scheduled_at[topic]
            self._forget_in_flight(topic)


__all__ = [
    "CANCELLED",
    "CONTROL_TIMEOUT_S",
    "ControlClient",
    "QueueJobRunner",
]
