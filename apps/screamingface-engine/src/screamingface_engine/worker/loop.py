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
from collections.abc import Awaitable, Callable, Sequence
from typing import Protocol

from screamingface_engine.config import Settings
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
        pull_timeout_s: float = PULL_TIMEOUT_S,
        heartbeat_interval_s: float = HEARTBEAT_INTERVAL_S,
        deadline_margin_s: float = DEADLINE_MARGIN_S,
        kill_grace_s: float = KILL_GRACE_S,
    ) -> None:
        if slots < 1:
            raise ValueError(f"worker slots must be >= 1, got {slots}")
        self._queue = queue
        self._publisher = publisher
        self._slots = slots
        self._drain_grace_s = drain_grace_s
        self._pull_timeout_s = pull_timeout_s
        # The drain signal: set by SIGTERM/SIGINT (or by a test). The claim loop stops
        # pulling once it is set; the supervisors read it to classify a drain termination.
        self._draining = asyncio.Event()
        # Set by the drain phase AFTER `drain_grace_s` has elapsed, the moment it SIGTERMs
        # the remaining children. A supervisor waiting on a child that ignores SIGTERM
        # wakes on this and SIGKILLs instead of waiting out the hard wall.
        self._terminating = asyncio.Event()
        # The live children, shared with the supervisors: the drain phase reads it to know
        # when the pool has drained, and SIGTERMs whatever is left.
        self._children: set[_ChildProcess] = set()
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
            heartbeat_interval_s=heartbeat_interval_s,
            deadline_margin_s=deadline_margin_s,
            kill_grace_s=kill_grace_s,
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
                    # Wait for a slot — or the drain signal, so a full pool cannot
                    # deadlock the drain (the supervisors would never finish on their
                    # own, and the drain handler runs only after this loop exits).
                    drain_task = asyncio.create_task(self._draining.wait())
                    done, _ = await asyncio.wait(
                        {*self._active, drain_task}, return_when=asyncio.FIRST_COMPLETED
                    )
                    drain_task.cancel()
                    with contextlib.suppress(asyncio.CancelledError):
                        await drain_task
                    for task in done:
                        self._active.discard(task)
                continue
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
                await asyncio.sleep(_PULL_RETRY_S)
                continue
            for msg in msgs:
                task = tg.create_task(self._supervisor.supervise(msg))
                self._active.add(task)
                task.add_done_callback(self._active.discard)
        await self._drain()

    async def _drain(self) -> None:
        """The drain phase: let children finish naturally up to ``drain_grace_s``, then
        SIGTERM the rest so each publishes ``Terminated(stopped, worker_draining)``.

        The supervisors keep heartbeating throughout, so a draining worker never looks
        abandoned to the queue. After the grace, ``_terminating`` is set and the remaining
        children are SIGTERM'd; each supervisor classifies the death as a drain and
        publishes its named frame before acking.
        """
        loop = asyncio.get_running_loop()
        deadline = loop.time() + self._drain_grace_s

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
        # SIGTERM'd within one poll of registering, and `terminate()` on an
        # already-terminated child is harmless.
        self._terminating.set()
        while self._active:
            for proc in tuple(self._children):
                proc.terminate()
            await asyncio.sleep(_DRAIN_POLL_S)


def run_worker(settings: Settings | None = None) -> None:
    """The worker's composition root: build the queue, publisher, and worker from Settings.

    ``settings`` is injectable for tests; production callers leave it ``None`` and let
    ``Settings()`` read the environment.
    """
    from screamingface_engine.adapters.jetstream import JetStreamPublisher
    from screamingface_engine.runner_queue import RunQueue

    settings = settings if settings is not None else Settings()
    queue = RunQueue(
        settings.nats_url,
        stream=settings.run_queue_stream,
        ack_wait_s=settings.run_queue_ack_wait_s,
        max_deliver=settings.run_queue_max_deliver,
        max_ack_pending=settings.run_queue_max_ack_pending,
        duplicate_window_s=settings.run_queue_duplicate_window_s,
        max_age_s=settings.run_queue_max_age_s,
    )
    # The publisher's sweep must exclude the CONFIGURED queue stream, not a stale constant.
    publisher = JetStreamPublisher(settings.nats_url, run_queue_stream=settings.run_queue_stream)
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
        # INVARIANT: the heartbeat cadence is DERIVED from the configured `ack_wait`, not
        # left at the constant — a heartbeat slower than `ack_wait` redelivers a still-
        # running run to a second worker (double execution). `derived_heartbeat_interval_s`
        # keeps `heartbeat <= ack_wait / 3` for every legal configuration.
        heartbeat_interval_s=derived_heartbeat_interval_s(settings.run_queue_ack_wait_s),
    )
    asyncio.run(worker.run())


__all__ = ["PULL_TIMEOUT_S", "Worker", "run_worker"]
