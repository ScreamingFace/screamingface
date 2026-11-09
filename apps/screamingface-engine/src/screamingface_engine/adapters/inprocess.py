"""`InProcessJobRunner` — the `JobRunner` over an `asyncio.Task` per run (local mode).

The local-mode counterpart to the queue-backed runner: same port, same deterministic
`job_name(topic)` identity, same single-use 409 guard — a task registry instead of a
queue and a worker pool.

# INVARIANT: engine-free. The concrete `Executor` arrives through an injected
# factory, so this module imports neither the url4 engine nor
# `screamingface_engine.runner`. That is what keeps it a SHARED leaf under
# `.claude/scripts/check_layering.py` rather than a hole in the control-plane/
# run-mode boundary — the one module that fuses the two halves is
# `screamingface_engine.local`, and it is exempt there by name.

Span export (e2e workbench unit 6a): with an OTLP endpoint configured, each run flushes its span
tree after its terminal frame, off the event loop, and the run's task waits for it. A slow or
down collector therefore keeps the run's admission slot (and `exists()` / `status() == "running"`)
for up to `tracing.otlp.FLUSH_TIMEOUT_MS` after `Terminated` — the same hold a Job's process has
before it exits. With no endpoint (the default) there is no flush and no hold. The flush itself
is owned by the runner, not the run's task: cancelling the run stops the WAIT, never the flush,
and `aclose()` returns only after every flush has finished.
"""

import asyncio
import logging
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping, Sequence
from datetime import datetime
from decimal import Decimal
from functools import partial
from typing import cast

from screamingface_engine import job_env
from screamingface_engine.candidate_outcomes import CandidateOutcomeStream, publish_outcome
from screamingface_engine.client_provenance import ProvenanceExecutor
from screamingface_engine.ports import IdentityAwareJobRunner, StoppedBeforeSchedule
from screamingface_engine.run_evidence import (
    SettlementWatch,
    adopt_or_mint_traceparent,
    log_scheduled,
    log_terminated,
    outcome_of,
    settlement_of,
)
from screamingface_engine.subjects import RUN_ROOT_NODE
from screamingface_engine.tracing.loader import load_span_sink
from screamingface_engine.tracing.relay import SpanRelay, SpanSink
from url4.streaming.interfaces import (
    EventPublisher,
    ExecStep,
    Executor,
    JobAlreadyExists,
    JobRunnerAtCapacity,
    JobStatus,
    TraceContext,
    job_name,
)
from url4.streaming.lifecycle import run as lifecycle_run
from url4.streaming.protocol import CachePolicy
from url4.streaming.trace import valid_traceparent

_logger = logging.getLogger(__name__)

ExecutorFactory = Callable[[Mapping[str, str]], Executor]
"""Builds the per-run `Executor` from that run's environment.

Takes the env rather than the run's fields so it is satisfied by `runner.main.build_executor`
verbatim — the same entry point a real Job's process calls, given the same variables.
"""

ExtraModelRefresh = Callable[[Mapping[str, str]], Awaitable[None]]
"""Refresh dynamic model state for one verified caller before its run env is rendered."""

SpanSinkLoader = Callable[[Mapping[str, str]], SpanSink | None]
"""Builds a run's span sink from the environment, or ``None`` when no OTLP endpoint is set.

`tracing.loader.load_span_sink` in production — the same loader a Job's `runner.main` calls —
and a seam for tests, which hand in a recording fake instead of a real exporter.
"""


class _PreparedExecutor(Executor):
    """Build the real executor lazily, inside the already-registered run lifecycle."""

    def __init__(self, prepare: Callable[[], Awaitable[Executor]]) -> None:
        self._prepare = prepare
        self._built: Executor | None = None

    def last_summary(self) -> object:
        """The built executor's summary, so a run's cost reaches its outcome (OME-1785)."""
        return None if self._built is None else _summary_of(self._built)

    async def execute(
        self,
        url4: str,
        *,
        trace: TraceContext | None = None,
    ) -> AsyncIterator[ExecStep]:
        executor = self._built = await self._prepare()
        steps = executor.execute(url4, trace=trace)
        try:
            async for step in steps:
                yield step
        finally:
            close = getattr(steps, "aclose", None)
            if close is not None:
                await close()


