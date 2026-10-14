"""The marking room holds only the Cases near the clerk, not every Case it has marked (OME-1607).

Measured on a `draco-3pass` replay: the aggregate started one task per Case up front and kept
the list to the end. Each finished task kept its context, and each context kept what the Case's
grading had put there — inspect creates a Transcript lazily in the task that first asks for one,
and that Transcript keeps every judge `ModelEvent` with the full report prompt. 100 Cases × ~74
judge calls stayed resident, about 35 KB per call, until the child ran out of memory.

These tests model inspect's behavior with a ContextVar a Case sets inside its own task, and pin:
the memory a marked Case left in its context is released once the clerk hands the Case over; a
slow Case cannot let later Cases run unboundedly ahead; each Case still runs in its own copy of
the caller's context.
"""

from __future__ import annotations

import asyncio
import contextvars
import gc
import json
import weakref
from collections.abc import Sequence
from typing import Any

import pytest
from test_shared_grading_aggregation import _envelope, _grading, _Hook, _mean, _path, _selected

from screamingface_engine.benchmarks.shared_grading.benchmark_aggregation import (
    CASE_GRADING_CONCURRENCY,
    MARKING_WINDOW_FACTOR,
    BenchmarkAggregation,
    CaseGradeOutcome,
    GradeRequest,
)
from screamingface_engine.benchmarks.shared_grading.mean_scorer import mean_scorer

_SCORED = CaseGradeOutcome(
    score=0.5, metrics={"judged": 2, "expected": 2, "invalid_replies": 0}, checks=[]
)
_WINDOW = MARKING_WINDOW_FACTOR * CASE_GRADING_CONCURRENCY
_WAIT_S: float = 5.0

#: What inspect does: a value created lazily in the task that first asks, kept by its context.
_CASE_TRANSCRIPT: contextvars.ContextVar[Any] = contextvars.ContextVar("case_transcript")
_CALLER_SCOPE: contextvars.ContextVar[str] = contextvars.ContextVar("caller_scope", default="")


class _Transcript:
    """A stand-in for inspect's Transcript: one per Case, holding that Case's judge calls."""

    def __init__(self, case_id: int) -> None:
        self.case_id = case_id
        self.events = [bytearray(1024) for _ in range(8)]


def _marking_room(grade: Any) -> BenchmarkAggregation:
    return _path(_Hook(), grade_case=grade, case_grading_concurrency=CASE_GRADING_CONCURRENCY)


def _rows(case_ids: Sequence[int]) -> list[dict[str, object]]:
    return [_envelope(case_id, _grading(case_id)) for case_id in case_ids]


async def _aggregate(path: BenchmarkAggregation, case_ids: Sequence[int]) -> dict[str, Any]:
    return await path.aggregate_async(
        json.dumps(_rows(case_ids)),
        benchmark_id="test-benchmark",
        benchmark_revision="rev",
        selected_cases=_selected(*case_ids),
        grading_material=lambda case_id: (5, -3),
        scorer=mean_scorer(_mean),
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("cases", [3 * _WINDOW, 100])
async def test_a_marked_case_s_context_is_released_once_it_is_handed_over(cases: int) -> None:
    """The peak number of Case contexts alive does not grow with the number of Cases."""

    alive: list[weakref.ref[_Transcript]] = []
    peak = 0

    async def grade(request: GradeRequest) -> CaseGradeOutcome:
        nonlocal peak
        transcript = _Transcript(int(request.case_id))
        _CASE_TRANSCRIPT.set(transcript)  # kept by this Case's task context, as inspect does
        alive.append(weakref.ref(transcript))
        del transcript
        gc.collect()
        peak = max(peak, sum(1 for ref in alive if ref() is not None))
        await asyncio.sleep(0)
        return _SCORED

    case_ids = tuple(range(1, cases + 1))
    result = await _aggregate(_marking_room(grade), case_ids)
    assert [case["case_id"] for case in result["cases"]] == list(case_ids)
    # Bounded by the window ahead of the clerk (+1: the Case being handed over), for any N.
    assert peak <= _WINDOW + 1


@pytest.mark.asyncio
async def test_a_slow_case_does_not_let_later_cases_run_unboundedly_ahead() -> None:
    """While Case 1 is still being judged, no Case beyond the window starts."""

    started_while_first_pending: list[int] = []
    first_done = False

    async def grade(request: GradeRequest) -> CaseGradeOutcome:
        nonlocal first_done
        if not first_done:
            started_while_first_pending.append(int(request.case_id))
        if request.case_id == 1:
            for _ in range(500):  # a slow judge: the other seats finish many Cases meanwhile
                await asyncio.sleep(0)
            first_done = True
        return _SCORED

    case_ids = tuple(range(1, 101))
    result = await asyncio.wait_for(_aggregate(_marking_room(grade), case_ids), _WAIT_S)
    assert len(result["cases"]) == 100
    assert max(started_while_first_pending) <= _WINDOW


@pytest.mark.asyncio
async def test_each_case_runs_in_its_own_copy_of_the_caller_s_context() -> None:
    """What a Case sets stays in its own task; what the caller set reaches every Case."""

    leaked: list[int] = []
    seen_scope: set[str] = set()

    async def grade(request: GradeRequest) -> CaseGradeOutcome:
        if _CASE_TRANSCRIPT.get(None) is not None:
            leaked.append(int(request.case_id))
        seen_scope.add(_CALLER_SCOPE.get())
        _CASE_TRANSCRIPT.set(_Transcript(int(request.case_id)))
        await asyncio.sleep(0)
        return _SCORED

    token = _CALLER_SCOPE.set("aggregate-request")
    try:
        await _aggregate(_marking_room(grade), tuple(range(1, 3 * _WINDOW + 1)))
    finally:
        _CALLER_SCOPE.reset(token)
    assert leaked == []
    assert seen_scope == {"aggregate-request"}
