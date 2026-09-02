"""One run's supervision (OME-1089): claim → dedupe → spawn → heartbeat → classify → ack.

The worker's crash domain is ONE run: each claimed message is forked as a child process
running the existing ``screamingface-engine run`` entrypoint, and this module owns that
child's whole life — the dedupe check before it starts, the in-progress heartbeats that
keep a 16-hour run from looking abandoned, the hard wall that replaces
``activeDeadlineSeconds``, the drain path, and the named terminal frame that turns a
dead child into something a client can actually see.

LAYERING: this module imports the serving half and ``runner_queue``, and NOTHING from the
run half — the run is spawned as a child process, never imported (see the layering note
in :mod:`screamingface_engine.worker`).
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import sys
import uuid
from collections.abc import Awaitable, Callable, Mapping
from datetime import UTC, datetime
from typing import Any, Literal, Protocol

from screamingface_engine import job_env
from screamingface_engine.adapters.jetstream import QueueReadError
from screamingface_engine.logs import run_scope
from screamingface_engine.runner_queue import decode_message, topic_of_message
from screamingface_engine.subjects import ENQUEUED_AT_HEADER
from url4.streaming.protocol import (
    ErrorInfo,
    OutboundFrame,
    TerminatedData,
    TerminatedEvent,
    source_for,
)

logger = logging.getLogger(__name__)

TerminalStatus = Literal["succeeded", "failed", "stopped", "timed_out"]
"""The four terminal statuses a run can end in (``TerminatedData.status``)."""

# The named error codes the worker itself publishes. Each is a real, client-visible
# reason — the whole point of the worker's terminal frames is that a dead child reads as
# a named failure rather than silence.
QUEUE_EXPIRED = "queue_expired"
"""The run's capability expired while it sat in the queue; it was dropped unexecuted."""
WORKER_DRAINING = "worker_draining"
"""The worker is draining and stopped the run before it finished."""
CANCELLED = "cancelled"
"""The run was cancelled by its owner over the control subject (OME-1090).

The App's queued-cancel tombstone uses the same code (``adapters.queue_runner``), so a
client sees one reason whether the cancel landed before or after the claim.
"""
DEADLINE_EXCEEDED = "deadline_exceeded"
"""The child hung past the hard wall and was SIGTERM'd, then SIGKILL'd."""
OOM_KILLED = "oom_killed"
"""The child exited 137 — the OS killed it for exceeding its memory budget."""
KILLED = "killed"
"""The child was killed by a signal."""
CHILD_EXITED = "child_exited"
"""The child exited non-zero on its own."""
SPAWN_FAILED = "spawn_failed"
"""The child could not be started at all."""

# How long a child that ignores SIGTERM is given before the worker SIGKILLs it. The
# child is a Python process with no SIGTERM handler, so this is a backstop for a child
# stuck in uninterruptible I/O, not a normal path.
KILL_GRACE_S = 10.0
# The margin past `deadline_s + STREAM_GRACE_S` before the worker declares a child hung.
# The child enforces `deadline_s` in-process and then waits out `STREAM_GRACE_S` before
# reclaiming its stream, so a well-behaved child exits before the wall; the margin absorbs
# process teardown.
DEADLINE_MARGIN_S = 30.0
# How often the worker extends a claimed message's ack_wait while its child runs. Far
# below the queue's default ack_wait (60s), so a 16-hour run is never redelivered.
HEARTBEAT_INTERVAL_S = 20.0


def derived_heartbeat_interval_s(ack_wait_s: float) -> float:
    """The heartbeat cadence the worker runs for a queue with this `ack_wait`.

    WHY derived and not configured: the heartbeat exists to keep `in_progress` fresher than
    `ack_wait`, or JetStream assumes the delivery was lost and redelivers a STILL-RUNNING run
    to a second worker — the double execution the mechanism exists to prevent. The invariant
    `heartbeat <= ack_wait / 3` must hold for EVERY configuration; deriving it from the one
    knob that can violate it makes the invariant hold by construction instead of by an
    operator remembering a comment. The cap keeps the default cadence (20s at the default
    60s `ack_wait`); `Settings` floors `ack_wait` at 3s so the derived cadence never
    collapses below 1s and hammers the broker.
    """
    return min(HEARTBEAT_INTERVAL_S, ack_wait_s / 3.0)


class ClaimedMessage(Protocol):
    """The slice of ``nats.aio.msg.Msg`` the supervisor uses.

    A Protocol rather than the concrete class so the unit tests can hand in a fake without
    importing the broker client.
    """

    data: bytes
    metadata: Any

    async def ack(self) -> None: ...

    async def in_progress(self) -> None: ...


