"""The Engine's driver: it starts each Run's Candidates, and stops a Run when it should stop.

FEATURE: a detached Run (OME-1837), E5 P2 spec R1 to R4 and R7 to R11. The Client sends a Run once
with every Candidate's start; from then on the Engine starts them, at most `inflight` at a time,
whether or not anyone is following, and stops the Run on a cancel, at a detached Run's deadline, or
when nobody has followed an attached Run for `orphan_grace_s`.

INVARIANT (R4): one driver per Run. Each Run is driven under its lease in the registry, taken and
renewed by a conditional write, so of two App processes only one starts its Candidates, and a
driver that lost its lease stops.

INVARIANT (D6): a Candidate keeps one topic, and one trace, for its whole life. A start whose fate
is unknown is sent again under the same topic; the queue, or a worker's claim, drops a repeat.

LAYERING: control plane (`runs`).
"""

from __future__ import annotations

import asyncio
import contextlib
import enum
import logging
import secrets
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Protocol, cast

from screamingface_engine.adapters.jetstream import QueueReadError
from screamingface_engine.artifacts.run_results import result_prefix
from screamingface_engine.auth.token import new_topic
from screamingface_engine.candidate_outcomes import (
    OUTCOME_STATUSES,
    CandidateOutcome,
    OutcomeStatus,
    storable_error_code,
)
from screamingface_engine.catalog.admission import RunModelAdmission
from screamingface_engine.config import Settings
from screamingface_engine.ports import IdentityAwareJobRunner, StoppedBeforeSchedule
from screamingface_engine.runner_queue import RunQueueUnavailable
from screamingface_engine.runs.records import (
    CandidateStart,
    DueRun,
    OwnerKey,
    PendingStart,
    StartPlan,
    StopReason,
)
from screamingface_engine.runs.registry import RunCanceled
from screamingface_engine.runs.stopping import make_stops
from screamingface_engine.scheduling import schedule_run
from screamingface_engine.stopping import stop_topic
from url4.streaming.interfaces import EventConsumer, JobAlreadyExists, JobRunnerAtCapacity
from url4.streaming.protocol import CachePolicy, TerminatedEvent
from url4.streaming.trace import format_traceparent

logger = logging.getLogger(__name__)

# The verified identity a start carries (`job_env.IDENTITY_HEADER_ENV`): the Run's owner (R1).
_OWNER_HEADER = "X-User-Email"
# The code of a permanent refusal that names none.
_REFUSED = "start_refused"


@dataclass(frozen=True)
class DriverSettings:
    """The driver's timings. ``retry_s`` is the fixed backoff when the runner gives no delay
    (R14: the in-process runner never does)."""

    inflight: int = 8
    lease_s: float = 60.0
    tick_s: float = 15.0
    outcome_grace_s: float = 120.0
    orphan_grace_s: float = 120.0
    job_deadline_s: int = 57_600
    retry_s: float = 5.0

    @classmethod
    def from_settings(cls, settings: Settings) -> DriverSettings:
        return cls(
            inflight=settings.run_driver_inflight,
            lease_s=settings.run_driver_lease_s,
            tick_s=settings.run_driver_tick_s,
            outcome_grace_s=settings.run_outcome_grace_s,
            orphan_grace_s=settings.orphan_grace_s,
            job_deadline_s=settings.job_deadline_s,
        )


