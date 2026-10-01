"""Shared endpoint implementations own activity independently of route installation."""

import asyncio

import pytest

from screamingface_engine.activity.observer import ActivityObserver
from screamingface_engine.activity_kinds import ActivityKind
from screamingface_engine.benchmarks import grading_endpoints, phases
from screamingface_engine.observations import ModelCall, RunObservations
from url4.peer.server import Request


@pytest.mark.parametrize("factory", ["aggregate", "case_grade", "attempt_records"])
def test_shared_endpoint_emits_without_an_installation_wrapper(monkeypatch, factory):
    records = []
    monkeypatch.setattr(
        phases,
        "current_log_sink",
        lambda: lambda body, attributes, **kw: records.append(attributes),
    )
    if factory == "aggregate":
        handler = grading_endpoints.aggregate_endpoint(
            label="example", available_case_count=1, aggregate=lambda rows, count: {"score": 1}
        )
        context, intent, kind = "[]", "aggregate:1", "aggregation"
    else:
        builder = getattr(grading_endpoints, f"{factory}_endpoint")
        handler = builder(label="example", item_name="record", bind=lambda case, rows: {"score": 1})
        context = "[{}]" if factory == "case_grade" else '{"attempt_1": {}}'
        intent, kind = "1", "grading"
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
async def test_decorator_covers_awaited_work_and_preserves_parentage(monkeypatch):
    records = []

    def emit(body, attributes=None, **kwargs):
        records.append(attributes)

    monkeypatch.setattr(phases, "current_log_sink", lambda: emit)
    error = ValueError("private")
    run = RunObservations((ActivityObserver,))

    @phases.observe_phase(ActivityKind.ANSWERING)
    async def answer():
        async with ModelCall("writer", emit):
            await asyncio.sleep(0)
            raise error

    with run.bind(), pytest.raises(ValueError) as caught:
        await answer()
    await run.aclose()
    assert caught.value is error
    start, model_start, model_end, end = records
    assert model_start["sf.activity.parent_id"] == start["sf.activity.id"]
    assert model_end["sf.activity.state"] == end["sf.activity.state"] == "failed"
    assert "private" not in str(records)


def test_decorator_observes_shared_vocabulary_without_registration(monkeypatch):
    records = []
    monkeypatch.setattr(
        phases,
        "current_log_sink",
        lambda: lambda body, attributes, **kw: records.append(attributes),
    )

    @phases.observe_phase(ActivityKind.GRADING)
    def check():
        return "checked"

    with RunObservations((ActivityObserver,)).bind():
        assert check() == "checked"
    assert [record["sf.activity.state"] for record in records] == ["started", "completed"]
