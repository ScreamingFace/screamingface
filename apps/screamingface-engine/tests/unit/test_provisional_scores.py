"""Provisional snapshots observe canonical grades without controlling execution."""

import asyncio
import json

import pytest
from test_graded_result_transport import _result
from test_ifeval_incremental_proof import _assets

from screamingface_engine.activity.observer import ActivityObserver
from screamingface_engine.benchmarks.aggregation import CandidateScore
from screamingface_engine.benchmarks.definition import link_candidate
from screamingface_engine.benchmarks.ifeval.definition import IFEVAL
from screamingface_engine.benchmarks.ifeval.runtime import install
from screamingface_engine.benchmarks.progress import completed_case
from screamingface_engine.observations import RunObservations
from screamingface_engine.world.candidate_adapter import install_candidate_invocation
from url4.dag import run as execute
from url4.observe import Log
from url4.peer.server import Url4Node


def test_snapshots_are_cumulative_private_and_deduplicated(monkeypatch):
    logs = []
    monkeypatch.setattr(
        "screamingface_engine.benchmarks.progress.current_log_sink",
        lambda: lambda body, attrs: logs.append(dict(attrs)),
    )
    run = RunObservations((ActivityObserver,))

    def scorer(cases):
        return CandidateScore(score=0.0, metrics={})

    result = _result()
    with run.bind():
        completed_case("board", "v1", result, scorer)
        completed_case("board", "v1", result, scorer)
    assert len(logs) == 1
    assert logs[0]["sf.progress.score"] == 0.0
    assert logs[0]["sf.progress.completed"] == 1
    assert logs[0]["sf.progress.graded"] == 1
    assert "input" not in json.dumps(logs)


def test_observer_failure_does_not_change_execution(monkeypatch):
    def broken(*args):
        raise ValueError("observer failure")

    monkeypatch.setattr("screamingface_engine.benchmarks.progress.current_log_sink", lambda: broken)
    run = RunObservations((ActivityObserver,))
    with run.bind():
        completed_case(
            "board", "v1", _result(), lambda cases: CandidateScore(score=1.0, metrics={})
        )
    assert run.fault_reported


@pytest.mark.asyncio
async def test_real_expression_emits_score_while_second_answer_is_blocked(tmp_path):
    _assets(tmp_path)
    node = Url4Node("test")
    install(node, tmp_path)
    install_candidate_invocation(node)
    waiting, release = asyncio.Event(), asyncio.Event()
    events = []

    class Observer:
        def on_event(self, event):
            if isinstance(event, Log) and event.attributes.get("sf.progress.schema"):
                events.append(dict(event.attributes))

    async def answer(request):
        if "(2)" in request.context:
            waiting.set()
            await release.wait()
        return "Fresh tea"

    node.endpoint("/proof")(answer)
    run = RunObservations((ActivityObserver,))
    with run.bind():
        task = asyncio.create_task(
            execute(
                link_candidate("/proof($input)!answer", IFEVAL.protocol(2)),
                io=node,
                observer=Observer(),
            )
        )
        try:
            await asyncio.wait_for(waiting.wait(), 5)
            assert events[0]["sf.progress.score"] == 1.0
            assert events[0]["sf.progress.graded"] == 1
            assert not task.done()
        finally:
            release.set()
            await asyncio.wait_for(task, 5)
            await run.aclose()


def test_coalesced_snapshot_recovers_all_cases_without_double_counting(monkeypatch):
    from screamingface_engine.activity.progress import Progress

    now = [0.0]
    monkeypatch.setattr("screamingface_engine.activity.progress.time.monotonic", lambda: now[0])
    state, logs = Progress(), []

    def scorer(cases):
        return CandidateScore(score=len(cases) / 3, metrics={})

    def emit(body, attributes=None, *, severity="INFO"):
        logs.append(dict(attributes or {}))

    for case_id in (1, 2):
        state.observe(
            "board", "v1", _result().model_copy(update={"case_id": case_id}), scorer, emit
        )
    assert len(logs) == 1
    now[0] = 1.0
    state.observe("board", "v1", _result().model_copy(update={"case_id": 3}), scorer, emit)
    assert logs[-1]["sf.progress.completed"] == 3
    assert logs[-1]["sf.progress.score"] == 1.0


@pytest.mark.asyncio
async def test_disabled_and_closed_observers_do_not_score(monkeypatch):
    def forbidden(*args):
        pytest.fail("disabled observation must not calculate provisional scores")

    monkeypatch.setattr(
        "screamingface_engine.benchmarks.progress.current_log_sink", lambda: forbidden
    )
    run = RunObservations((lambda: ActivityObserver(enabled=False),))
    with run.bind():
        completed_case("board", "v1", _result(), forbidden)
    await run.aclose()
    with run.bind():
        completed_case("board", "v1", _result(), forbidden)
