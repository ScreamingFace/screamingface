"""Shared endpoint implementations own activity independently of route installation."""

import asyncio
import json
from collections.abc import Coroutine
from typing import Any, cast

import pytest

from screamingface_engine.activity.observer import ActivityObserver
from screamingface_engine.activity_kinds import ActivityKind
from screamingface_engine.benchmarks import grading_endpoints, phases
from screamingface_engine.benchmarks.case_evaluation import aggregate_code, case_evaluation_code
from screamingface_engine.benchmarks.contract import encode_candidate_invocation
from screamingface_engine.observations import ModelCall, RunObservations
from url4 import CodeCall, CodeInput
from url4.peer.server import Request


def _code_call(**values: str) -> CodeCall:
    inputs = tuple(
        CodeInput(position, name, value, 0.0)
        for position, (name, value) in enumerate(values.items(), start=1)
    )
    return CodeCall("/arbitrary", {}, inputs)


async def _rows_score(rows: str, count: int) -> dict[str, int]:
    return {"score": 1}


@pytest.mark.parametrize("factory", ["aggregate", "case_grade", "case_evaluation"])
def test_shared_endpoint_emits_without_an_installation_wrapper(monkeypatch, factory):
    records = []
    monkeypatch.setattr(
        phases,
        "current_log_sink",
        lambda: lambda body, attributes, **kw: records.append(attributes),
    )
    # WHY (spec 2026-10-20 R1): the aggregate and the per-Case record are code mounts that read
    # named sources; the shared Case-grade endpoint is unchanged.
    with RunObservations((ActivityObserver,)).bind():
        if factory == "aggregate":
            handler = aggregate_code(label="example", available_case_count=1, aggregate=_rows_score)
            awaited = cast(
                Coroutine[Any, Any, str], handler(_code_call(evaluations="[]", selected="1"))
            )
            result = asyncio.run(awaited)
            assert result == '{"score":1}'
            kind = "aggregation"
        elif factory == "case_grade":
            handler = grading_endpoints.case_grade_endpoint(
                label="example", item_name="record", bind=lambda case, rows: {"score": 1}
            )
            request = Request(path="/arbitrary", context="[{}]", intent="1", params={})
            assert handler(request) == '{"score":1}'
            kind = "grading"
        else:
            handler = case_evaluation_code(
                label="example",
                check=lambda case_id, invocation, others: {},
                build_case_grade=lambda case, rows: {"score": 1},
                observe_grading=True,
            )
            invocation = encode_candidate_invocation("answer", "stop", None)
            row = json.loads(cast(str, handler(_code_call(case='{"id": 1}', attempt_1=invocation))))
            assert row["grading"] == [{"score": 1}]
            kind = "grading"
    # INVARIANT: neither the handler nor its registration is decorated by the caller.
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
