"""The worker's claim loop (OME-1089): a slot pool that pulls runs from the durable
queue and supervises each as a child process.

The loop is deliberately small: it owns the slot accounting (the worker's only shared
mutable state), the pull cadence, and the drain path. Everything about ONE run — the
dedupe check, the spawn, the heartbeats, the hard wall, the terminal frame — lives in
:class:`screamingface_engine.worker.supervisor.RunSupervisor`, so the loop reads as what
it is: claim up to the free slots, hand each message to a supervisor, and on SIGTERM
stop claiming and let the children drain.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import signal
import time
from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
from typing import TYPE_CHECKING, Protocol

import nats

from screamingface_engine.config import Settings

if (
    TYPE_CHECKING
):  # the adapters are imported lazily at runtime; only the annotation needs the names
    from screamingface_engine.adapters.jetstream import JetStreamPublisher
    from screamingface_engine.runner_queue import RunQueue
from screamingface_engine.runner_queue import topic_of_message
from screamingface_engine.subjects import CONTROL_SUBJECT_PREFIX
from screamingface_engine.worker.metrics import WorkerMetrics, build_worker_metrics
from screamingface_engine.worker.supervisor import (
    DEADLINE_MARGIN_S,
    HEARTBEAT_INTERVAL_S,
    KILL_GRACE_S,
    ClaimedMessage,
    RunSupervisor,
    _ChildProcess,
    _Publisher,
    derived_heartbeat_interval_s,
)

logger = logging.getLogger(__name__)

# How long a pull waits for the first message before the loop re-checks the drain signal.
# Short on purpose: the drain signal is only noticed between pulls, so a long timeout
# would delay a drain by that long.
PULL_TIMEOUT_S = 5.0
# How often the drain phase re-checks whether the in-flight children have finished.
_DRAIN_POLL_S = 0.05


# How often a pull that failed on a transient broker error is retried. Short: the claim
# loop is only blocked for the retry, and a broker that is down fails the NEXT connect too —
# this is a backoff, not the recovery mechanism.
_PULL_RETRY_S = 1.0


class _Queue(Protocol):
    """The slice of ``RunQueue`` the worker uses."""

    async def pull(self, batch: int, timeout_s: float) -> Sequence[ClaimedMessage]: ...


class _ControlMessage(Protocol):
    """The slice of ``nats.aio.msg.Msg`` the control loop uses."""

    subject: str
    data: bytes

    async def respond(self, data: bytes) -> None: ...


class _ControlSubscription(Protocol):
    """The slice of ``nats.aio.subscription.Subscription`` the control loop uses."""

    @property
    def messages(self) -> AsyncIterator[_ControlMessage]: ...


class _Control(Protocol):
    """The slice of a core NATS client the control loop uses."""

    async def subscribe(self, subject: str) -> _ControlSubscription: ...


class Worker:
    """The slot pool: claim runs from the queue, supervise each as a child process.

    ``queue`` and ``publisher`` are injected (the composition root builds the real
    ``RunQueue`` and ``JetStreamPublisher``; tests hand in fakes). ``spawn`` defaults to
    ``asyncio.create_subprocess_exec`` and is injectable so tests can hand in a fake
    process.
    """

    def __init__(
        self,
        *,
        queue: _Queue,
        publisher: _Publisher,
        slots: int,
        drain_grace_s: float,
        io_capacity: int,
        memory_budget_bytes: int,
        spawn: Callable[..., Awaitable[_ChildProcess]] | None = None,
        control: _Control | None = None,
        pull_timeout_s: float = PULL_TIMEOUT_S,
        heartbeat_interval_s: float = HEARTBEAT_INTERVAL_S,
        deadline_margin_s: float = DEADLINE_MARGIN_S,
        kill_grace_s: float = KILL_GRACE_S,
        metrics: WorkerMetrics | None = None,
    ) -> None:
        if slots < 1:
            raise ValueError(f"worker slots must be >= 1, got {slots}")
        self._queue = queue
        self._publisher = publisher
        self._slots = slots
        self._drain_grace_s = drain_grace_s
        self._pull_timeout_s = pull_timeout_s
        # The worker's Prometheus metrics (OME-1092). `None` (tests, or a worker built
        # without the composition root) builds a fresh instance on its own registry, so
        # nothing here ever touches a shared registry.
        self._metrics = metrics if metrics is not None else build_worker_metrics()
        self._metrics.slots_total.set(slots)
        # The run-control channel (OME-1090): a core NATS client subscribed to
        # `url4.runctl.*`. `None` disables the control loop (tests that do not exercise
        # cancellation).
        self._control = control
        # The drain signal: set by SIGTERM/SIGINT (or by a test). The claim loop stops
        # pulling once it is set; the supervisors read it to classify a drain termination.
        self._draining = asyncio.Event()
        # Set by the drain phase AFTER `drain_grace_s` has elapsed, the moment it SIGTERMs
        # the remaining children. A supervisor waiting on a child that ignores SIGTERM
        # wakes on this and SIGKILLs instead of waiting out the hard wall.
        self._terminating = asyncio.Event()
        # Set when the drain phase has COMPLETED (the grace window elapsed, the remaining
        # children were SIGTERM'd, and the pool is empty). The control loop exits on THIS
        # rather than on `_draining` (review follow-up P2-12): with the signal only, every
        # `url4.runctl.*` request in the drain window went unanswered — see `_control_loop`.
        self._drained = asyncio.Event()
        # The live children, shared with the supervisors: the drain phase reads it to know
        # when the pool has drained, and SIGTERMs whatever is left.
        self._children: set[_ChildProcess] = set()
        # The topic → child index (OME-1090): the control loop reads it to find the owner
        # of a run; the supervisors maintain it alongside `_children`.
        self._children_by_topic: dict[str, _ChildProcess] = {}
        # Topics a control request has cancelled (OME-1090): the control loop adds a topic
        # before SIGTERMing its child; the supervisors read it to classify the death.
        self._cancelled: set[str] = set()
        # Runs this worker has CLAIMED but not yet spawned (OME-1090): the control loop
        # answers from here while a run is starting, so a cancel that lands in the spawn
        # window gets a reply (and the App writes no tombstone) instead of being ignored
        # until the child has run to completion — two terminal frames. The claim loop
        # registers a topic BEFORE creating the supervisor task (closing the scheduling
        # gap), and the supervisor clears it once the child registers (or fails to).
        self._starting: set[str] = set()
        # The in-flight supervisor tasks — the slot accounting. asyncio is single-threaded,
        # so no lock is needed; the fetch batch is computed from the free slots below.
        self._active: set[asyncio.Task[None]] = set()
        self._supervisor = RunSupervisor(
            publisher=publisher,
            spawn=spawn if spawn is not None else asyncio.create_subprocess_exec,
            memory_budget_bytes=memory_budget_bytes,
            io_capacity=io_capacity,
            draining=self._draining,
            terminating=self._terminating,
            children=self._children,
            children_by_topic=self._children_by_topic,
            cancelled=self._cancelled,
            starting=self._starting,
            heartbeat_interval_s=heartbeat_interval_s,
            deadline_margin_s=deadline_margin_s,
            kill_grace_s=kill_grace_s,
            metrics=self._metrics,
        )

    async def run(self) -> None:
        """Run the worker until the drain signal, then drain and exit.

        The supervisors live in a ``TaskGroup`` so a failure cancels siblings
        deterministically: one run's supervision blowing up (a broker error, a bug) stops
        the pool rather than leaving the other runs unsupervised.
        """
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, self._draining.set)
        try:
            async with asyncio.TaskGroup() as tg:
                tg.create_task(self._claim_loop(tg))
                if self._control is not None:
                    tg.create_task(self._control_loop(tg))
        finally:
            for sig in (signal.SIGTERM, signal.SIGINT):
                loop.remove_signal_handler(sig)

    async def _claim_loop(self, tg: asyncio.TaskGroup) -> None:
        """Claim runs from the queue and supervise them, until the drain signal.

        INVARIANT: the fetch batch is computed from FREE slots — ``worker_slots`` minus
        the supervisors in flight — so the worker never holds more unacked messages than
        it can run, and never starves sibling pull consumers by fetching more than the
        pool can hold. When every slot is busy the loop waits for a supervisor to finish
        before pulling again.
        """
        while not self._draining.is_set():
            free = self._slots - len(self._active)
            if free <= 0:
                if self._active:
                    await self._await_free_slot()
                continue
            pull_started = time.monotonic()
            # The loop-liveness signal: stamped on every pull ATTEMPT, before the await —
            # a loop wedged inside a pull (or never reaching one) stops advancing this
            # gauge while the scrape thread stays healthy. See the gauge's docstring for
            # the alert shape.
            self._metrics.last_claim_attempt.set(time.time())
            try:
                msgs = await self._queue.pull(free, timeout_s=self._pull_timeout_s)
            except Exception as exc:
                # WHY a local catch and not a crash (review follow-up N-3): `pull` wraps
                # the broker calls — the fetch itself and the `ensure_stream` it guards —
                # and a transient broker error escaping here would land in the shared
                # TaskGroup and cancel every co-located supervisor, SIGKILLing N healthy
                # children: the same cascade as the supervisor's own guarded reads,
                # reached from the claim side. Log and retry; if the loop is genuinely
                # wedged, the claim-liveness gauge stops advancing and the operator's
                # alert fires. `CancelledError` is a `BaseException` and passes through,
                # so a shutdown still lands.
                logger.warning("queue pull failed with %r; retrying in %.1fs", exc, _PULL_RETRY_S)
                # V-5: the failure counter is the alert lever the liveness stamp cannot
                # be — the stamp advances on every ATTEMPT, so a pull that keeps failing
                # (or silently returning nothing) still looks alive. A rising counter is
                # the operator's signal that the worker's broker path needs attention.
                self._metrics.pull_failures_total.inc()
                await asyncio.sleep(_PULL_RETRY_S)
                continue
            self._metrics.claim_latency_s.observe(time.monotonic() - pull_started)
            for msg in msgs:
                # Register the run as STARTING before the supervisor task exists: a cancel
                # that arrives while the claim loop is between pulls must find the topic,
                # or the control loop ignores it and the App tombstones a run this worker
                # is about to own (two terminal frames — the race OME-1090's fix closes).
                self._starting.add(topic_of_message(msg.data))
                task = tg.create_task(self._supervisor.supervise(msg))
                self._active.add(task)
                task.add_done_callback(self._on_task_done)
            # WHY the busy-slot gauge is set AFTER the add loop, not before (review
            # follow-up): the old order reported the pre-claim count in the window between
            # the pull returning and the tasks registering — a scrape landing there during a
            # bursty claim under-reported utilization by the just-claimed batch, biasing
            # capacity dashboards LOW at the moments of highest throughput.
            self._metrics.slots_busy.set(len(self._active))
        await self._drain()

    async def _await_free_slot(self) -> None:
        """Block until a supervisor finishes or the drain signal fires.

        The drain signal is in the race so a FULL pool cannot deadlock the drain: the
        supervisors would never finish on their own, and the drain handler runs only
        after this loop exits. Any tasks that completed alongside the winner are
        reaped here — `_on_task_done` will also fire for them, and `discard` is
        idempotent."""
        drain_task = asyncio.create_task(self._draining.wait())
        try:
            done, _ = await asyncio.wait(
                {*self._active, drain_task}, return_when=asyncio.FIRST_COMPLETED
            )
        finally:
            drain_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await drain_task
        for task in done:
            self._active.discard(task)

    def _on_task_done(self, task: asyncio.Task[None]) -> None:
        """Drop a finished supervisor task and refresh the busy-slot gauge."""
        self._active.discard(task)
        self._metrics.slots_busy.set(len(self._active))

    async def _control_loop(self, tg: asyncio.TaskGroup) -> None:
        """Serve run-control requests: only the owner of a run replies, and it SIGTERMs
        its child (OME-1090).

        Every worker subscribes to ``url4.runctl.*``; a request for a topic this worker
        does not own is ignored — no reply — so the App's short timeout reads "not
        running here" and falls back to the tombstone. A request for an owned topic is
        answered (the App then writes nothing) and the child is SIGTERM'd; the supervisor
        classifies the death as a cancel and publishes ``Terminated(stopped)``.

        INVARIANT: the loop EXITS when the drain phase has COMPLETED — not the moment the
        drain signal arrives (review follow-up P2-12). The subscription's iterator only
        ends when the CONNECTION closes, and `run_worker` closes the control connection
        only after `Worker.run()` returns — so a loop that merely awaits the next message
        keeps the TaskGroup (and the rolling deploy behind it) alive past the drain, which
        is the deploy-interrupts-runs regression the drain exists to prevent. But exiting
        on the SIGNAL used to leave every cancel in the drain window unanswered:
        `_children_by_topic` stays populated while the drained runs drain, so up to
        `drain_grace_s` of `url4.runctl.*` requests timed out, the App tombstoned runs
        that were still executing and still billing, and the caller was told the run
        stopped when it had not. Serving until `_drained` (set when the drain phase is
        done and the pool is empty) keeps cancels answerable through the window, and the
        abandon-on-timeout shape below still ends the TaskGroup.
        """
        control = self._control
        if control is None:
            return
        sub = await control.subscribe(f"{CONTROL_SUBJECT_PREFIX}.*")
        messages = sub.messages.__aiter__()
        while True:
            msg_task = asyncio.ensure_future(messages.__anext__())
            drained_task = asyncio.create_task(self._drained.wait())
            try:
                done, _ = await asyncio.wait(
                    {msg_task, drained_task}, return_when=asyncio.FIRST_COMPLETED
                )
            finally:
                drained_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await drained_task
            if msg_task not in done:
                # The drain phase finished: abandon the pending fetch and exit.
                msg_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await msg_task
                return
            await self._handle_control(msg_task.result())

    async def _handle_control(self, msg: _ControlMessage) -> None:
        """Answer one control request: SIGTERM the child that owns the topic, or reply to a
        starting run's cancellation. A request for a topic this worker does not own gets no
        reply — the App's short timeout reads "not running here" and falls back to the
        tombstone.
        """
        topic = msg.subject.removeprefix(f"{CONTROL_SUBJECT_PREFIX}.")
        proc = self._children_by_topic.get(topic)
        if proc is None:
            if topic in self._starting:
                # A run this worker is STARTING: the child has not registered yet, but
                # the App must not tombstone a run this worker is about to own — that
                # is how a run ends with two terminal frames. Mark the topic cancelled
                # and reply; the supervisor enacts the cancel the moment the child
                # registers.
                #
                # WHY the mark BEFORE the reply: `respond` is real network I/O — a
                # suspension point. In the other order, the spawn could complete and
                # the supervisor's registration check (`if topic in self._cancelled`)
                # could run while `respond` was in flight, find the mark absent, and
                # let the child run to completion — while the App, already holding
                # "ok", wrote no tombstone: the caller believes the run was stopped
                # and it never was. By the time the ack is SENT, the cancellation is
                # recorded, so the registration check sees it on every schedule order.
                self._cancelled.add(topic)
                await msg.respond(b"ok")
            return
        self._cancelled.add(topic)
        proc.terminate()
        await msg.respond(b"ok")

    async def _drain(self) -> None:
        """The drain phase: let children finish naturally up to ``drain_grace_s``, then
        SIGTERM the rest so each publishes ``Terminated(stopped, worker_draining)``.

        The supervisors keep heartbeating throughout, so a draining worker never looks
        abandoned to the queue. After the grace, ``_terminating`` is set and the remaining
        children are SIGTERM'd; each supervisor classifies the death as a drain and
        publishes its named frame before acking. `_drained` is set when the phase is done
        — the control loop's exit condition (see `_control_loop`).
        """
        loop = asyncio.get_running_loop()
        deadline = loop.time() + self._drain_grace_s

        self._metrics.drains.inc()
        # Phase 1 — the grace window: let in-flight runs finish naturally. WHY the ACTIVE
        # supervisor tasks and not the CHILDREN (review follow-up P2-6): a task is
        # registered the moment its run is claimed, while its child only registers once
        # the spawn completes — a run whose spawn was still in flight when the signal
        # landed used to find `_children` EMPTY and consume ZERO grace: `_terminating`
        # was set immediately and the run was killed `kill_grace` after spawn with no
        # chance to finish on its own. Waiting on the tasks counts every claimed run.
        while self._active and loop.time() < deadline:
            await asyncio.sleep(_DRAIN_POLL_S)

        # Phase 2 — the deadline: flip `_terminating` (each remaining supervisor's kill
        # path engages) and terminate children as they appear. The old one-shot snapshot
        # pass over `_children` let a child that registered AFTER the pass reach its
        # supervisor's kill path having NEVER received a SIGTERM — hard-killed
        # `kill_grace` after spawn with no chance to publish its frames (review
        # follow-up N-2). Re-polling until the pool is empty closes that: any child is
        # SIGTERM'd within one poll of registering.
        self._terminating.set()
        while self._active:
            for proc in tuple(self._children):
                # WHY the guard (review follow-up V-1): `_release_child` removes a finished
                # child only AFTER its publish and ack round trips, so an EXITED child is
                # routinely still here when this pass lands — and `terminate()` on one is
                # NOT harmless. A real transport raises `ProcessLookupError` (an `OSError`)
                # from `_check_proc` once the process is reaped; unsuppressed it escaped
                # into the shared TaskGroup and SIGKILLed every remaining draining child —
                # the P2-1 cascade, reintroduced by the drain, on every drain. A child
                # whose exit was observed is skipped outright; one reaped in the window
                # before the watcher fires (returncode still None) is suppressed.
                if proc.returncode is not None:
                    continue
                with contextlib.suppress(ProcessLookupError):
                    proc.terminate()
            await asyncio.sleep(_DRAIN_POLL_S)
        # The drain phase is complete (the pool is empty) — the control loop's exit
        # signal (see `_control_loop` and P2-12).
        self._drained.set()


def worker_composition(settings: Settings) -> tuple[RunQueue, JetStreamPublisher]:
    """The worker's queue and publisher, from Settings.

    Extracted from `run_worker` (review follow-up V-9) so the stream-wiring test can hold
    the WORKER's composition root to the same Settings the App's roots answer to — the two
    sides agreeing on the stream name is the whole P2-2 fix, and a test that only inspects
    one root cannot see the other drifting.
    """
    from screamingface_engine.adapters.jetstream import JetStreamPublisher
    from screamingface_engine.runner_queue import RunQueue

    queue = RunQueue(
        settings.nats_url,
        stream=settings.run_queue_stream,
        subject_prefix=settings.run_queue_subject_prefix,
        ack_wait_s=settings.run_queue_ack_wait_s,
        max_deliver=settings.run_queue_max_deliver,
        max_ack_pending=settings.run_queue_max_ack_pending,
        duplicate_window_s=settings.run_queue_duplicate_window_s,
        max_age_s=settings.run_queue_max_age_s,
        bucket_count=settings.run_queue_bucket_count,
        # INVARIANT: the App and the worker declare the SAME singleton stream, and
        # `ensure_stream` refuses a declaration whose properties diverge from an existing
        # one — so both halves must read this from the same setting. Omitting it here left
        # the worker on the code default regardless of configuration, which on a clustered
        # broker is a startup failure for whichever half declares second.
        replicas=settings.run_queue_replicas,
    )
    # The publisher's sweep must exclude the CONFIGURED queue stream, not a stale constant.
    publisher = JetStreamPublisher(settings.nats_url, run_queue_stream=settings.run_queue_stream)
    return queue, publisher


def run_worker(settings: Settings | None = None) -> None:
    """The worker's composition root: build the queue, publisher, control channel, and
    worker from Settings.

    ``settings`` is injectable for tests; production callers leave it ``None`` and let
    ``Settings()`` read the environment.
    """
    settings = settings if settings is not None else Settings()
    queue, publisher = worker_composition(settings)
    metrics = build_worker_metrics()
    metrics.started.inc()
    if settings.worker_metrics_port > 0:
        # The worker's own scrape endpoint (OME-1092): the chart exposes this port on the
        # runner pool Deployment. The stdlib-backed server is the prometheus_client
        # convention for a process that serves nothing else.
        from prometheus_client import start_http_server

        start_http_server(settings.worker_metrics_port, registry=metrics.registry)

    async def _main() -> None:
        # The control channel is a core NATS client of its own, like the queue's and the
        # publisher's: each component owns its connection, and the worker closes the one it
        # created.
        nc = await nats.connect(settings.nats_url)
        try:
            worker = Worker(
                queue=queue,
                publisher=publisher,
                # INVARIANT: the worker's slot count is `run_queue_worker_slots` — the same value
                # the queue settings derive `max_ack_pending` from — so the worker's concurrency
                # and the queue's ack-pending bound cannot disagree.
                slots=settings.run_queue_worker_slots,
                drain_grace_s=settings.worker_drain_grace_s,
                io_capacity=settings.worker_io_capacity,
                memory_budget_bytes=settings.worker_memory_budget_bytes,
                control=nc,
                # INVARIANT: the heartbeat cadence is DERIVED from the configured `ack_wait`, not
                # left at the constant — a heartbeat slower than `ack_wait` redelivers a still-
                # running run to a second worker (double execution). `derived_heartbeat_interval_s`
                # keeps `heartbeat <= ack_wait / 3` for every legal configuration.
                heartbeat_interval_s=derived_heartbeat_interval_s(settings.run_queue_ack_wait_s),
                metrics=metrics,
            )
            await worker.run()
        finally:
            await nc.close()

    asyncio.run(_main())


__all__ = ["PULL_TIMEOUT_S", "Worker", "run_worker"]
