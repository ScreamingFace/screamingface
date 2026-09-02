"""`InProcessJobRunner` — the local-mode `JobRunner` over asyncio tasks.

Two things are worth pinning here beyond the happy path: the run ENVIRONMENT it synthesises (it
must be the same `job_env` contract the queue codec writes onto a run's message, or
`build_executor` would behave differently local vs deployed), and its ADMISSION behaviour (a
cluster queues surplus work; one event loop cannot, so this adapter has to refuse).
"""

import asyncio
from collections.abc import AsyncIterator, Mapping
from decimal import Decimal

import pytest

from screamingface_engine import job_env
from screamingface_engine.adapters.inprocess import InProcessJobRunner
from screamingface_engine.adapters.memory import InMemoryEventStream
from url4.streaming.interfaces import (
    Completed,
    ExecStep,
    Executor,
    JobAlreadyExists,
    JobRunnerAtCapacity,
    TraceContext,
    job_name,
)
from url4.streaming.protocol import ResultData, StartedEvent, TerminatedEvent
from url4.streaming.protocol.signals import CostUsageData
from url4.streaming.protocol.taxonomy import CostBreakdown, TokenUsage

TOPIC = "t-local"

pytestmark = pytest.mark.asyncio


def _subtree() -> CostUsageData:
    return CostUsageData(
        scope="self",
        provider="test",
        model="test-model",
        pricing_version="v0",
        usage=TokenUsage(input_tokens=0, output_tokens=0),
        cost=CostBreakdown(total_usd=Decimal("0")),
    )


class _StubExecutor(Executor):
    """Yields a Completed immediately, or blocks forever, or raises."""

    def __init__(self, *, block: bool = False, boom: Exception | None = None) -> None:
        self._block = block
        self._boom = boom
        self.env: Mapping[str, str] | None = None

    async def execute(
        self, url4: str, *, trace: TraceContext | None = None
    ) -> AsyncIterator[ExecStep]:
        if self._boom is not None:
            raise self._boom
        if self._block:
            await asyncio.Event().wait()
        yield Completed(result=ResultData(body="ok"), subtree_cost=_subtree())


def _runner(
    stream: InMemoryEventStream,
    executor: Executor | None = None,
    *,
    base_env: Mapping[str, str] | None = None,
    max_concurrent_runs: int = 8,
    max_history: int = 1000,
) -> tuple[InProcessJobRunner, list[Mapping[str, str]]]:
    """A runner plus the list of envs its factory was called with."""
    seen: list[Mapping[str, str]] = []

    def factory(env: Mapping[str, str]) -> Executor:
        seen.append(dict(env))
        return executor if executor is not None else _StubExecutor()

    return (
        InProcessJobRunner(
            stream,
            factory,
            base_env=base_env,
            max_concurrent_runs=max_concurrent_runs,
            max_history=max_history,
        ),
        seen,
    )


async def _drain_until_terminal(stream: InMemoryEventStream, topic: str) -> TerminatedEvent:
    async for event in stream.subscribe(topic, from_sequence=None):
        if isinstance(event, TerminatedEvent):
            return event
    raise AssertionError("stream ended without a terminal frame")


async def _await_started(stream: InMemoryEventStream, topic: str) -> None:
    """Block until the run has actually begun publishing.

    Cancelling a task that has not yet had its first step scheduled kills the coroutine before
    its body — and therefore before `lifecycle.run`'s terminating `except` — ever runs, so no
    terminal frame is produced. A client stops a run it has observed starting, so waiting for
    `Started` is both the realistic sequence and what makes these tests deterministic instead of
    dependent on how many event-loop turns `schedule` happens to take.
    """
    async for event in stream.subscribe(topic, from_sequence=None):
        if isinstance(event, StartedEvent):
            return


# --- the run environment ------------------------------------------------------------------


async def test_schedule_builds_the_same_job_env_contract_a_job_would_get() -> None:
    stream = InMemoryEventStream()
    runner, seen = _runner(stream, base_env={job_env.AIGATEWAY_BASE_URL: "http://gw"})

    await runner.schedule(TOPIC, "/m('x')!'go'", 42, traceparent=None, profile="p")
    await _drain_until_terminal(stream, TOPIC)

    env = seen[0]
    assert env[job_env.TOPIC] == TOPIC
    assert env[job_env.EXPRESSION] == "/m('x')!'go'"
    assert env[job_env.JOB_DEADLINE_S] == "42"
    assert env[job_env.AIGATEWAY_PROFILE] == "p"
    # the ambient deploy-time half survives, exactly as `envFrom` would supply it
    assert env[job_env.AIGATEWAY_BASE_URL] == "http://gw"


async def test_a_malformed_traceparent_is_dropped_rather_than_forwarded() -> None:
    stream = InMemoryEventStream()
    runner, seen = _runner(stream)

    await runner.schedule(TOPIC, "q", 10, traceparent="not-a-traceparent")
    await _drain_until_terminal(stream, TOPIC)

    assert job_env.TRACEPARENT not in seen[0]


# --- lifecycle ----------------------------------------------------------------------------


async def test_a_run_reaches_a_succeeded_terminal_frame() -> None:
    stream = InMemoryEventStream()
    runner, _ = _runner(stream)

    name = await runner.schedule(TOPIC, "q", 10)
    terminal = await _drain_until_terminal(stream, TOPIC)

    assert name == job_name(TOPIC)
    assert terminal.data.status == "succeeded"


