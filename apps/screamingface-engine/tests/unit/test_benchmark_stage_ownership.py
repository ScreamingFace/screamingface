"""Shared endpoint implementations own activity independently of route installation."""

import asyncio

import pytest

from screamingface_engine.activity.observer import ActivityObserver
from screamingface_engine.benchmarks import evaluation, stages
from screamingface_engine.observations import ModelCall, RunObservations
from url4.peer.server import Request


@pytest.mark.parametrize("factory", ["aggregate", "case_evaluation", "attempt_records"])
def test_shared_endpoint_emits_without_an_installation_wrapper(monkeypatch, factory):
    records = []
    monkeypatch.setattr(
        stages,
        "current_log_sink",
        lambda: lambda body, attributes, **kw: records.append(attributes),
    )
    if factory == "aggregate":
        handler = evaluation.aggregate_endpoint(
            label="example", available_case_count=1, aggregate=lambda rows, count: {"score": 1}
        )
        context, intent, kind = "[]", "aggregate:1", "aggregation"
    else:
        builder = getattr(evaluation, f"{factory}_endpoint")
        handler = builder(label="example", item_name="record", bind=lambda case, rows: {"score": 1})
        context = "[{}]" if factory == "case_evaluation" else '{"attempt_1": {}}'
        intent, kind = "1", "grading_reduce"
    # INVARIANT: neither the handler nor its registration is decorated by the caller.
    with RunObservations((ActivityObserver,)).bind():
        assert handler(Request(path="/arbitrary", context=context, intent=intent, params={})) == (
            '{"score":1}'
        )
    assert [(r["sf.activity.kind"], r["sf.activity.state"]) for r in records] == [
        (kind, "started"),
        (kind, "completed"),
    ]


@pytest.mark.asyncio
async def test_explicit_scope_covers_awaited_work_and_preserves_parentage(monkeypatch):
    records = []

    def emit(body, attributes=None, **kwargs):
        records.append(attributes)

    monkeypatch.setattr(stages, "current_log_sink", lambda: emit)
    error = ValueError("private")
    run = RunObservations((ActivityObserver,))
    with run.bind(), pytest.raises(ValueError) as caught:
        async with stages.stage_scope(stages.BenchmarkStage.ANSWERING):
            async with ModelCall("writer", emit):
                await asyncio.sleep(0)
                raise error
    await run.aclose()
    assert caught.value is error
    start, model_start, model_end, end = records
    assert model_start["sf.activity.parent_id"] == start["sf.activity.id"]
    assert model_end["sf.activity.state"] == end["sf.activity.state"] == "failed"
    assert "private" not in str(records)