# INVARIANT: strictly above the Client's per-Evaluation fan-out, which is 8 (
# `_MAX_CANDIDATES_IN_FLIGHT` in `packages/screamingface/src/screamingface/_evaluation/
# runner.py`). The Client opens one run per Candidate, so an equal value leaves zero headroom
# and one ordinary Evaluation saturates the runner exactly. Pinned by
# `tests/unit/test_local_capacity_contract.py`, which also explains why that check is a floor
# rather than a direct comparison.
DEFAULT_MAX_CONCURRENT_RUNS = 32
DEFAULT_MAX_HISTORY = 1000


def _summary_of(executor: Executor) -> object:
    last_summary = getattr(executor, "last_summary", None)
    return None if last_summary is None else last_summary()


def _cost_of(executor: Executor) -> Decimal | None:
    """The run's exact cost from its executor's summary, or None when it has none (spec R3)."""
    cost = getattr(_summary_of(executor), "cost_usd", None)
    return cost if isinstance(cost, Decimal) else None


def _terminal_status(task: asyncio.Task[None]) -> JobStatus:
    if task.cancelled():
        return "stopped"
    return "failed" if task.exception() is not None else "succeeded"


def _map_status(task: asyncio.Task[None] | None, verdict: JobStatus | None = None) -> JobStatus:
    if task is None:
        return "not_found"
    if not task.done():
        return "running"
    # INVARIANT: the run's own terminal frame wins over how its task ended. A stop/aclose that
    # lands during the post-terminal span flush cancels the task, but the run had already ended
    # `succeeded`/`failed` — reading the task would rewrite that verdict to `stopped`.
    return verdict if verdict is not None else _terminal_status(task)


