"""Canonical grades are consumable before subsequent grading work starts."""

import asyncio
import json

import pytest
from test_spine_scored import BoardError, _aggregate, _envelope, _grading, _Hook, _path, _selected


def test_first_result_does_not_wait_for_or_start_second_grade() -> None:
    async def run() -> None:
        hook = _Hook()
        path = _path(hook)
        stream = path.iter_case_results(
            json.dumps([_envelope(1, _grading(1)), _envelope(2, _grading(2))]),
            selected_cases=_selected(1, 2),
            grading_material=lambda _: (5, -3),
        )
        first = await anext(stream)
        assert first.case_id == 1
        assert first.grade is not None and first.grade.score == 0.5
        assert [request.case_id for request in hook.requests] == [1]
        second = await anext(stream)
        assert second.case_id == 2
        assert [request.case_id for request in hook.requests] == [1, 2]
        assert [result async for result in stream] == []

    asyncio.run(run())


def test_closing_incremental_results_does_not_grade_remaining_cases() -> None:
    async def run() -> None:
        hook = _Hook()
        stream = _path(hook).iter_case_results(
            json.dumps([_envelope(1, _grading(1)), _envelope(2, _grading(2))]),
            selected_cases=_selected(1, 2),
            grading_material=lambda _: (5, -3),
        )
        await anext(stream)
        await stream.aclose()
        assert [request.case_id for request in hook.requests] == [1]

    asyncio.run(run())


def test_bad_later_row_is_rejected_before_any_grading() -> None:
    async def run() -> None:
        hook = _Hook()
        stream = _path(hook).iter_case_results(
            json.dumps([_envelope(1, _grading(1)), _envelope(3, _grading(3))]),
            selected_cases=_selected(1, 2),
            grading_material=lambda _: (5, -3),
        )
        with pytest.raises(BoardError):
            await anext(stream)
        assert hook.requests == []

    asyncio.run(run())


def test_failed_case_is_yielded_without_calling_grader() -> None:
    async def run() -> None:
        hook = _Hook()
        results = [
            result
            async for result in _path(hook).iter_case_results(
                json.dumps([_envelope(1, _grading(1))]),
                selected_cases=_selected(1),
                grading_material=lambda _: None,
            )
        ]
        assert len(results) == 1
        assert results[0].status == "failed"
        assert results[0].grade is not None and results[0].grade.score is None
        assert results[0].failures[0].code == "missing_rubric_asset"
        assert hook.requests == []

    asyncio.run(run())


def test_omitted_case_stays_finalizers_responsibility() -> None:
    async def run() -> None:
        hook = _Hook()
        path = _path(hook, missing_row_result=lambda *_: None)
        assert [
            result
            async for result in path.iter_case_results(
                "[]", selected_cases=_selected(1), grading_material=lambda _: (5, -3)
            )
        ] == []
        assert hook.requests == []

    asyncio.run(run())


def test_final_aggregation_uses_incremental_results_without_regrading() -> None:
    hook = _Hook()
    result = _aggregate(
        _path(hook),
        [_envelope(1, _grading(1)), _envelope(2, _grading(2))],
        _selected(1, 2),
    )
    assert result["score"] == 0.5
    assert [case["case_id"] for case in result["cases"]] == [1, 2]
    assert [request.case_id for request in hook.requests] == [1, 2]