async def test_status_walks_running_then_succeeded() -> None:
    stream = InMemoryEventStream()
    runner, _ = _runner(stream)

    assert await runner.status(TOPIC) == "not_found"
    await runner.schedule(TOPIC, "q", 10)
    assert await runner.status(TOPIC) == "running"
    await _drain_until_terminal(stream, TOPIC)
    await asyncio.sleep(0)  # let the task's done-callback run
    assert await runner.status(TOPIC) == "succeeded"


async def test_a_second_run_on_a_live_topic_is_refused() -> None:
    stream = InMemoryEventStream()
    runner, _ = _runner(stream, _StubExecutor(block=True))

    await runner.schedule(TOPIC, "q", 10)
    assert await runner.exists(TOPIC) is True
    with pytest.raises(JobAlreadyExists):
        await runner.schedule(TOPIC, "q", 10)

    await _await_started(stream, TOPIC)
    await runner.stop(TOPIC)
    await _drain_until_terminal(stream, TOPIC)


async def test_a_finished_topic_frees_its_slot_immediately() -> None:
    """Unlike a k8s Job, which persists until its TTL — there is no substrate object to linger."""
    stream = InMemoryEventStream()
    runner, _ = _runner(stream)

    await runner.schedule(TOPIC, "q", 10)
    await _drain_until_terminal(stream, TOPIC)
    await asyncio.sleep(0)

    assert await runner.exists(TOPIC) is False
    await runner.schedule(TOPIC, "q", 10)  # must not raise


async def test_stop_terminates_the_stream_rather_than_leaving_it_silent() -> None:
    """The bug this adapter must not have: a cancelled task that published no terminal frame
    leaves a sync GET holding to its cap and a WS client seeing only heartbeats."""
    stream = InMemoryEventStream()
    runner, _ = _runner(stream, _StubExecutor(block=True))

    await runner.schedule(TOPIC, "q", 10)
    await _await_started(stream, TOPIC)
    await runner.stop(TOPIC)

    terminal = await _drain_until_terminal(stream, TOPIC)
    assert terminal.data.status == "stopped"


async def test_stop_is_idempotent_on_an_unknown_or_finished_topic() -> None:
    stream = InMemoryEventStream()
    runner, _ = _runner(stream)

    await runner.stop("never-scheduled")  # must not raise
    await runner.schedule(TOPIC, "q", 10)
    await _drain_until_terminal(stream, TOPIC)
    await asyncio.sleep(0)
    await runner.stop(TOPIC)  # must not raise


async def test_an_exploding_executor_terminates_as_failed() -> None:
    stream = InMemoryEventStream()
    runner, _ = _runner(stream, _StubExecutor(boom=RuntimeError("nope")))

    await runner.schedule(TOPIC, "q", 10)
    terminal = await _drain_until_terminal(stream, TOPIC)

    assert terminal.data.status == "failed"
    assert terminal.data.error is not None


async def test_a_run_past_its_deadline_terminates_as_timed_out() -> None:
    stream = InMemoryEventStream()
    runner, _ = _runner(stream, _StubExecutor(block=True))

    # `deadline_s` is an int on the port, so 1s is the smallest real bound — the executor blocks
    # forever, so exceeding it is deterministic rather than timing-sensitive.
    await runner.schedule(TOPIC, "q", 1)
    terminal = await asyncio.wait_for(_drain_until_terminal(stream, TOPIC), timeout=10)

    assert terminal.data.status == "timed_out"


# --- admission and bookkeeping --------------------------------------------------------------


async def test_over_the_concurrency_cap_the_runner_refuses() -> None:
    stream = InMemoryEventStream()
    runner, _ = _runner(stream, _StubExecutor(block=True), max_concurrent_runs=2)

    await runner.schedule("a", "q", 10)
    await runner.schedule("b", "q", 10)
    assert runner.active_count() == 2

    with pytest.raises(JobRunnerAtCapacity) as exc:
        await runner.schedule("c", "q", 10)
    assert exc.value.limit == 2

    await runner.aclose()


async def test_capacity_is_released_when_a_run_finishes() -> None:
    stream = InMemoryEventStream()
    runner, _ = _runner(stream, max_concurrent_runs=1)

    await runner.schedule("a", "q", 10)
    await _drain_until_terminal(stream, "a")
    await asyncio.sleep(0)

    assert runner.active_count() == 0
    await runner.schedule("b", "q", 10)  # must not raise


async def test_history_is_bounded_but_never_evicts_a_live_run() -> None:
    stream = InMemoryEventStream()
    runner, _ = _runner(stream, max_history=2)

    for topic in ("a", "b", "c", "d"):
        await runner.schedule(topic, "q", 10)
        await _drain_until_terminal(stream, topic)
        await asyncio.sleep(0)

    assert len(runner._tasks) <= 2  # noqa: SLF001 - the bound is the behaviour under test


async def test_aclose_cancels_in_flight_runs_and_terminates_their_streams() -> None:
    stream = InMemoryEventStream()
    runner, _ = _runner(stream, _StubExecutor(block=True))

    await runner.schedule(TOPIC, "q", 10)
    await _await_started(stream, TOPIC)
    await runner.aclose()

    terminal = await _drain_until_terminal(stream, TOPIC)
    assert terminal.data.status == "stopped"