class InProcessJobRunner(IdentityAwareJobRunner):
    """`JobRunner` backed by a `dict[str, asyncio.Task]`, one task per run.

    Differs from the queue-backed runner in two ways that follow from the substrate rather
    than from choice:

    * A completed task frees its `job_name` slot immediately (see `exists`), because there is no
      lingering substrate object to block a re-run — where a finished Job persists until its TTL.
    * Admission is this runner's own responsibility (`max_concurrent_runs`). A cluster absorbs
      surplus Jobs by scheduling them later; here every accepted run shares one event loop, so
      over-admitting degrades every run in flight instead of queueing.
    """

    def __init__(
        self,
        stream: EventPublisher,
        executor_factory: ExecutorFactory,
        *,
        base_env: Mapping[str, str] | None = None,
        max_concurrent_runs: int = DEFAULT_MAX_CONCURRENT_RUNS,
        max_history: int = DEFAULT_MAX_HISTORY,
        extra_models: Callable[[], Sequence[str]] | None = None,
        refresh_extra_models: ExtraModelRefresh | None = None,
        span_sink: SpanSinkLoader = load_span_sink,
        outcomes: CandidateOutcomeStream | None = None,
    ) -> None:
        self._stream = stream
        self._span_sink = span_sink
        # FEATURE (OME-1785): each run's Candidate outcome, for the Run registry's writer. Only
        # the run writes a terminal frame here, so its frame always landed (spec R3).
        self._outcomes = outcomes
        self._outcome_publishes: set[asyncio.Task[None]] = set()
        self._factory = executor_factory
        # WHY a callable and not a snapshot (OME-880): the admitted-model overlay grows while
        # the app runs, and a model admitted a second ago must reach the very next run.
        self._extra_models = extra_models
        self._refresh_extra_models = refresh_extra_models
        # WHY injected rather than read from os.environ here: the deploy-time half of a run's
        # environment (aigateway base URL, Tavily key, runner config path) is ambient in local
        # mode, and taking it as a parameter is what keeps this class testable without monkey-
        # patching the process environment.
        self._base_env = dict(base_env or {})
        self._tasks: dict[str, asyncio.Task[None]] = {}
        # Topics a bound stop reached before their task existed (E5 P1 spec D12): their
        # `schedule()` spawns nothing. Not consumed, so a resent start of the topic cannot run;
        # bounded oldest-first by `max_history`, the same bound as the single-use task registry.
        self._stopped_before_schedule: dict[str, None] = {}
        # INVARIANT (OME-1747 review): one entry per built span sink until its close has
        # finished. The runner, not the run's task, owns these: `stop()`/`aclose()` cancel the
        # run's task, and a close owned by that task was cancelled with it — never run at all
        # when it was still queued on a busy default executor. `aclose()` waits for every entry.
        self._sink_closes: set[asyncio.Task[None]] = set()
        # The terminal frame's verdict per job name, recorded before the span flush is awaited.
        # Pruned in step with `_tasks`; replaced when a topic is re-run.
        self._verdicts: dict[str, JobStatus] = {}
        # WHY a counter and not len(_tasks): _tasks retains completed entries so status() can
        # report a terminal state instead of not_found, which would make an active count O(history).
        # This increments per schedule() and decrements from a done-callback on every completion
        # path (return, raise, cancel), so admission stays O(1).
        self._active = 0
        self._max_concurrent = max_concurrent_runs
        # WHY bounded: a finished Job is reclaimed by the substrate's TTL, but this dict has no
        # external reaper — a long-lived local process would otherwise retain one Task (plus any
        # stored exception and traceback) per distinct topic for its whole life.
        self._max_history = max_history

    # --- admission and bookkeeping ----------------------------------------------------------

    def _on_done(
        self,
        task: asyncio.Task[None],
        *,
        topic: str,
        traceparent: str,
        watch: SettlementWatch,
        executor: Executor,
    ) -> None:
        # INVARIANT: registered exactly once per schedule(), so each run decrements exactly once
        # however it ended.
        self._active -= 1
        self._prune_history()
        # FEATURE (OME-940): the durable half of the evidence. Emitted for EVERY outcome — the
        # failed run is the one whose record is needed, and it was the one previously losing it.
        outcome, error = outcome_of(watch, task)
        log_terminated(_logger, topic=topic, traceparent=traceparent, outcome=outcome, error=error)
        if self._outcomes is not None:
            settled = settlement_of(watch, task, cost_usd=_cost_of(executor))
            publish = asyncio.get_running_loop().create_task(
                publish_outcome(self._outcomes, topic, settled)
            )
            self._outcome_publishes.add(publish)
            publish.add_done_callback(self._outcome_publishes.discard)

    def _prune_history(self) -> None:
        if len(self._tasks) <= self._max_history:
            return
        # Oldest-first (dicts preserve insertion order), evicting only DONE entries — reclaiming a
        # live task's slot would re-open the single-use guard for a run still in flight.
        for name, task in list(self._tasks.items()):
            if len(self._tasks) <= self._max_history:
                return
            if task.done():
                del self._tasks[name]
                self._verdicts.pop(name, None)

    def active_count(self) -> int:
        """Runs still in flight — the admission gate's input, and what `/metrics` reports.

        Read at scrape time by `metrics._ActiveRunsCollector` as
        `screamingface_engine_active_runs` (OME-942). It used to say "would report", which was
        true: nothing read it, so the one number that says whether the App is at its admission
        ceiling was visible only to the code enforcing it.
        """
        return self._active

    # --- the run environment ----------------------------------------------------------------

    def _env(
        self,
        topic: str,
        url4: str,
        deadline_s: int,
        traceparent: str | None,
        identity: Mapping[str, str] | None = None,
        cache: CachePolicy | None = None,
        answer_seed: int | None = None,
        shape: job_env.RunShape = "expression",
        capture: bool = False,
        replay_frozen_copy: str | None = None,
    ) -> dict[str, str]:
        """The environment this run's `Executor` is built from.

        Deliberately the same `job_env` keys the queue codec writes onto a run's message: the
        two adapters are two renderings of ONE contract, so `build_executor` cannot tell a local
        run from a worker's, and a variable added to one adapter is visibly missing from the
        other.
        """
        env = job_env.without_retired_keys(self._base_env)
        env[job_env.TOPIC] = topic
        env[job_env.EXPRESSION] = url4
        env[job_env.JOB_DEADLINE_S] = str(deadline_s)
        forwarded = valid_traceparent(traceparent)
        if forwarded is not None:
            env[job_env.TRACEPARENT] = forwarded
        # INVARIANT: the request's identity REPLACES the ambient one rather than merging with it.
        # `_base_env` is this process's own environment, so a leftover identity key there would
        # otherwise leak one caller's identity onto another caller's run — and a partial merge is
        # worse than either, since it would pair one caller's email with another's tenant.
        for name in job_env.IDENTITY_HEADER_ENV.values():
            env.pop(name, None)
        env.update(job_env.identity_to_env(identity or {}))
        # INVARIANT: same reset, and the sharpest case for it. `_base_env` is one dict shared by
        # every local run, so a leftover `participate=true` would let a run that explicitly opted
        # out be served a stored answer it refused — the exact silent, chargeable failure this
        # whole design exists to prevent. Cleared unconditionally, then re-stated from THIS run.
        for name in (job_env.CACHE_PARTICIPATE, job_env.CACHE_MAX_AGE_S):
            env.pop(name, None)
        env.update(job_env.cache_policy_to_env(cache))
        # INVARIANT: same reset as identity/cache policy — the CURRENT overlay replaces any
        # ambient value, so a stale admitted set in `_base_env` never leaks onto a run (OME-880).
        env.pop(job_env.EXTRA_MODELS, None)
        if self._extra_models is not None:
            env.update(job_env.extra_models_to_env(self._extra_models()))
        # INVARIANT: same reset as cache/identity — a leftover seed in `_base_env` would stamp
        # one caller's sitting onto the next caller's run, corrupting both records (OME-1038).
        env.pop(job_env.ANSWER_SEED, None)
        env.update(job_env.answer_seed_to_env(answer_seed))
        # INVARIANT: same reset (OME-1307). A leftover mode in the shared `_base_env` would turn the
        # next caller's normal run into a capture or a paid run into a replay, so both keys are
        # re-stated from THIS run.
        env.pop(job_env.CAPTURE, None)
        env.pop(job_env.REPLAY_FROZEN_COPY, None)
        env.update(job_env.capture_env(capture))
        env.update(job_env.replay_frozen_copy_env(replay_frozen_copy))
        # INVARIANT (OME-908): local mode's downstream bound is the shared fair-share gate,
        # NEVER this env — a copy exported in the operator's shell would stack a per-run
        # `BoundedIOLayer` UNDER the gate and re-introduce exactly the static bound local
        # mode replaced. Popped unconditionally; the gate reaches runs through the
        # executor factory's `io_gate`, not through env.
        env.pop(job_env.IO_CONCURRENCY, None)
        # Same reset: the shape is THIS run's, never an ambient value (uniform executor PRD 04).
        env.pop(job_env.RUN_SHAPE, None)
        env[job_env.SPEC_VERSION] = job_env.CURRENT_SPEC_VERSION
        if shape == "direct":
            env[job_env.RUN_SHAPE] = "direct"
        return env

    # --- the JobRunner port -----------------------------------------------------------------

    async def schedule(
        self,
        topic: str,
        url4: str,
        deadline_s: int,
        *,
        traceparent: str | None = None,
        credential: str | None = None,
        identity: Mapping[str, str] | None = None,
        cache: CachePolicy | None = None,
        answer_seed: int | None = None,
        client_version: str | None = None,
        shape: job_env.RunShape = "expression",
        capture: bool = False,
        replay_frozen_copy: str | None = None,
        enqueued_at: datetime | None = None,
    ) -> str:
        """Spawn the run as a task and return its job name.

        Raises:
            JobRunnerAtCapacity: too many runs already in flight.
            JobAlreadyExists: a run for this topic is still running.
        """
        name = job_name(topic)
        # Before the capacity check: a canceled start answers as canceled, never "retry".
        if topic in self._stopped_before_schedule:
            raise StoppedBeforeSchedule(topic)
        if self._active >= self._max_concurrent:
            raise JobRunnerAtCapacity(self._active, self._max_concurrent)
        existing = self._tasks.get(name)
        if existing is not None and not existing.done():
            raise JobAlreadyExists(name)
        # FEATURE (OME-940): decide the run's traceparent HERE, adopting the caller's or minting
        # one, so the control plane can name the run it is scheduling and `job_env.TRACEPARENT`
        # is always set. Left to `lifecycle.run`, the id would be minted after this returns and
        # this adapter — and the runner's log context — would never learn it.
        run_traceparent = adopt_or_mint_traceparent(traceparent)

        def build() -> Executor:
            env = self._env(
                topic,
                url4,
                deadline_s,
                run_traceparent,
                identity,
                cache,
                answer_seed=answer_seed,
                shape=shape,
                capture=capture,
                replay_frozen_copy=replay_frozen_copy,
            )
            return self._factory(env)

        async def prepare() -> Executor:
            # FEATURE (OME-1499): refresh runs INSIDE the registered lifecycle, but before
            # `_env` reads the snapshot. Capacity/topic reservation therefore stays atomic,
            # and a cold fetch never delays the schedule response before a stream exists.
            assert self._refresh_extra_models is not None
            await self._refresh_extra_models(identity or {})
            return build()

        executor = build() if self._refresh_extra_models is None else _PreparedExecutor(prepare)
        watch = SettlementWatch(self._stream)
        self._verdicts.pop(name, None)
        task = asyncio.get_running_loop().create_task(
            self._exported_run(
                name,
                watch,
                ProvenanceExecutor(executor, client_version),
                topic,
                url4,
                traceparent=run_traceparent,
                deadline_s=deadline_s,
            ),
            name=f"url4-run:{name}",
        )
        task.add_done_callback(
            partial(
                self._on_done,
                topic=topic,
                traceparent=run_traceparent,
                watch=watch,
                executor=executor,
            )
        )
        self._tasks[name] = task
        self._active += 1
        log_scheduled(_logger, topic=topic, traceparent=run_traceparent, job_name=name)
        return name

    async def _exported_run(
        self,
        name: str,
        watch: SettlementWatch,
        executor: Executor,
        topic: str,
        url4: str,
        *,
        traceparent: str,
        deadline_s: int,
    ) -> None:
        """`lifecycle.run`, publishing through the run's `SpanRelay` (e2e workbench unit 6a).

        FEATURE: the same wrap `runner.main._run_process` gives a Job, so a local run exports its
        `url4.run` span tree when `OTEL_EXPORTER_OTLP_ENDPOINT` (or the traces-specific variable)
        is set, and is a pure passthrough when it is not — the default. Before this, the local
        engine exported nothing at all.

        WHY the relay is built HERE, inside the task, and not in `schedule`: a run cancelled
        before its first step never enters this body, so it never builds a sink — and a built
        sink owns an exporter thread that only `shutdown` stops. Built in `schedule`, that run
        would leak the thread.

        WHY the relay is OUTSIDE `TerminalWatch` (relay -> watch -> stream): both are transparent
        proxies, and with the relay outermost the watch and the stream receive the very objects
        `lifecycle.run` published.

        INVARIANT: telemetry never fails or alters a run (OME-1130 ledger D4). The relay swallows
        every sink error and `shutdown` logs a failed close. The production loader never raises,
        but `span_sink` is an injected seam, so a raising loader is logged here and the run goes
        ahead unexported rather than dying before its first frame.

        INVARIANT: the terminal verdict is recorded only when `lifecycle.run` RETURNS — that is
        its promise that the outcome is published and durable. When it raises (the terminal
        flush failed, or a cancel landed on it), the frame may not be durable and the task's
        own `failed`/`stopped` stands. The verdict is recorded BEFORE the span flush is
        awaited, so a stop or shutdown that cancels the task during that later flush cannot
        turn a finished run into `stopped`.

        WHY the loader gets `_base_env` and not the run's synthesised env: only the ambient
        `OTEL_*` variables configure export, and they live in the base env — the per-run keys
        `_env` adds (topic, expression, identity, ...) have no bearing on the exporter.
        """
        try:
            sink = self._span_sink(self._base_env)
        except Exception:
            _logger.warning(
                "span sink loader raised; run %s proceeds without span export",
                topic,
                exc_info=True,
            )
            sink = None
        relay = SpanRelay(watch, sink, traceparent=traceparent)
        try:
            await lifecycle_run(
                relay,
                executor,
                topic,
                url4,
                node=RUN_ROOT_NODE,
                traceparent=traceparent,
                deadline_s=deadline_s,
            )
            if watch.outcome is not None:
                self._verdicts[name] = cast(JobStatus, watch.outcome)
        finally:
            if sink is not None:
                # WHY shielded: cancelling the run must stop only this task's WAIT, never the
                # close itself (see `_close_sink`). Awaited so the run's task still ends only
                # once its trace, root span included, has been handed over.
                await asyncio.shield(self._close_sink(relay))

    def _close_sink(self, relay: SpanRelay) -> asyncio.Task[None]:
        """Start the run's sink close as a task the RUNNER owns, and return it.

        WHY a thread: `OtlpSpanSink.close` joins its flush for up to its bound, and every local
        run shares this one event loop — a blocking flush here would stall every other run.

        INVARIANT: called once per built sink, from the run's `finally`, so the close runs
        exactly once. Nothing ever cancels this task: the run's cancel stops at the shield, and
        `aclose()` awaits a shielded view of it, so cancelling `aclose()` stops at its shield
        too — a close queued behind a saturated default executor still runs once a worker frees.
        The done callback therefore removes the task only once it has actually finished.
        """
        close = asyncio.get_running_loop().create_task(asyncio.to_thread(relay.shutdown))
        self._sink_closes.add(close)
        close.add_done_callback(self._sink_closes.discard)
        return close

    async def stop(self, topic: str) -> None:
        """Cancel the run, if one is live. Idempotent — absent or finished is a no-op.

        Cancelling is what produces the run's `Terminated(stopped)` frame: `lifecycle.run`
        publishes it on the way out. No purge here — the REST DELETE route purges separately and
        the WS stop path deliberately does not, which mirrors the queue runner.
        """
        task = self._tasks.get(job_name(topic))
        if task is not None:
            _stop_once(task)

    async def stop_bound(self, topic: str) -> None:
        """As `stop`, but a topic with no task yet never gets one (E5 P1 spec D12).

        WHY: a cancel can land between a start's bind and its schedule. Plain `stop` would find
        nothing to cancel, and the task spawned next would run until the start's confirmation
        stopped it, which may already have called a provider.
        """
        if job_name(topic) not in self._tasks:
            self._stopped_before_schedule[topic] = None
            while len(self._stopped_before_schedule) > self._max_history:
                del self._stopped_before_schedule[next(iter(self._stopped_before_schedule))]
        await self.stop(topic)

    async def exists(self, topic: str) -> bool:
        task = self._tasks.get(job_name(topic))
        return task is not None and not task.done()

    async def status(self, topic: str) -> JobStatus:
        name = job_name(topic)
        return _map_status(self._tasks.get(name), self._verdicts.get(name))

    async def aclose(self) -> None:
        """Cancel every in-flight run and await it — graceful shutdown.

        Each cancelled run still publishes its own `Terminated(stopped)`, so a client attached
        during shutdown sees the run end rather than the socket simply going quiet.

        INVARIANT: each run is stopped exactly once (`_stop_once`), whether by `stop()`, this
        call, or a concurrent/repeated `aclose()`; every caller then waits for the same run
        completion, and cancelling a caller never reaches the run.

        INVARIANT: returns only after every span-sink close has FINISHED — including closes a
        cancelled run started and stopped waiting for. Those are awaited through shields, never
        cancelled — not even when this `aclose()` itself is cancelled: a close still queued on
        the default executor would otherwise never run, and the done callback would drop it
        from `_sink_closes` before any other `aclose()` could wait for it.
        """
        self._stopped_before_schedule.clear()
        pending = [task for task in self._tasks.values() if not task.done()]
        for task in pending:
            _stop_once(task)
        if pending:
            _logger.info("cancelling %d in-flight local run(s) on shutdown", len(pending))
            # WHY shielded views: gather cancels its children when its caller is cancelled.
            # Without the shields, a cancelled `aclose()` — or one of two concurrent calls —
            # would cancel each run a SECOND time while it flushes its `Terminated(stopped)`
            # frame, cutting that flush off. A caller's cancel now abandons only its own wait.
            await asyncio.gather(*(asyncio.shield(t) for t in pending), return_exceptions=True)
        # The cancelled runs' outcomes are on their way out; let them land before the stream goes.
        if self._outcome_publishes:
            await asyncio.gather(*self._outcome_publishes, return_exceptions=True)
        # Read AFTER the runs are gathered: a run cancelled above starts its close on the way out.
        closes = list(self._sink_closes)
        if closes:
            # WHY shielded views: gather cancels its children when its caller is cancelled
            # (`return_exceptions` does not stop that). Cancelling this `aclose()` must stop
            # only its own wait — the runner-owned close stays queued/running and tracked, so a
            # concurrent or repeated `aclose()` still waits for the real completion.
            await asyncio.gather(*(asyncio.shield(c) for c in closes), return_exceptions=True)


def _stop_once(task: asyncio.Task[None]) -> None:
    """Cancel a live run unless a stop is already on its way.

    WHY `cancelling()`: a run that is already stopping is publishing and flushing its
    `Terminated(stopped)` frame. A second cancel would land on that flush and cut it off, so the
    stop frame might never become durable. `lifecycle.run` never uncancels, so a non-zero count
    means a stop already reached (or is about to reach) the run.
    """
    if not task.done() and task.cancelling() == 0:
        task.cancel()


__all__ = [
    "DEFAULT_MAX_CONCURRENT_RUNS",
    "DEFAULT_MAX_HISTORY",
    "ExecutorFactory",
    "InProcessJobRunner",
    "SpanSinkLoader",
]
