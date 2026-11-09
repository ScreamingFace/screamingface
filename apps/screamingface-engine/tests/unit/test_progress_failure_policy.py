"""OME-1642: the live progress score picks the same Cases as the finalized result.

INVARIANT: for a `withhold` Benchmark the in-run (provisional) score counts a failed Case as 0
over every observed Case, so the last progress score equals the finalized score; under
`coverage_declare` it stays the graded-only mean. One helper (`policy_cases`) makes the choice
for both, so the two cannot drift.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Sequence
from typing import Any

import pytest
from test_shared_grading_aggregation import _envelope, _grading, _Hook, _path, _selected
from test_withhold_reduction import _failed, _finalize, _scored

from screamingface_engine.activity.observer import ActivityObserver
from screamingface_engine.activity.progress import Progress
from screamingface_engine.benchmarks.aggregation import CandidateScore
from screamingface_engine.benchmarks.contract import CaseResult
from screamingface_engine.benchmarks.definition import FailurePolicy
from screamingface_engine.benchmarks.progress import completed_case, grading_progress
from screamingface_engine.observations import RunObservations


def _mean_over_received(cases: Sequence[CaseResult]) -> CandidateScore:
    """The scorer contract: divide by every Case received, a Case with no grade counting 0."""

    total = sum(
        case.grade.score
        for case in cases
        if case.grade is not None and case.grade.score is not None
    )
    return CandidateScore(score=total / len(cases), metrics={})


# 1.0, 0.5 and one failed Case: withhold 0.5 (over 3), coverage_declare 0.75 (over 2).
_CASES = [_scored(1, 1.0), _scored(2, 0.5), _failed(3)]
_EXPECTED = {"withhold": 0.5, "coverage_declare": 0.75}


@pytest.mark.parametrize("policy", ["withhold", "coverage_declare"])
def test_the_final_progress_score_equals_the_finalized_score(policy: FailurePolicy) -> None:
    logs: list[dict[str, Any]] = []
    progress = Progress()
    for case in _CASES:
        progress.observe(
            "board",
            "v1",
            case,
            _mean_over_received,
            lambda body, attributes=None, *, severity="INFO": logs.append(dict(attributes or {})),
            failure_policy=policy,
        )
    progress.flush(
        "board",
        "v1",
        _mean_over_received,
        lambda body, attributes=None, *, severity="INFO": logs.append(dict(attributes or {})),
        failure_policy=policy,
    )

    finalized = _finalize(policy, _CASES, scorer=_mean_over_received)

    assert logs[-1]["sf.progress.score"] == finalized.score == _EXPECTED[policy]
    assert logs[-1]["sf.progress.completed"] == 3
    # INVARIANT: the graded count is a count of graded Cases under both policies.
    assert logs[-1]["sf.progress.graded"] == 2


@pytest.mark.parametrize("policy", ["withhold", "coverage_declare"])
def test_no_graded_case_publishes_no_progress_score_under_both_policies(
    policy: FailurePolicy,
) -> None:
    logs: list[dict[str, Any]] = []
    progress = Progress()
    progress.observe(
        "board",
        "v1",
        _failed(1),
        lambda cases: pytest.fail("the scorer must not run"),
        lambda body, attributes=None, *, severity="INFO": logs.append(dict(attributes or {})),
        failure_policy=policy,
    )

    assert logs[-1]["sf.progress.score"] is None
    assert logs[-1]["sf.progress.graded"] == 0


@pytest.mark.parametrize("policy", ["withhold", "coverage_declare"])
def test_the_policy_reaches_progress_through_completed_case(
    monkeypatch: pytest.MonkeyPatch, policy: FailurePolicy
) -> None:
    logs: list[dict[str, Any]] = []
    monkeypatch.setattr(
        "screamingface_engine.benchmarks.progress.current_log_sink",
        lambda: lambda body, attrs: logs.append(dict(attrs)),
    )
    run = RunObservations((ActivityObserver,))
    try:
        with run.bind():
            with grading_progress("board", "v1", _mean_over_received, failure_policy=policy):
                for case in _CASES:
                    completed_case("board", "v1", case, _mean_over_received, failure_policy=policy)
    finally:
        asyncio.run(run.aclose())

    assert logs[-1]["sf.progress.score"] == _EXPECTED[policy]


@pytest.mark.parametrize("policy", ["withhold", "coverage_declare"])
def test_the_aggregation_publishes_a_final_progress_score_equal_to_its_result(
    monkeypatch: pytest.MonkeyPatch, policy: FailurePolicy
) -> None:
    logs: list[dict[str, Any]] = []
    monkeypatch.setattr(
        "screamingface_engine.benchmarks.progress.current_log_sink",
        lambda: lambda body, attrs: logs.append(dict(attrs)),
    )
    run = RunObservations((ActivityObserver,))
    try:
        with run.bind():
            result = _path(_Hook(), failure_policy=policy).aggregate(
                json.dumps(
                    [
                        _envelope(1, _grading(1)),
                        {"error": {"kind": "ResolutionError", "message": "the call 429'd"}},
                    ]
                ),
                benchmark_id="board",
                benchmark_revision="v1",
                selected_cases=_selected(1, 2),
                grading_material=lambda case_id: (5, -3),
                scorer=_mean_over_received,
            )
    finally:
        asyncio.run(run.aclose())

    assert result["score"] is not None
    assert logs[-1]["sf.progress.score"] == result["score"]
