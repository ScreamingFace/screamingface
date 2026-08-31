"""`InProcessJobRunner` — the `JobRunner` over an `asyncio.Task` per run (local mode).

The local-mode counterpart to `K8sJobRunner`: same port, same deterministic `job_name(topic)`
identity, same single-use 409 guard — a task registry instead of a cluster.

# INVARIANT: engine-free. The concrete `Executor` arrives through an injected
# factory, so this module imports neither the url4 engine nor
# `screamingface_engine.runner`. That is what keeps it a SHARED leaf under
# `.claude/scripts/check_layering.py` rather than a hole in the control-plane/
# run-mode boundary — the one module that fuses the two halves is
# `screamingface_engine.local`, and it is exempt there by name.
"""

import asyncio
import logging
from collections.abc import Callable, Mapping, Sequence

from screamingface_engine import job_env
from screamingface_engine.ports import IdentityAwareJobRunner
from url4.streaming.interfaces import (
    EventPublisher,
    Executor,
    JobAlreadyExists,
    JobRunnerAtCapacity,
    JobStatus,
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

# INVARIANT: strictly above the Client's per-Evaluation fan-out, which is 8 (
# `_MAX_CANDIDATES_IN_FLIGHT` in `packages/screamingface/src/screamingface/_evaluation/
# runner.py`). The Client opens one run per Candidate, so an equal value leaves zero headroom
# and one ordinary Evaluation saturates the runner exactly. Pinned by
# `tests/unit/test_local_capacity_contract.py`, which also explains why that check is a floor
# rather than a direct comparison.
DEFAULT_MAX_CONCURRENT_RUNS = 32
DEFAULT_MAX_HISTORY = 1000


def _terminal_status(task: asyncio.Task[None]) -> JobStatus:
    if task.cancelled():
        return "stopped"
    return "failed" if task.exception() is not None else "succeeded"


def _map_status(task: asyncio.Task[None] | None) -> JobStatus:
    if task is None:
        return "not_found"
    if not task.done():
        return "running"
    return _terminal_status(task)


class InProcessJobRunner(IdentityAwareJobRunner):
    """`JobRunner` backed by a `dict[str, asyncio.Task]`, one task per run.

    Differs from `K8sJobRunner` in two ways that follow from the substrate rather than from
    choice:

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
    ) -> None:
        self._stream = stream
        self._factory = executor_factory
        # WHY a callable and not a snapshot (OME-880): the admitted-model overlay grows while
        # the app runs, and a model admitted a second ago must reach the very next run.
        self._extra_models = extra_models
        # WHY injected rather than read from os.environ here: the deploy-time half of a run's
        # environment (aigateway base URL, Tavily key, runner config path) is ambient in local
        # mode, and taking it as a parameter is what keeps this class testable without monkey-
        # patching the process environment.
        self._base_env = dict(base_env or {})
        self._tasks: dict[str, asyncio.Task[None]] = {}
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

    def _on_done(self, _task: asyncio.Task[None]) -> None:
        # INVARIANT: registered exactly once per schedule(), so each run decrements exactly once
        # however it ended.
        self._active -= 1
        self._prune_history()

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

    def active_count(self) -> int:
        """Runs still in flight — the admission gate's input, and what `/metrics` would report."""
        return self._active

    # --- the run environment ----------------------------------------------------------------

    def _env(
        self,
        topic: str,
        url4: str,
        deadline_s: int,
        traceparent: str | None,
        profile: str | None,
        identity: Mapping[str, str] | None = None,
        cache: CachePolicy | None = None,
    ) -> dict[str, str]:
        """The environment this run's `Executor` is built from.

        Deliberately the same `job_env` keys `K8sJobRunner._env` writes onto a Job spec: the two
        adapters are two renderings of ONE contract, so `build_executor` cannot tell a local run
        from a Job's, and a variable added to one adapter is visibly missing from the other.
        """
        env = dict(self._base_env)
        env[job_env.TOPIC] = topic
        env[job_env.EXPRESSION] = url4
        env[job_env.JOB_DEADLINE_S] = str(deadline_s)
        forwarded = valid_traceparent(traceparent)
        if forwarded is not None:
            env[job_env.TRACEPARENT] = forwarded
        # INVARIANT: the request's profile REPLACES the ambient one rather than inheriting it. A
        # profile left over in `_base_env` would silently route one caller's run through a profile
        # they never asked for — the same reasoning as the identity reset below.
        if profile is not None:
            env[job_env.AIGATEWAY_PROFILE] = profile
        else:
            env.pop(job_env.AIGATEWAY_PROFILE, None)
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
        # INVARIANT (OME-908): local mode's downstream bound is the shared fair-share gate,
        # NEVER this env — a copy exported in the operator's shell would stack a per-run
        # `BoundedIOLayer` UNDER the gate and re-introduce exactly the static bound local
        # mode replaced. Popped unconditionally; the gate reaches runs through the
        # executor factory's `io_gate`, not through env.
        env.pop(job_env.IO_CONCURRENCY, None)
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
        profile: str | None = None,
        identity: Mapping[str, str] | None = None,
        cache: CachePolicy | None = None,
    ) -> str:
        """Spawn the run as a task and return its job name.

        Raises:
            JobRunnerAtCapacity: too many runs already in flight.
            JobAlreadyExists: a run for this topic is still running.
        """
        if self._active >= self._max_concurrent:
            raise JobRunnerAtCapacity(self._active, self._max_concurrent)
        name = job_name(topic)
        existing = self._tasks.get(name)
        if existing is not None and not existing.done():
            raise JobAlreadyExists(name)
        env = self._env(topic, url4, deadline_s, traceparent, profile, identity, cache)
        # WHY build the Executor here but resolve its world lazily (inside `execute`): a factory
        # that raised now would take down the caller's request with nothing on the stream, where a
        # failure inside the run terminates the topic properly. See `Url4Executor._resolve_world`.
        executor = self._factory(env)
        task = asyncio.get_running_loop().create_task(
            lifecycle_run(
                self._stream,
                executor,
                topic,
                url4,
                traceparent=traceparent,
                deadline_s=deadline_s,
            ),
            name=f"url4-run:{name}",
        )
        task.add_done_callback(self._on_done)
        self._tasks[name] = task
        self._active += 1
        return name

    async def stop(self, topic: str) -> None:
        """Cancel the run, if one is live. Idempotent — absent or finished is a no-op.

        Cancelling is what produces the run's `Terminated(stopped)` frame: `lifecycle.run`
        publishes it on the way out. No purge here — the REST DELETE route purges separately and
        the WS stop path deliberately does not, which mirrors `K8sJobRunner`.
        """
        task = self._tasks.get(job_name(topic))
        if task is not None and not task.done():
            task.cancel()

    async def exists(self, topic: str) -> bool:
        task = self._tasks.get(job_name(topic))
        return task is not None and not task.done()

    async def status(self, topic: str) -> JobStatus:
        return _map_status(self._tasks.get(job_name(topic)))

    async def aclose(self) -> None:
        """Cancel every in-flight run and await it — graceful shutdown.

        Each cancelled run still publishes its own `Terminated(stopped)`, so a client attached
        during shutdown sees the run end rather than the socket simply going quiet.
        """
        pending = [task for task in self._tasks.values() if not task.done()]
        for task in pending:
            task.cancel()
        if pending:
            _logger.info("cancelling %d in-flight local run(s) on shutdown", len(pending))
            await asyncio.gather(*pending, return_exceptions=True)


__all__ = [
    "DEFAULT_MAX_CONCURRENT_RUNS",
    "DEFAULT_MAX_HISTORY",
    "ExecutorFactory",
    "InProcessJobRunner",
]
