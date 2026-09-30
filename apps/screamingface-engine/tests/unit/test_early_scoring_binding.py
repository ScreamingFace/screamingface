"""An execution-owned grade is reused, never recalculated for the final result."""

import json

import pytest
from test_shared_grading_aggregation import _envelope, _grading, _Hook, _path, _selected

from screamingface_engine.benchmarks.aggregation import CandidateScore
from screamingface_engine.benchmarks.shared_grading.incremental import Scoring


@pytest.mark.asyncio
async def test_early_grades_retain_position_and_are_not_regraded():
    hook = _Hook()
    scoring = Scoring(
        _path(hook),
        "board",
        "v1",
        _selected(1, 2),
        lambda _: (5, -3),
        lambda cases: CandidateScore(score=0.5, metrics={}),
    )
    first = await scoring.grade_row(json.dumps(_envelope(1, _grading(1))), 0)
    assert [r.case_id for r in hook.requests] == [1]
    second = await scoring.grade_row(json.dumps(_envelope(2, _grading(2))), 1)
    result = await scoring.finish(json.dumps([first, second]))
    assert result["score"] == 0.5
    assert [c["case_id"] for c in result["cases"]] == [1, 2]
    assert [r.case_id for r in hook.requests] == [1, 2]


@pytest.mark.asyncio
async def test_early_transport_refuses_foreign_results():
    hook = _Hook()
    scoring = Scoring(
        _path(hook),
        "board",
        "v1",
        _selected(1),
        lambda _: (5, -3),
        lambda cases: CandidateScore(score=0.5, metrics={}),
    )
    row = json.loads(await scoring.grade_row(json.dumps(_envelope(1, _grading(1))), 0))
    row["revision"] = "other"
    with pytest.raises(ValueError):
        await scoring.finish(json.dumps([row]))
    assert len(hook.requests) == 1


@pytest.mark.asyncio
async def test_collected_failure_preserves_batch_result_and_selected_position():
    hook = _Hook()
    scoring = Scoring(
        _path(hook),
        "board",
        "v1",
        _selected(1, 2),
        lambda _: (5, -3),
        lambda cases: CandidateScore(score=0.5, metrics={}),
    )
    raw = _envelope(1, _grading(1))
    failed = {"error": {"code": "rate_limited", "message": "unavailable", "permanent": False}}
    first = await scoring.grade_row(json.dumps(raw), 0)
    result = await scoring.finish(json.dumps([first, failed]))
    assert len(hook.requests) == 1
    baseline = Scoring(
        _path(_Hook()),
        "board",
        "v1",
        _selected(1, 2),
        lambda _: (5, -3),
        lambda cases: CandidateScore(score=0.5, metrics={}),
    ).aggregate(json.dumps([raw, failed]))
    assert result == baseline


@pytest.mark.asyncio
@pytest.mark.parametrize("row", [None, "null", {}, {"error": {"kind": "CaseFinalizationError"}}])
async def test_invalid_or_corrupt_grade_is_not_a_missing_case(row):
    hook = _Hook()
    scoring = Scoring(
        _path(hook),
        "board",
        "v1",
        _selected(1),
        lambda _: (5, -3),
        lambda cases: CandidateScore(score=0.5, metrics={}),
    )
    with pytest.raises(ValueError):
        await scoring.finish(json.dumps([row]))
    assert hook.requests == []
