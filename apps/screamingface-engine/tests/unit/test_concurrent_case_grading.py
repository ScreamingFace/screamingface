"""The marking room marks several Cases at once, and nothing it publishes moves.

FEATURE (OME-1527, R4): a judged Benchmark's grade hook waits on a judge call per Case;
marking one Case at a time made a gdpval-sized run wait on ~4,500 judge calls in a row.
These tests pin what concurrency must not change: the bound, the order, the failure
ladder, and which exception leaves the aggregate.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Mapping, Sequence
from typing import Any

import pytest
from test_shared_grading_aggregation import _envelope, _grading, _Hook, _mean, _path, _selected

from screamingface_engine.benchmarks.aggregation import finalize_candidate_result
from screamingface_engine.benchmarks.contract import CaseResult
from screamingface_engine.benchmarks.shared_grading import benchmark_aggregation
from screamingface_engine.benchmarks.shared_grading.benchmark_aggregation import (
    CASE_GRADING_CONCURRENCY,
    BenchmarkAggregation,
    CaseGradeOutcome,
    GradeRequest,
)
from screamingface_engine.benchmarks.shared_grading.mean_scorer import mean_scorer

_SCORED = CaseGradeOutcome(
    score=0.5, metrics={"judged": 2, "expected": 2, "invalid_replies": 0}, checks=[]
)
#: WHY a timeout on every wait: serial marking deadlocks these tests (Case 1 waits on a
#: later Case that never starts), so a regression fails in seconds instead of hanging.
_WAIT_S: float = 5.0


def _marking_room(grade: Any) -> BenchmarkAggregation:
    """The shared marking room as a judged Benchmark binds it: several Cases at once."""

    return _path(_Hook(), grade_case=grade, case_grading_concurrency=CASE_GRADING_CONCURRENCY)


def _rows(case_ids: Sequence[int]) -> list[dict[str, object]]:
    """One collected row per Case, in selected order."""

    return [_envelope(case_id, _grading(case_id)) for case_id in case_ids]


async def _aggregate(
    path: BenchmarkAggregation, rows: Sequence[Mapping[str, Any]], case_ids: Sequence[int]
) -> dict[str, Any]:
    """Run the final aggregate the way the plugin lane's judged handler awaits it."""

    return await path.aggregate_async(
        json.dumps(rows),
        benchmark_id="test-benchmark",
        benchmark_revision="rev",
        selected_cases=_selected(*case_ids),
        grading_material=lambda case_id: (5, -3),
        scorer=mean_scorer(_mean),
    )


@pytest.mark.asyncio
async def test_cases_are_marked_side_by_side_but_never_beyond_the_bound() -> None:
    """WHY the bound: each Case in flight is a judge call queued at the gateway."""

    in_flight: int = 0
    peak: int = 0

    async def grade(request: GradeRequest) -> CaseGradeOutcome:
        """Count the Cases inside the hook at once."""

        nonlocal in_flight, peak
        in_flight += 1
        peak = max(peak, in_flight)
        # WHY the yields: a stand-in for a judge round trip; they hand the loop to the
        # other Cases. They prove overlap, not any wall-clock speedup.
        for _ in range(3):
            await asyncio.sleep(0)
        in_flight -= 1
        return _SCORED

    case_ids: tuple[int, ...] = tuple(range(1, 3 * CASE_GRADING_CONCURRENCY + 1))
    result: dict[str, Any] = await _aggregate(_marking_room(grade), _rows(case_ids), case_ids)
    assert 1 < peak <= CASE_GRADING_CONCURRENCY
    assert [case["case_id"] for case in result["cases"]] == list(case_ids)


@pytest.mark.asyncio
async def test_later_cases_finishing_first_move_neither_results_nor_progress(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """INVARIANT: results and progress publishes follow the selected order, not finish order."""

    published: list[Any] = []
    finished: list[Any] = []
    case_3_done: asyncio.Event = asyncio.Event()
    monkeypatch.setattr(
        benchmark_aggregation,
        "completed_case",
        lambda benchmark, revision, result, scorer: published.append(result.case_id),
    )

    async def grade(request: GradeRequest) -> CaseGradeOutcome:
        """Case 1 finishes only after Case 3 has: finish order 2, 3, 1."""

        if request.case_id == 1:
            await asyncio.wait_for(case_3_done.wait(), _WAIT_S)
        finished.append(request.case_id)
        if request.case_id == 3:
            case_3_done.set()
        return _SCORED

    result: dict[str, Any] = await _aggregate(_marking_room(grade), _rows((1, 2, 3)), (1, 2, 3))
    assert finished == [2, 3, 1]
    assert [case["case_id"] for case in result["cases"]] == [1, 2, 3]
    assert published == [1, 2, 3]


@pytest.mark.asyncio
async def test_a_failing_case_publishes_exactly_what_serial_marking_publishes() -> None:
    """INVARIANT: the failure ladder is per Case; concurrency changes no failed Case's bytes."""

    async def grade(request: GradeRequest) -> CaseGradeOutcome:
        """Case 2's judge left a verdict out; the others score."""

        await asyncio.sleep(0)
        if request.case_id == 2:
            return CaseGradeOutcome(
                score=None,
                metrics={"judged": 1, "expected": 2, "invalid_replies": 0},
                checks=[],
                failure_code="incomplete_verdicts",
            )
        return _SCORED

    path: BenchmarkAggregation = _marking_room(grade)
    # Case 4 has no row at all: the missing-case rung, never the hook.
    rows: list[dict[str, object]] = _rows((1, 2, 3))
    concurrent: dict[str, Any] = await _aggregate(path, rows, (1, 2, 3, 4))
    serial: list[CaseResult] = [
        result
        async for result in path.iter_case_results(
            json.dumps(rows),
            selected_cases=_selected(1, 2, 3, 4),
            grading_material=lambda case_id: (5, -3),
        )
    ]
    expected: dict[str, Any] = finalize_candidate_result(
        benchmark_id="test-benchmark",
        benchmark_revision="rev",
        selected_cases=_selected(1, 2, 3, 4),
        cases=serial,
        scorer=mean_scorer(_mean),
    ).as_payload()
    assert concurrent == expected
    codes: list[Any] = [[f["code"] for f in case["failures"]] for case in concurrent["cases"]]
    assert codes == [[], ["incomplete_verdicts"], [], ["missing_case_row"]]


@pytest.mark.asyncio
async def test_the_first_raising_case_in_selected_order_leaves_and_no_grading_outlives_it() -> None:
    """INVARIANT: the same exception as serial marking leaves; in-flight siblings are cancelled."""

    assert CASE_GRADING_CONCURRENCY >= 4  # Cases 1-4 must all be in flight at once
    cancelled: list[Any] = []

    async def grade(request: GradeRequest) -> CaseGradeOutcome:
        """Case 3 raises first in time, Case 2 first in selected order, Case 4 never ends."""

        try:
            if request.case_id == 3:
                raise RuntimeError("case 3 broke")
            await asyncio.sleep(0)
            if request.case_id == 2:
                raise RuntimeError("case 2 broke")
            if request.case_id == 4:
                await asyncio.Event().wait()
            return _SCORED
        except asyncio.CancelledError:
            cancelled.append(request.case_id)
            raise

    with pytest.raises(RuntimeError, match="case 2 broke"):
        await _aggregate(_marking_room(grade), _rows((1, 2, 3, 4)), (1, 2, 3, 4))
    assert cancelled == [4]
