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
import uuid
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime
from typing import Any, Protocol

import nats
from nats.aio.client import Client
from nats.aio.msg import Msg
from nats.errors import NoRespondersError

from screamingface_engine.ports import IdentityAwareJobRunner
from screamingface_engine.runner_queue import DEFAULT_IO_CONCURRENCY, encode_message
from screamingface_engine.subjects import control_subject_for
from url4.streaming.interfaces import JobStatus, job_name
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


class _Queue(Protocol):
    """The slice of ``RunQueue`` the queue runner uses."""

    async def publish(self, message: bytes) -> None: ...

    async def depth(self) -> int: ...


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
        # topic → when this replica accepted it. The capability-validity input for the
        # scheduled/not_found boundary; pruned on each schedule so it stays bounded by the
        # topics accepted within one capability lifetime.
        self._scheduled_at: dict[str, datetime] = {}

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
        """
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
        await self._queue.publish(message)
        self._scheduled_at[topic] = self._clock()
        self._prune()
        return job_name(topic)

    async def stop(self, topic: str) -> None:
        """Stop the run: reach a running one over the control subject, else tombstone a
        queued one. Idempotent — unknown and already-terminal topics are no-ops.

        The control request goes out FIRST: a reply means a worker owns the run and is
        SIGTERMing its child, which ends in the worker's own `Terminated(stopped)` — the
        App must not also write a tombstone, or the run would end in two terminal frames.
        No reply within `control_timeout_s` means "not running here", and the tombstone
        covers the queued case. A stream that already ends in a terminal frame, or that
        does not exist at all (never attached, never scheduled), is left untouched.
        """
        if await self._request_control(topic):
            return
        frame = await self._publisher.last_frame(topic)
        if isinstance(frame, TerminatedEvent):
            return
        if frame is None and not await self._publisher.stream_exists(topic):
            return
        await self._publish_tombstone(topic)

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
        """
        frame = await self._publisher.last_frame(topic)
        if isinstance(frame, TerminatedEvent):
            return frame.data.status
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
        the topics accepted within one capability lifetime."""
        now = self._clock()
        expired = [
            topic
            for topic, at in self._scheduled_at.items()
            if (now - at).total_seconds() >= self._capability_lifetime_s
        ]
        for topic in expired:
            del self._scheduled_at[topic]


__all__ = [
    "CANCELLED",
    "CONTROL_TIMEOUT_S",
    "ControlClient",
    "QueueJobRunner",
]