class DriverRegistry(Protocol):
    """The part of the Run registry the driver uses (`runs.store_driver`, `runs.store`)."""

    def lease_run(
        self, run_id: str, held_until: datetime | None, until: datetime
    ) -> Awaitable[bool]: ...
    def release_run(self, run_id: str, held_until: datetime) -> Awaitable[None]: ...
    def due_runs(self, now: datetime) -> Awaitable[list[DueRun]]: ...
    def pending_starts(self, run_id: str) -> Awaitable[StartPlan | None]: ...
    def overdue(self, run_id: str, before: datetime) -> Awaitable[list[str]]: ...
    def stop(
        self, run_id: str, reason: StopReason, *, unless_followed_since: datetime | None = None
    ) -> Awaitable[bool]: ...
    def settle_startless(self) -> Awaitable[int]: ...
    def bind(
        self, owner: OwnerKey, run_id: str, candidate: int, topic: str, *, trace_id: str | None
    ) -> Awaitable[None]: ...
    def mark_scheduled(self, topic: str) -> Awaitable[bool]: ...
    def settle(self, topic: str, outcome: CandidateOutcome) -> Awaitable[None]: ...
    def stop_done(self, topic: str) -> Awaitable[None]: ...


class _Start(enum.Enum):
    STARTED = enum.auto()
    # Nothing was started; try again after a delay (at capacity, the queue unreachable).
    RETRY = enum.auto()
    # Settled or left to a stop; nothing more to do for this Candidate now.
    DONE = enum.auto()


