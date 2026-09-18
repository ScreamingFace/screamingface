"""Stage attribution uses explicit execution context, never a sibling's identity."""

import asyncio

import pytest

from screamingface_engine.activity.observer import ActivityObserver
from screamingface_engine.activity_kinds import ActivityKind
from screamingface_engine.benchmarks.case_context import case_scope
from screamingface_engine.benchmarks.stages import observe_stage
from screamingface_engine.observations import ModelCall, RunObservations


@pytest.mark.asyncio
async def test_interleaved_stages_and_models_keep_their_own_case(monkeypatch):
    events = []

    def emit(body, attributes=None, **kwargs):
        events.append(dict(attributes or {}))

    monkeypatch.setattr("screamingface_engine.benchmarks.stages.current_log_sink", lambda: emit)

    @observe_stage(ActivityKind.GRADING)
    async def grade():
        async with ModelCall("judge", emit):
            await asyncio.sleep(0)

    async def execute(case):
        with case_scope(case):
            await grade()

    run = RunObservations((ActivityObserver,))
    with run.bind():
        await asyncio.gather(execute(42), execute("007"))
    await run.aclose()
    stages = {
        r["sf.activity.id"]: r["sf.activity.case_id"]
        for r in events
        if r["sf.activity.kind"] == "grading"
    }
    assert set(stages.values()) == {42, "007"}
    for record in events:
        if record["sf.activity.kind"] == "model_call":
            assert record["sf.activity.case_id"] == stages[record["sf.activity.parent_id"]]


@pytest.mark.parametrize("case", [None, "private question with spaces"])
def test_unknown_or_unsafe_case_does_not_suppress_stage(monkeypatch, case):
    events = []

    def emit(body, attributes=None, **kwargs):
        events.append(dict(attributes or {}))

    monkeypatch.setattr("screamingface_engine.benchmarks.stages.current_log_sink", lambda: emit)
    with RunObservations((ActivityObserver,)).bind(), case_scope(case):
        assert observe_stage(ActivityKind.GRADING)(lambda: "ok")() == "ok"
    assert [r["sf.activity.state"] for r in events] == ["started", "completed"]
    assert all("sf.activity.case_id" not in r for r in events)


@pytest.mark.asyncio
async def test_candidate_answering_stage_starts_inside_decoded_case_scope(monkeypatch):
    from screamingface_engine.benchmarks import candidate_adapter
    from screamingface_engine.benchmarks.candidate_adapter import install_candidate_invocation
    from screamingface_engine.benchmarks.definition import candidate
    from url4 import render
    from url4.peer.server import Url4Node

    events = []
    inputs = []

    def emit(body, attributes=None, **kwargs):
        events.append(dict(attributes or {}))

    async def evaluate(node, expression, input_text, **kwargs):
        inputs.append(input_text)
        return "answer"

    monkeypatch.setattr("screamingface_engine.benchmarks.stages.current_log_sink", lambda: emit)
    monkeypatch.setattr(candidate_adapter, "evaluate_candidate_recipe", evaluate)
    node = Url4Node()
    install_candidate_invocation(node)
    run = RunObservations((ActivityObserver,))
    try:
        with run.bind():
            await node.evaluate(
                render(candidate("question", case_id="007", web_search=False)),
                env={"candidate": "recipe"},
            )
        assert inputs == ["question"]
        assert [r["sf.activity.state"] for r in events] == ["started", "completed"]
        assert all(r["sf.activity.case_id"] == "007" for r in events)
    finally:
        await run.aclose()
        await node.aclose()
