"""A run whose record refuses its run summary fails BEFORE its terminal frame (OME-1988, review 1).

FEATURE: a detached Run (OME-1837), E5 P2 spec §4.3, R3 and R7. STORY: as a reader of the
leaderboard, a Candidate whose run summary has a malformed figure reads `failed` everywhere, even
when its outcome is late and the driver settles it from its terminal frame.

INVARIANT: one verdict. The run's executor fails the run with `run_summary_invalid` (permanent)
before it builds its result, so url4's lifecycle publishes `Terminated(failed)`, and the frame,
the outcome, the R7 settle, the record and the log lines all say `failed`.

Each run here is the real `Url4Executor`, through a real producer, running a node that makes one
priced model call. The run summary is the run's own closing log (`executor._closing_logs`,
published with no span); the `summary` fixture makes it state the given attributes. A node's own
`ctx.log` is never the summary, whatever it carries (review round 2).
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Callable, Mapping, Sequence
from decimal import Decimal
from pathlib import Path
from typing import Any, cast

import pytest
import pytest_asyncio
from run_driver_support import SETTINGS, DriverRunner, drivers
from run_registry_support import (
    DATABASES,
    Registry,
    open_registry,
    postgres_server,  # noqa: F401  (a fixture the Postgres parameter requests)
    start_spec,
)
from test_inprocess_outcomes import _published

from screamingface_engine.adapters.inprocess import InProcessJobRunner
from screamingface_engine.adapters.memory import (
    InMemoryCandidateOutcomeStream,
    InMemoryEventStream,
)
from screamingface_engine.candidate_outcomes import CandidateOutcome
from screamingface_engine.runner import main
from screamingface_engine.runner.cache_counters import RunCacheCounters
from screamingface_engine.runner.executor import Url4Executor
from screamingface_engine.runner.operation_capture import OperationCapturingExecutor
from screamingface_engine.runner.summary import RunSummary
from screamingface_engine.runs.records import owner_key
from url4.io.static import StaticIOLayer
from url4.streaming.interfaces import ExecStep, Executor, TraceContext
from url4.streaming.protocol import OutboundFrame, TerminatedEvent

pytestmark = pytest.mark.asyncio

TOPIC = "t-summary-refused"
URL4 = "q"
PREFIX = f"runs/run_{'a' * 32}/0"
TRACEPARENT = "00-0af7651916cd43dd8448eb211c80319c-b7ad6b7169203331-01"
ALICE = owner_key("alice@example.org")
# WHY the literals: the code is what the registry stores and the Client raises with.
CODE = "run_summary_invalid"
UNPRICED = "cache.saved_cost.unpriced_hits"
# The run's one model call: what a refused run still spent (review round 2, finding 5).
COST = Decimal("0.0042")

WELL_FORMED: dict[str, Any] = {
    "cache.hits": 1,
    "cache.misses": 0,
    "cache.bypasses": 0,
    "cache.saved_cost.reported_hits": 1,
    "cache.saved_cost.archive_hits": 0,
    UNPRICED: 0,
    "cache.saved_cost_usd": "0.012345",
    "capture.status": "partial",
    "capture.frozen_copy_id": "copy-1",
    "capture.replay": "copy-0",
    "capture.partial.local": 1,
}
MALFORMED = {**WELL_FORMED, UNPRICED: -1}
FIGURES = (
    "cache_hits",
    "cache_unpriced_hits",
    "cache_saved_cost_usd",
    "cache_saved_cost_archive_usd",
    "frozen_copy_id",
    "capture_status",
    "capture_replay",
    "capture_partial_reasons",
)
# What a refused record says for them (review round 2, finding 3): no figure is certified, and
# the two the Client's `_RunOutcome` always carries keep their defaults.
REFUSED_FIGURES = {**dict.fromkeys(FIGURES), "cache_hits": 0, "capture_partial_reasons": []}


@pytest.fixture
def summary(monkeypatch: pytest.MonkeyPatch) -> Callable[[Mapping[str, Any]], None]:
    """Make the run's own closing summary state the given attributes.

    WHY a patch of the run's cache counters: the line stays the real one (`_closing_logs`, no
    span, the root traceparent), and the run never writes a malformed figure itself.
    """

    def state(attributes: Mapping[str, Any]) -> None:
        monkeypatch.setattr(RunCacheCounters, "observed", property(lambda self: True))
        monkeypatch.setattr(RunCacheCounters, "attributes", lambda self: dict(attributes))

    return state


class _Node:
    """A url4 node that makes one priced model call, logs each line it was given with its own
    `ctx.log`, then answers."""

    deps: dict[str, object] = {}

    def __init__(self, logs: Sequence[Mapping[str, Any]]) -> None:
        self._logs = logs

    async def resolve(self, inputs: object, ctx: Any) -> str:
        ctx.report_usage(provider="test", model="m", input_tokens=3, output_tokens=2, cost_usd=COST)
        for attributes in self._logs:
            ctx.log("INFO", "a node's log", attributes=attributes)
        return "ANSWER"


class _Run(Executor):
    """The real `Url4Executor`, running `_Node` under whatever url4 the run names."""

    def __init__(self, *node_logs: Mapping[str, Any]) -> None:
        self._executor = Url4Executor(StaticIOLayer())
        self._node = _Node(node_logs)

    def execute(self, url4: str, *, trace: TraceContext | None = None) -> AsyncIterator[ExecStep]:
        return self._executor.execute(cast("str", self._node), trace=trace)

    def last_summary(self) -> RunSummary | None:
        return self._executor.last_summary()


async def _frames(stream: InMemoryEventStream, topic: str) -> list[OutboundFrame]:
    frames: list[OutboundFrame] = []
    async for frame in stream.subscribe(topic):
        frames.append(frame)
        if isinstance(frame, TerminatedEvent):
            return frames
    return frames


async def _local(
    *node_logs: Mapping[str, Any], prefix: str | None = PREFIX
) -> tuple[CandidateOutcome, list[OutboundFrame], _Run]:
    """One run on the in-process runner (local mode's producer): its outcome and its frames."""
    executor = _Run(*node_logs)
    stream = InMemoryEventStream()
    outcomes = InMemoryCandidateOutcomeStream()
    local = InProcessJobRunner(stream, lambda env: executor, outcomes=outcomes)
    await local.schedule(TOPIC, URL4, 60, traceparent=TRACEPARENT, result_prefix=prefix)
    outcome = (await _published(outcomes)).outcome
    return outcome, await _frames(stream, TOPIC), executor


def _terminal(frames: Sequence[OutboundFrame]) -> TerminatedEvent:
    terminal = frames[-1]
    assert isinstance(terminal, TerminatedEvent)
    return terminal


def _assert_refused(outcome: CandidateOutcome, frames: Sequence[OutboundFrame], name: str) -> None:
    """The frame, the outcome and the record all say `failed` with the one refusal."""
    message = f"SF Engine run summary {name} is invalid"
    error = _terminal(frames).data.error
    assert _terminal(frames).data.status == "failed"
    assert error is not None
    assert (error.code, error.message, error.permanent) == (CODE, message, True)
    # Refused before its result: no result frame. Finding 5: every call was made and paid for,
    # so the Candidate still states the run's exact cost.
    assert [frame.type for frame in frames if frame.type == "ai.url4.result"] == []
    assert (outcome.status, outcome.error_code, outcome.cost_usd) == ("failed", CODE, COST)
    record = outcome.record
    assert record is not None
    assert "result" not in record
    assert (record["error"]["code"], record["error"]["message"]) == (CODE, message)
    assert record["error"]["permanent"] is True


# --- The control ---------------------------------------------------------------------------------


async def test_a_well_formed_summary_succeeds_with_its_result_and_its_figures(
    summary: Callable[[Mapping[str, Any]], None],
) -> None:
    """The harness alone fails nothing: the figures the refused cases must not carry."""
    summary(WELL_FORMED)

    outcome, frames, _ = await _local()

    assert _terminal(frames).data.status == "succeeded"
    assert (outcome.status, outcome.error_code, outcome.cost_usd) == ("succeeded", None, COST)
    record = outcome.record
    assert record is not None
    assert record["result"]["size_bytes"] == len(b"ANSWER")
    assert {name: record[name] for name in FIGURES} == {
        "cache_hits": 1,
        "cache_unpriced_hits": 0,
        "cache_saved_cost_usd": "0.012345",
        "cache_saved_cost_archive_usd": None,
        "frozen_copy_id": "copy-1",
        "capture_status": "partial",
        "capture_replay": "copy-0",
        "capture_partial_reasons": ["local"],
    }


# --- R7: the frame says failed, so a settle from it does too --------------------------------------


@pytest_asyncio.fixture(params=DATABASES)
async def registry(request: pytest.FixtureRequest, tmp_path: Path) -> AsyncIterator[Registry]:
    async for opened in open_registry(request, tmp_path):
        yield opened


async def _run_the_start(start: Mapping[str, Any]) -> tuple[CandidateOutcome, TerminatedEvent]:
    """Run a start the driver sent on a local runner: its outcome, and its terminal frame."""
    outcomes = InMemoryCandidateOutcomeStream()
    local = InProcessJobRunner(InMemoryEventStream(), lambda env: _Run(), outcomes=outcomes)
    await local.schedule(
        start["topic"],
        start["url4"],
        60,
        traceparent=start["traceparent"],
        result_prefix=start["result_prefix"],
        exclusive=True,
    )
    outcome = (await _published(outcomes)).outcome
    frame = await local.last_frame(start["topic"])
    assert isinstance(frame, TerminatedEvent)
    return outcome, frame


async def test_r7_settles_a_refused_candidate_failed_and_its_late_outcome_agrees(
    registry: Registry, summary: Callable[[Mapping[str, Any]], None]
) -> None:
    """The finding: the refusal used to be decided after a `succeeded` terminal frame, so R7
    settled a Candidate whose outcome was late `succeeded`, and first-wins kept it."""
    summary(MALFORMED)
    run, _ = await registry.store.register(ALICE, start_spec("a"))
    runner = DriverRunner()
    driver = drivers(registry.store, runner, registry.clock)
    await driver.drive_once(run.id)
    topic = runner.starts[0]["topic"]
    # The driver never sees the outcome in time; it reads the run's terminal frame instead.
    late, frame = await _run_the_start(runner.starts[0])
    runner.frames[topic] = frame.model_copy(update={"time": registry.clock()})
    registry.clock.advance(seconds=SETTINGS.outcome_grace_s + 1)

    await driver.drive_once(run.id)
    settled = await registry.store.get(ALICE, run.id)
    await registry.store.settle(topic, late)
    filled = await registry.store.get(ALICE, run.id)

    assert settled is not None and filled is not None
    (first,) = settled.candidates
    assert (first.state, first.error_code, first.record) == ("failed", CODE, None)
    (candidate,) = filled.candidates
    # Finding 5: the late outcome fills the Candidate's cost with what the refused run spent.
    assert (candidate.state, candidate.error_code, candidate.cost_usd) == ("failed", CODE, COST)
    assert candidate.record is not None
    assert candidate.record["error"]["code"] == CODE
    assert "result" not in candidate.record


# --- Both producers ------------------------------------------------------------------------------


async def test_the_local_runner_ends_the_run_failed_and_says_so_in_every_line(
    caplog: pytest.LogCaptureFixture, summary: Callable[[Mapping[str, Any]], None]
) -> None:
    caplog.set_level(logging.INFO)
    summary(MALFORMED)

    outcome, frames, executor = await _local()

    _assert_refused(outcome, frames, UNPRICED)
    run_summary = executor.last_summary()
    assert run_summary is not None
    assert (run_summary.outcome, run_summary.error_code) == ("failed", CODE)
    messages = [record.getMessage() for record in caplog.records]
    terminated = [line for line in messages if line.startswith("run terminated")]
    assert len(terminated) == 1
    assert f"outcome=failed error={CODE}: " in terminated[0]
    refused = [
        record.getMessage()
        for record in caplog.records
        if record.levelno == logging.WARNING and "run summary refused" in record.getMessage()
    ]
    # Fix 2: one line, the topic and the attribute's name, never a figure's value.
    assert refused == [f"run summary refused topic={TOPIC} attribute='{UNPRICED}' code={CODE}"]


async def test_the_queue_child_ends_the_run_failed_and_says_so_in_every_line(
    caplog: pytest.LogCaptureFixture, summary: Callable[[Mapping[str, Any]], None]
) -> None:
    caplog.set_level(logging.INFO)
    summary(MALFORMED)
    stream = InMemoryEventStream()
    params = main.RunnerParams(
        topic=TOPIC, url4=URL4, nats_url="nats://unused", deadline_s=60.0, result_prefix=PREFIX
    )

    outcome = await main._run_and_log(  # noqa: SLF001
        OperationCapturingExecutor(_Run()), stream, params, TRACEPARENT
    )

    _assert_refused(outcome, await _frames(stream, TOPIC), UNPRICED)
    messages = [record.getMessage() for record in caplog.records]
    finished = [line for line in messages if line.startswith("run finished")]
    assert len(finished) == 1
    assert f"outcome=failed code={CODE}" in finished[0]


# --- The record and the rule ---------------------------------------------------------------------


async def test_a_malformed_closing_summary_refuses_the_run_and_its_record_states_no_figure(
    summary: Callable[[Mapping[str, Any]], None],
) -> None:
    """Round 1 fix 4, as round 2's finding 3 corrects it: the refused record certifies none of
    the summary's figures, though a node's well-formed log carries them all. The sticky rule
    (round 1 fix 5) is the fold's: `test_candidate_record_fail_closed.py`."""
    summary(MALFORMED)

    outcome, frames, _ = await _local(WELL_FORMED)

    _assert_refused(outcome, frames, UNPRICED)
    assert outcome.record is not None
    assert {name: outcome.record[name] for name in FIGURES} == REFUSED_FIGURES


async def test_a_nodes_log_is_no_run_summary_whatever_it_carries(
    caplog: pytest.LogCaptureFixture, summary: Callable[[Mapping[str, Any]], None]
) -> None:
    """Round 2, finding 1: url4 stamps every frame of a run with the root's `source`, so a node's
    `ctx.log` carrying `cache.hits` used to pass for the run summary, and a malformed one failed
    the run. Only the run's own closing log is the summary; here it is well formed."""
    caplog.set_level(logging.INFO)
    summary(WELL_FORMED)

    outcome, frames, _ = await _local({**MALFORMED, "capture.status": "maybe"})

    assert _terminal(frames).data.status == "succeeded"
    assert (outcome.status, outcome.error_code, outcome.cost_usd) == ("succeeded", None, COST)
    assert outcome.record is not None
    assert outcome.record["result"]["size_bytes"] == len(b"ANSWER")
    assert (outcome.record["cache_unpriced_hits"], outcome.record["capture_status"]) == (
        0,
        "partial",
    )
    assert not [record for record in caplog.records if record.levelno >= logging.WARNING]


async def test_a_nodes_malformed_log_alone_fails_nothing() -> None:
    """Finding 1, with no closing summary at all (the run observed no cache outcome): the
    node's line certifies no figure either."""
    outcome, frames, _ = await _local({**WELL_FORMED, "capture.status": "maybe"})

    assert _terminal(frames).data.status == "succeeded"
    assert (outcome.status, outcome.error_code) == ("succeeded", None)
    assert outcome.record is not None
    assert (outcome.record["cache_hits"], outcome.record["capture_status"]) == (0, None)


async def test_an_amount_with_a_huge_exponent_fails_the_run_instead_of_expanding_it(
    summary: Callable[[Mapping[str, Any]], None],
) -> None:
    """Fix 6: `1E+999999999` used to read as a finite amount, which `_amount` wrote out in
    fixed point, about 1 GB."""
    summary({**WELL_FORMED, "cache.saved_cost_usd": "1E+999999999"})

    outcome, frames, _ = await _local()

    _assert_refused(outcome, frames, "cache.saved_cost_usd")
    assert outcome.record is not None
    assert outcome.record["cache_saved_cost_usd"] is None


async def test_a_run_nobody_asked_a_record_of_is_not_refused(
    caplog: pytest.LogCaptureFixture, summary: Callable[[Mapping[str, Any]], None]
) -> None:
    """Only a driver-started run folds a record (§4.3), so only it is refused: every other run
    ends as it did."""
    summary(MALFORMED)

    outcome, frames, _ = await _local(prefix=None)

    assert _terminal(frames).data.status == "succeeded"
    assert (outcome.status, outcome.record) == ("succeeded", None)
    assert not [record for record in caplog.records if record.levelno >= logging.WARNING]