class _ChildProcess(Protocol):
    """The slice of ``asyncio.subprocess.Process`` the supervisor uses."""

    @property
    def returncode(self) -> int | None: ...

    stdout: Any
    stderr: Any

    async def wait(self) -> int: ...

    def terminate(self) -> None: ...

    def kill(self) -> None: ...


class _Publisher(Protocol):
    """The slice of ``JetStreamPublisher`` the supervisor uses."""

    async def last_frame(self, topic: str) -> OutboundFrame | None: ...

    async def ensure_stream(self, topic: str) -> None: ...

    async def publish(self, topic: str, event: OutboundFrame) -> None: ...

    async def flush(self) -> None: ...


class RunSupervisor:
    """Supervise one claimed run: dedupe, spawn, heartbeat, hard wall, classify, ack.

    One instance is shared by every supervisor task the worker spawns; the shared state
    it reads (the drain events, the live-children registry) is the worker's, passed in
    at construction. The supervisor itself is stateless between runs.
    """

    def __init__(
        self,
        *,
        publisher: _Publisher,
        spawn: Callable[..., Awaitable[_ChildProcess]],
        memory_budget_bytes: int,
        io_capacity: int,
        draining: asyncio.Event,
        terminating: asyncio.Event,
        children: set[_ChildProcess],
        children_by_topic: dict[str, _ChildProcess],
        cancelled: set[str],
        heartbeat_interval_s: float = HEARTBEAT_INTERVAL_S,
        deadline_margin_s: float = DEADLINE_MARGIN_S,
        kill_grace_s: float = KILL_GRACE_S,
    ) -> None:
        self._publisher = publisher
        self._spawn = spawn
        self._memory_budget_bytes = memory_budget_bytes
        self._io_capacity = io_capacity
        self._draining = draining
        self._terminating = terminating
        self._children = children
        # Topics with a run CURRENTLY executing on this worker. A redelivered duplicate
        # (an `ack_wait` shorter than a supervision gap, a broker hiccup) claims here while
        # the original is still alive; without this set the duplicate would fork a second
        # child for one topic and race its sibling to the terminal frame. Sync-guarded —
        # the check-and-add below has no await between it, so on the single event loop it is
        # atomic against every other claim.
        self._topics_in_flight: set[str] = set()
        # The topic → child index (OME-1090): the worker's control loop reads it to find
        # the owner of a run, and the supervisor maintains it alongside `_children`.
        self._children_by_topic = children_by_topic
        # Topics a control request has cancelled (OME-1090): the worker adds a topic before
        # SIGTERMing its child, and `_classify` reads it to name the death a cancel rather
        # than a kill.
        self._cancelled = cancelled
        self._deadline_margin_s = deadline_margin_s
        self._kill_grace_s = kill_grace_s

    async def supervise(self, msg: ClaimedMessage) -> None:
        """Claim one run and see it through to a terminal frame and an ack.

        INVARIANT: the ack is the LAST step, after the child has exited and its terminal
        frame is on the stream. Anything that fails before that leaves the message
        unacked, so the broker redelivers it (up to ``max_deliver``) instead of losing
        the run.
        """
        topic = topic_of_message(msg.data)
        with run_scope(topic):
            if topic in self._topics_in_flight:
                # A duplicate claim of a run THIS worker is already executing (redelivery
                # racing the in-flight original). The original owns the outcome — its
                # terminal frame and its ack — so the duplicate is acked away immediately:
                # spawning a second child for one topic would race it to the stream, and
                # leaving it unacked would redeliver it in a loop until the original ends.
                logger.warning(
                    "duplicate claim of %s acked away; the run is already executing here", topic
                )
                await msg.ack()
                return
            self._topics_in_flight.add(topic)
            try:
                await self._claim(msg, topic)
            finally:
                self._topics_in_flight.discard(topic)

    async def _claim(self, msg: ClaimedMessage, topic: str) -> None:
        """The claim gates and the run, after the duplicate guard has admitted the topic."""
        # One check for three cases: redelivery of a run that already finished, a
        # cancel that landed before the claim, and a stale message whose run is over.
        try:
            already_terminal = await self._terminal_frame_exists(topic)
        except QueueReadError:
            # WHY a local skip and not a crash: the stream tail was UNREADABLE — a transient
            # broker error, not an answer. The worker's supervisors share one TaskGroup, and
            # an error escaping here cancels every co-located run (each one SIGKILLed in its
            # cleanup) — one momentary NATS blip killing N healthy runs. Returning WITHOUT
            # the ack leaves the message for redelivery: the next attempt re-runs this check
            # and, once the broker is readable again, the dedupe answer is the real one.
            logger.warning("stream tail unreadable for %s; leaving the claim for redelivery", topic)
            return
        if already_terminal:
            await msg.ack()
            return
        if self._capability_expired(msg):
            await self._publish_terminal(
                topic, "failed", QUEUE_EXPIRED, "the run's capability expired while queued"
            )
            await msg.ack()
            return
        await self._run_child(msg, topic)

    async def _run_child(self, msg: ClaimedMessage, topic: str) -> None:
        """Fork the run as a child, supervise it to its terminal frame, then ack."""
        env = self._child_env(msg)
        try:
            proc = await self._spawn_child(env)
        except OSError as exc:
            # The run cannot start at all — a named failure beats silence, and the
            # message is acked so the run is not redelivered to fail the same way.
            await self._publish_terminal(topic, "failed", SPAWN_FAILED, str(exc))
            await msg.ack()
            return
        self._children.add(proc)
        self._children_by_topic[topic] = proc
        heartbeat = asyncio.create_task(self._heartbeat(msg, topic))
        output = asyncio.create_task(self._forward_output(proc, topic))
        try:
            outcome = await self._wait_for_child(proc, self._hard_wall_s(env))
            await self._publish_if_needed(topic, self._classify(outcome, proc.returncode, topic))
            await msg.ack()
        finally:
            heartbeat.cancel()
            output.cancel()
            # WHY gather and not sequential awaits under one `suppress`: a task that already
            # FAILED (not cancelled) re-raises its own exception on await, and `cancel()` is a
            # no-op on it — so `await heartbeat` would blow the finally block open and skip
            # every line below it (the child stays in `self._children`, a live child is never
            # killed). `return_exceptions=True` makes the gather itself unraisable; the
            # cleanup after it is therefore unconditional.
            for result in await asyncio.gather(heartbeat, output, return_exceptions=True):
                if isinstance(result, BaseException) and not isinstance(
                    result, asyncio.CancelledError
                ):
                    logger.warning("run supervision task failed during cleanup: %r", result)
            self._release_child(proc, topic)
            if proc.returncode is None:
                # A cancelled supervisor (a sibling failed and the TaskGroup unwound)
                # must not orphan its child.
                proc.kill()

    def _release_child(self, proc: _ChildProcess, topic: str) -> None:
        """Drop a finished child from every registry the worker shares.

        The cancel mark is per-run: a stale entry would misclassify a LATER run of the
        same topic whose child died from a signal that was not a cancel.
        """
        self._children.discard(proc)
        self._children_by_topic.pop(topic, None)
        self._cancelled.discard(topic)

    async def _publish_if_needed(
        self, topic: str, classification: tuple[TerminalStatus, str, str] | None
    ) -> None:
        """Publish the worker's named terminal frame unless the child already did.

        WHY the read is guarded (review follow-up P2-1): this runs AFTER the child
        exited, in the supervisor task that still has to ack. An unguarded read that
        raised ``QueueReadError`` escaped into the shared TaskGroup and cancelled every
        co-located supervisor — each sibling's cleanup SIGKILLs its live child, so one
        momentary broker blip at one child's exit killed N healthy runs (the same
        cascade as the claim-time gate, reached from the exit side). The run genuinely
        DID end, so on an unreadable tail the classified frame is published anyway —
        the named frame is the client's only account of a kill/OOM/deadline death, and
        the read-exists race (a child that published its own frame in the instant before
        the read failed) only ever risks one extra terminal frame, never a lost run.
        The ack always runs either way.
        """
        if classification is None:
            return
        try:
            already_terminal = await self._terminal_frame_exists(topic)
        except QueueReadError:
            logger.warning(
                "terminal-frame read unreadable for %s; publishing the classified frame",
                topic,
            )
            already_terminal = False
        if not already_terminal:
            try:
                await self._publish_terminal(topic, *classification)
            except Exception as exc:
                # WHY swallowed and not raised (review follow-up V-7): the run HAS ended —
                # this publish is the ACCOUNT of that ending, not the ending itself, and it
                # is a broker call made during the very blip that may have caused it. Left
                # unguarded its failure escaped into the shared TaskGroup, cancelling every
                # co-located supervisor (each sibling's cleanup SIGKILLs a live child — the
                # P2-1 cascade, reached from the publish side) and skipping the ack, so the
                # FINISHED run redelivered and was executed a second time. Losing the frame
                # is the bounded cost: the child's own frames are already on the stream, the
                # client's hold times out, and the operator sees this line. `CancelledError`
                # is a `BaseException` and still propagates.
                logger.error(
                    "terminal publish failed for %s; the run has ended and is acked "
                    "without its worker frame: %r",
                    topic,
                    exc,
                )

    # --- the claim-time checks ------------------------------------------------------------

    async def _terminal_frame_exists(self, topic: str) -> bool:
        """Whether the run's stream already ends in a terminal frame.

        True means the run is over — the message is redelivery, a cancel that landed
        before the claim, or a stale drop — so the worker acks and skips rather than
        running it a second time.
        """
        frame = await self._publisher.last_frame(topic)
        return isinstance(frame, TerminatedEvent)

    def _capability_expired(self, msg: ClaimedMessage) -> bool:
        """Whether the run's capability has expired while it sat in the queue.

        The run's deadline counts from when the message was PUBLISHED: a message claimed
        after ``deadline_s`` has elapsed has no time left to run, so executing it would
        only produce an immediate timeout. The worker drops it with a named
        ``queue_expired`` frame instead of executing it late. A message with no readable
        timestamp or deadline is treated as not expired — the safe direction.

        WHY the stamped header and not `msg.metadata.timestamp`: nats-py's metadata
        records the DELIVERY moment — when this worker PULLED the message — so a backlogged
        run reads as age ~0 exactly when it waited the longest, and the drop below never
        fired for the runs it exists to catch. The publisher stamps the enqueue wall-clock
        on the message (`subjects.ENQUEUED_AT_HEADER`); a message without the stamp (published
        before it existed) falls back to the delivery timestamp — the pre-stamp semantics,
        never worse.
        """
        published_at = self._published_at(msg)
        if published_at is None:
            return False
        raw_deadline = decode_message(msg.data).get(job_env.JOB_DEADLINE_S)
        if raw_deadline is None:
            return False
        return (datetime.now(UTC) - published_at).total_seconds() >= float(raw_deadline)

    def _published_at(self, msg: ClaimedMessage) -> datetime | None:
        """The message's enqueue moment: the stamped header first, delivery time as fallback."""
        headers = getattr(msg, "headers", None) or {}
        raw = headers.get(ENQUEUED_AT_HEADER) if hasattr(headers, "get") else None
        if raw:
            try:
                stamped = datetime.fromisoformat(raw)
            except ValueError:
                stamped = None
            if stamped is not None:
                return stamped if stamped.tzinfo is not None else stamped.replace(tzinfo=UTC)
        return getattr(getattr(msg, "metadata", None), "timestamp", None)

    # --- the child ------------------------------------------------------------------------

    def _child_env(self, msg: ClaimedMessage) -> dict[str, str]:
        """The child's environment: the worker's deploy-time env merged with the message's
        per-run env, plus the worker's own knobs.

        WHY merge rather than pass the message alone: the message carries only the per-run
        mapping; the deploy-time variables the run mode reads (``NATS_URL``,
        ``AIGATEWAY_BASE_URL``, ``TAVILY_API_KEY``, ``RUNNER_CONFIG``, the artifact store,
        ...) live in the worker Pod's env, and the child inherits exactly what this dict
        says. The message's per-run values win over the worker's ambient ones, and the
        worker's io budget is written last so it is the authority on how wide a run may
        fan out (the fair-share gate cannot span processes, so the budget travels by env).
        """
        env = dict(os.environ)
        env.update(decode_message(msg.data))
        env[job_env.IO_CONCURRENCY] = str(self._io_capacity)
        return env

    async def _spawn_child(self, env: Mapping[str, str]) -> _ChildProcess:
        """Fork the run entrypoint as a supervised child, under its own ``RLIMIT_AS``.

        WHY through the exec wrapper and not ``preexec_fn``: CPython documents
        ``preexec_fn`` as unsafe in the presence of threads, and this process runs an
        event loop plus whatever the NATS client starts. The wrapper is a separate tiny
        process that sets the address-space limit and execs ``screamingface-engine run``
        in place, so the run inherits the limit and the worker never touches the child's
        memory.
        """
        return await self._spawn(
            sys.executable,
            "-m",
            "screamingface_engine.worker.exec_wrapper",
            str(self._memory_budget_bytes),
            env=dict(env),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

    def _hard_wall_s(self, env: Mapping[str, str]) -> float | None:
        """The worker's hard wall for this run: ``deadline_s + STREAM_GRACE_S + margin``.

        The child enforces ``deadline_s`` in-process (publishing ``Terminated(timed_out)``)
        and then waits out ``STREAM_GRACE_S`` before reclaiming its stream, so a
        well-behaved child exits by ``deadline_s + STREAM_GRACE_S``. Past the wall the
        child is hung and the worker SIGTERMs, then SIGKILLs — this replaces
        ``activeDeadlineSeconds``. A message with no deadline (the codec always writes
        one) is unbounded, mirroring the child's own reading.
        """
        raw_deadline = env.get(job_env.JOB_DEADLINE_S)
        if raw_deadline is None:
            return None
        grace_s = float(env.get(job_env.STREAM_GRACE_S, job_env.DEFAULT_STREAM_GRACE_S))
        return float(raw_deadline) + grace_s + self._deadline_margin_s

    async def _wait_for_child(self, proc: _ChildProcess, hard_wall_s: float | None) -> str:
        """Wait for the child to exit, bounded by the hard wall; return how it ended.

        ``"finished"`` — the child exited on its own. ``"draining"`` — the drain handler
        fired (the supervisor terminated THIS child): it exited from the SIGTERM within the
        kill grace, or had to be SIGKILL'd. ``"deadline"`` — the hard wall expired and the
        worker killed it.
        """
        wait_task = asyncio.create_task(proc.wait())
        term_task = asyncio.create_task(self._terminating.wait())
        try:
            done, _ = await asyncio.wait(
                {wait_task, term_task},
                timeout=hard_wall_s,
                return_when=asyncio.FIRST_COMPLETED,
            )
        finally:
            term_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await term_task
        if term_task in done:
            # Checked BEFORE `wait_task in done`, deliberately: when BOTH completed — the
            # drain fired and the child exited in the same scheduling batch — the exit is
            # the drain's doing (or landed microseconds before its SIGTERM, which is
            # operationally the same event). Reading that race as a natural "finished"
            # would hand the classifier a drain kill as the child's own exit, and a child
            # that dies from the SIGTERM (rc -15) would be published as a failure.
            # The drain phase fired for THIS child — its phase-2 pass SIGTERMs every child
            # still registered, within one poll of it appearing (review follow-up), and the
            # child that ignores the SIGTERM gets the kill-grace backstop below.
            try:
                await asyncio.wait_for(wait_task, timeout=self._kill_grace_s)
            except TimeoutError:
                # WHY a FRESH `proc.wait()` and not `await wait_task`: `wait_for`
                # CANCELLED `wait_task` when it timed out, and awaiting a cancelled
                # task re-raises `CancelledError` — which would abort `supervise`
                # before the `Terminated(stopped, worker_draining)` frame and the ack,
                # and the run would redeliver and execute twice. Reap on a new wait,
                # the same shape `_kill_with_grace` uses.
                proc.kill()
            await proc.wait()
            return "draining"
        if wait_task in done:
            await wait_task
            return "finished"
        # The hard wall expired: SIGTERM, then SIGKILL.
        wait_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await wait_task
        await self._kill_with_grace(proc)
        return "deadline"

    async def _kill_with_grace(self, proc: _ChildProcess) -> None:
        """SIGTERM, then SIGKILL after ``kill_grace_s`` — the hard-wall backstop."""
        proc.terminate()
        try:
            await asyncio.wait_for(proc.wait(), timeout=self._kill_grace_s)
        except TimeoutError:
            proc.kill()
            await proc.wait()

    def _classify(
        self, outcome: str, returncode: int | None, topic: str
    ) -> tuple[TerminalStatus, str, str] | None:
        """The named terminal frame the worker must publish for a child that published none.

        Returns ``(status, code, message)``, or ``None`` when the worker must add
        nothing: a clean exit means the child's own teardown already put a terminal frame
        on the stream (or reclaimed it), so a second one would be a duplicate.
        """
        if outcome == "deadline":
            status, code, message = (
                "timed_out",
                DEADLINE_EXCEEDED,
                "the run exceeded its deadline and was killed",
            )
        elif outcome == "draining":
            # WHY `outcome` alone and not `or self._draining.is_set()`: the drain flag is
            # GLOBAL — set for the whole grace window, while unrelated children keep exiting
            # for their OWN reasons (an OOM, a crash) inside that window. Trusting the flag
            # relabeled every such exit as a benign drain-stop, masking real failures during
            # rolling deploys — precisely when someone is watching deploy health. The
            # drain-caused kills are exactly the ones `_wait_for_child` reports as
            # `"draining"` (it saw the drain fire for THIS child); that causality is the
            # classifier's only input.
            status, code, message = (
                "stopped",
                WORKER_DRAINING,
                "the worker is draining; the run was stopped",
            )
        elif topic in self._cancelled and returncode is not None and returncode < 0:
            # A control request SIGTERM'd this child (OME-1090): the death is a cancel, not
            # a kill. A child that exited 0 on its own before the request landed is NOT
            # classified here — its own terminal frame stands.
            status, code, message = (
                "stopped",
                CANCELLED,
                "the run was cancelled by its owner",
            )
        elif returncode == 0:
            return None
        elif returncode == 137:
            status, code, message = (
                "failed",
                OOM_KILLED,
                "the run was killed for exceeding its memory budget",
            )
        elif returncode is not None and returncode < 0:
            status, code, message = (
                "failed",
                KILLED,
                f"the run was killed by signal {-returncode}",
            )
        else:
            status, code, message = (
                "failed",
                CHILD_EXITED,
                f"the run exited with status {returncode}",
            )
        return status, code, message

    # --- the child's side channels --------------------------------------------------------

    async def _heartbeat(self, msg: ClaimedMessage, topic: str) -> None:
        """Extend the claimed message's ack_wait while its child runs.

        Without this, a run longer than the queue's ``ack_wait`` (60s) would be
        redelivered mid-run — a second worker would claim it, see the run's own frames on
        the stream, and ack it away, while the first worker's eventual ack would be a
        no-op. The heartbeat is cancelled the moment the child exits.
        """
        while True:
            await asyncio.sleep(self._heartbeat_interval_s)
            try:
                await msg.in_progress()
            except asyncio.CancelledError:
                raise  # the run is over — the supervisor cancelled this task
            except Exception:
                # A transient broker failure (a connection blip, a protocol error) must not
                # kill the heartbeat: the task dying here means the ack_wait runs out, the
                # message is redelivered mid-run, and a second worker double-runs it — the
                # exact outcome the heartbeat exists to prevent. Log and keep the loop; the
                # broker recovers or the run ends, and either way the next extension retries.
                logger.exception("heartbeat extension failed for %s; retrying next interval", topic)

    async def _forward_output(self, proc: _ChildProcess, topic: str) -> None:
        """Forward the child's stdout/stderr to the worker's log, topic-bound.

        The child's own logs are the operator's view of a run that is not the stream, and
        they must be attributable to the run. The worker adds no logging of its own about
        the expression — ``runner/main.py`` already logs its length rather than its
        content (OME-990), and the worker must not undo that.
        """

        async def _drain(stream: Any, level: int) -> None:
            if stream is None:
                return
            while True:
                line = await stream.readline()
                if not line:
                    return
                logger.log(
                    level, "run output topic=%s %s", topic, line.decode(errors="replace").rstrip()
                )

        await asyncio.gather(
            _drain(proc.stdout, logging.INFO),
            _drain(proc.stderr, logging.WARNING),
        )

    async def _publish_terminal(
        self, topic: str, status: TerminalStatus, code: str, message: str
    ) -> None:
        """Publish a named terminal frame to the run's stream.

        The frame is a root frame (``source`` is the run's own), so a client attached to
        the run sees it as the run's outcome. The broker assigns the stream sequence, and
        the App-side consumer stamps it onto the frame, so the client's replay cursor
        advances past it exactly as it would past the child's own terminal frame.
        """
        await self._publisher.ensure_stream(topic)
        await self._publisher.publish(
            topic,
            TerminatedEvent(
                id=uuid.uuid4().hex,
                source=source_for(topic),
                subject=topic,
                time=datetime.now(UTC),
                data=TerminatedData(
                    status=status,
                    error=ErrorInfo(code=code, message=message),
                ),
            ),
        )
        await self._publisher.flush()


__all__ = [
    "CANCELLED",
    "CHILD_EXITED",
    "DEADLINE_EXCEEDED",
    "DEADLINE_MARGIN_S",
    "HEARTBEAT_INTERVAL_S",
    "KILL_GRACE_S",
    "KILLED",
    "OOM_KILLED",
    "QUEUE_EXPIRED",
    "RunSupervisor",
    "SPAWN_FAILED",
    "WORKER_DRAINING",
]