class RunDrivers:
    """Every Run this App process drives: one task per Run it holds the lease of, and the tick."""

    def __init__(
        self,
        registry: DriverRegistry,
        job_runner: IdentityAwareJobRunner,
        *,
        stream: EventConsumer,
        settings: DriverSettings,
        clock: Callable[[], datetime],
        model_admission: RunModelAdmission | None = None,
    ) -> None:
        self._registry = registry
        self._job_runner = job_runner
        self._stream = stream
        self._settings = settings
        self._clock = clock
        self._model_admission = model_admission
        self._leases: dict[str, datetime] = {}
        self._tasks: dict[str, asyncio.Task[None]] = {}
        # The runner's last asked-for delay per Run (an at-capacity `Retry-After`).
        self._delays: dict[str, float] = {}
        self._woken = asyncio.Event()
        # INVARIANT (R10): the start of the current run of good ticks. No orphan stop is made
        # until it is `orphan_grace_s` old, so neither a restart nor a registry outage, during
        # which no follow could be recorded, stops a followed Run.
        self._healthy_since: datetime | None = None

    # --- the loop ------------------------------------------------------------------------------

    async def run(self) -> None:
        """Tick every `tick_s`, or at once when woken, and drive each Run the tick hands out."""
        while True:
            # WHY cleared before the tick: a wake that lands during it then brings the next one
            # at once, instead of being lost until `tick_s` passes.
            self._woken.clear()
            for run_id in await self.tick():
                self._spawn(run_id)
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self._woken.wait(), self._settings.tick_s)

    def wake(self) -> None:
        """Tick now: a Run was just registered (`POST /runs`)."""
        self._woken.set()

    async def aclose(self) -> None:
        """Stop driving, and give every lease up so another process may take the Runs at once."""
        tasks = list(self._tasks.values())
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        for run_id in list(self._leases):
            await self._release(run_id)

    def _spawn(self, run_id: str) -> None:
        task = self._tasks.get(run_id)
        if task is not None and not task.done():
            return
        task = asyncio.get_running_loop().create_task(self._drive(run_id), name=f"drive:{run_id}")
        self._tasks[run_id] = task
        task.add_done_callback(lambda done: self._forget(run_id, done))

    def _forget(self, run_id: str, task: asyncio.Task[None]) -> None:
        if self._tasks.get(run_id) is task:
            del self._tasks[run_id]
        if not task.cancelled() and task.exception() is not None:
            logger.error("driving %s failed", run_id, exc_info=task.exception())

    async def _drive(self, run_id: str) -> None:
        try:
            while await self.drive_once(run_id):
                await asyncio.sleep(self._pause(run_id))
        finally:
            await self._release(run_id)

    def _pause(self, run_id: str) -> float:
        """The wait before the next pass: the runner's delay or the fixed backoff, and never
        longer than a third of the lease, so the lease is renewed in time (R4)."""
        delay = self._delays.pop(run_id, None) or self._settings.retry_s
        return max(1.0, min(delay, self._settings.lease_s / 3))

    # --- the tick (R9 to R11) ------------------------------------------------------------------

    async def tick(self) -> list[str]:
        """One pass over the registry: stop Runs past their deadline and attached Runs nobody
        follows, make owed stops, settle Candidates nothing will start, and return the Runs that
        need a driver. A failed pass returns none and restarts the orphan clock."""
        now = self._clock()
        try:
            return await self._tick(now)
        except Exception:
            self._healthy_since = None
            logger.exception("the Run driver's tick failed; no orphan stop until it recovers")
            return []

    async def _tick(self, now: datetime) -> list[str]:
        due = await self._registry.due_runs(now)
        if self._healthy_since is None:
            self._healthy_since = now
        if await self._stop_due(due, now):
            due = await self._registry.due_runs(now)
        for run in due:
            if run.owed:
                await self._make_stops(run.owed)
        await self._registry.settle_startless()
        return [run.run_id for run in due if run.drive]

    async def _stop_due(self, due: list[DueRun], now: datetime) -> bool:
        grace = timedelta(seconds=self._settings.orphan_grace_s)
        assert self._healthy_since is not None
        orphans_allowed = now - self._healthy_since >= grace
        stopped = False
        for run in due:
            if run.past_deadline:
                stopped |= await self._registry.stop(run.run_id, "deadline")
            elif run.unfollowed and orphans_allowed:
                # The stop checks the stamp again in its own transaction: a follower that came
                # back since this read keeps the Run (R10).
                stopped |= await self._registry.stop(
                    run.run_id, "orphaned", unless_followed_since=now - grace
                )
        return stopped

    async def _make_stops(self, topics: tuple[str, ...] | list[str]) -> None:
        for topic, exc in await make_stops(self._registry, self._stop, list(topics)):
            # It stays owed, and the next tick makes it again (R9).
            logger.warning("stopping %s failed; the next tick tries again: %r", topic, exc)

    async def _stop(self, topic: str) -> None:
        await stop_topic(self._job_runner, self._stream, topic, bound=True)

    # --- one Run (R1, R2, R4, R7) --------------------------------------------------------------

    async def drive_once(self, run_id: str) -> bool:
        """One pass over a Run: renew its lease, settle Candidates whose outcome never came, and
        start pending ones while there is room. Whether the Run still needs driving."""
        now = self._clock()
        if not await self._renew(run_id, now):
            return False
        live = await self._drive_held(run_id, now)
        if not live:
            await self._release(run_id)
        return live

    async def _drive_held(self, run_id: str, now: datetime) -> bool:
        plan = await self._registry.pending_starts(run_id)
        if plan is None:
            return False
        await self._settle_overdue(run_id, now)
        if not plan.stopped:
            room = self._settings.inflight - plan.in_flight
            for pending in plan.pending[: max(room, 0)]:
                if await self._start(plan, pending) is _Start.RETRY:
                    break
        return bool(plan.pending) or plan.in_flight > 0

    async def _renew(self, run_id: str, now: datetime) -> bool:
        until = now + timedelta(seconds=self._settings.lease_s)
        if await self._registry.lease_run(run_id, self._leases.get(run_id), until):
            self._leases[run_id] = until
            return True
        # Another process holds the Run, or took it over: this driver stops.
        self._leases.pop(run_id, None)
        return False

    async def _release(self, run_id: str) -> None:
        held = self._leases.pop(run_id, None)
        if held is None:
            return
        try:
            await self._registry.release_run(run_id, held)
        except Exception:
            # It expires on its own after `lease_s`.
            logger.warning("could not release the lease of %s", run_id, exc_info=True)

    async def _start(self, plan: StartPlan, pending: PendingStart) -> _Start:
        """Bind the Candidate's topic, schedule its start and mark it scheduled (R1)."""
        topic = pending.topic or new_topic()
        trace_id = pending.trace_id or secrets.token_hex(16)
        result = await self._send(plan, pending, topic, trace_id)
        if result is _Start.STARTED and not await self._registry.mark_scheduled(topic):
            # A stop landed during the start and owes it a stop (R9).
            await self._make_stops([topic])
        return result

    async def _send(
        self, plan: StartPlan, pending: PendingStart, topic: str, trace_id: str
    ) -> _Start:
        try:
            with self._job_runner.start_attempt(topic):
                await self._registry.bind(
                    plan.owner, plan.run_id, pending.index, topic, trace_id=trace_id
                )
                await self._schedule(plan, pending, topic, trace_id)
        except (RunCanceled, StoppedBeforeSchedule):
            result = _Start.DONE  # the stop settles it (R9)
        except JobRunnerAtCapacity as exc:
            if exc.retry_after_s is not None:
                self._delays[plan.run_id] = float(exc.retry_after_s)
            result = _Start.RETRY
        except RunQueueUnavailable:
            # Nothing is known to have started; the same start goes again (D6).
            logger.warning("the run queue is unavailable; %s is retried", topic, exc_info=True)
            result = _Start.RETRY
        except JobAlreadyExists:
            result = _Start.STARTED  # R14: the in-process runner holds a task for it
        except Exception as exc:
            result = await self._refused(topic, exc)
        else:
            result = _Start.STARTED
        return result

    async def _schedule(
        self, plan: StartPlan, pending: PendingStart, topic: str, trace_id: str
    ) -> None:
        start: CandidateStart = pending.start
        await schedule_run(
            self._job_runner,
            self._model_admission,
            topic,
            start.url4,
            self._settings.job_deadline_s,
            cache=CachePolicy() if start.use_cache else CachePolicy(participate=False),
            traceparent=format_traceparent(trace_id, secrets.token_hex(8)),
            identity=None if plan.owner_email is None else {_OWNER_HEADER: plan.owner_email},
            answer_seed=start.answer_seed,
            client_version=plan.client_version,
            capture=start.capture,
            replay_frozen_copy=start.replay_frozen_copy,
            result_prefix=result_prefix(plan.run_id, pending.index),
            exclusive=True,
        )

    async def _refused(self, topic: str, exc: Exception) -> _Start:
        """A refusal that says it is permanent settles the Candidate `failed` with its code; any
        other failure is retried, since the start may still land (R1)."""
        if getattr(exc, "permanent", False) is not True:
            logger.warning("starting %s failed; it is retried", topic, exc_info=exc)
            return _Start.RETRY
        code = getattr(exc, "code", None)
        error_code = storable_error_code(code if isinstance(code, str) and code else _REFUSED)
        await self._registry.settle(topic, CandidateOutcome("failed", error_code))
        return _Start.DONE

    async def _settle_overdue(self, run_id: str, now: datetime) -> None:
        """R7: a Candidate whose run ended but whose outcome never arrived settles from its
        terminal frame, once the frame is older than `outcome_grace_s`: state and error code, no
        cost and no record, which the runner's own outcome fills if it lands later."""
        grace = timedelta(seconds=self._settings.outcome_grace_s)
        for topic in await self._registry.overdue(run_id, now - grace):
            try:
                frame = await self._job_runner.last_frame(topic)
            except QueueReadError:
                continue
            if not isinstance(frame, TerminatedEvent) or frame.time is None:
                continue
            if frame.time + grace > now or frame.data.status not in OUTCOME_STATUSES:
                continue
            error = frame.data.error
            outcome = CandidateOutcome(
                cast(OutcomeStatus, frame.data.status),
                storable_error_code(None if error is None else error.code),
                finished_at=frame.time,
            )
            await self._registry.settle(topic, outcome)


__all__ = ["DriverRegistry", "DriverSettings", "RunDrivers"]
