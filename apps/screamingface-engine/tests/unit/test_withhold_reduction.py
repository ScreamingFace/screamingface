"""OME-1642 U2: the `withhold` failure policy reduces over EVERY selected Case.

INVARIANT: under `withhold` a Case with no numeric grade adds 0 to the headline and to every
Named Score column, and stays in the denominator; under `coverage_declare` the scorer sees only
the graded Cases, exactly as before. `scored_cases` and `correct` stay counts of graded Cases,
and coverage reads "graded / selected" under both policies.
"""

from __future__ import annotations

import json
from collections.abc import Sequence

import pytest
from test_shared_grading_aggregation import _envelope, _grading, _Hook, _path, _selected

from screamingface_engine.benchmarks.aggregation import (
    CandidateScore,
    Scorer,
    SelectedCase,
    finalize_candidate_result,
    refusal_case_result,
)
from screamingface_engine.benchmarks.contract import (
    CandidateResult,
    CaseGrade,
    CaseId,
    CaseResult,
    Failure,
)
from screamingface_engine.benchmarks.definition import FailurePolicy
from screamingface_engine.benchmarks.medxpert.aggregate import _accuracy as medxpert_accuracy
from screamingface_engine.benchmarks.shared_grading.incremental import Scoring
from screamingface_engine_inspect.single_shot import _accuracy


def _grade(score: float | None, scores: dict[str, float | None] | None = None) -> CaseGrade:
    return CaseGrade(method="test", score=score, metrics={}, checks=[], scores=scores or {})


def _scored(
    case_id: int, score: float, scores: dict[str, float | None] | None = None
) -> CaseResult:
    return CaseResult(
        status="scored",
        case_id=case_id,
        input=f"input {case_id}",
        output=f"output {case_id}",
        finish_reason="stop",
        refusal=None,
        grade=_grade(score, scores),
        failures=[],
        metadata={},
    )


def _failed(case_id: int) -> CaseResult:
    return CaseResult(
        status="failed",
        case_id=case_id,
        input=f"input {case_id}",
        output=None,
        finish_reason=None,
        refusal=None,
        grade=_grade(None),
        failures=[
            Failure(
                stage="grading",
                code="judge_unavailable",
                message="the Judge was unavailable",
                retryable=True,
                case_id=case_id,
                metadata={},
            )
        ],
        metadata={},
    )


def _selection(*case_ids: CaseId) -> list[SelectedCase]:
    return [
        SelectedCase(case_id=case_id, input=f"input {case_id}", metadata={}) for case_id in case_ids
    ]


def _finalize(
    policy: FailurePolicy,
    cases: Sequence[CaseResult],
    scorer: Scorer = _accuracy,
) -> CandidateResult:
    return finalize_candidate_result(
        benchmark_id="benchmark",
        benchmark_revision="revision",
        selected_cases=_selection(*(case.case_id for case in cases)),
        cases=cases,
        scorer=scorer,
        failure_policy=policy,
    )


def test_withhold_counts_a_failed_case_as_zero_over_every_selected_case() -> None:
    cases = [_scored(1, 1.0), _scored(2, 0.5), _scored(3, 0.0), _failed(4)]

    withheld = _finalize("withhold", cases)
    declared = _finalize("coverage_declare", cases)

    assert withheld.score == 0.375
    assert withheld.coverage == 0.75
    assert declared.score == 0.5
    assert declared.coverage == 0.75
    # INVARIANT: counts stay over the graded Cases under both policies.
    assert withheld.metrics["scored_cases"] == 3
    assert withheld.metrics["correct"] == 1
    assert withheld.metrics == declared.metrics
    assert [case.case_id for case in withheld.cases] == [1, 2, 3, 4]


def test_withhold_gives_every_named_score_column_the_same_denominator() -> None:
    cases = [
        _scored(1, 1.0, {"f1": 1.0, "exact": 1.0}),
        _scored(2, 0.5, {"f1": 0.5, "exact": 0.0}),
        _failed(3),
    ]

    withheld = _finalize("withhold", cases)
    declared = _finalize("coverage_declare", cases)

    assert withheld.score == 0.5
    assert withheld.scores == {"f1": 0.5, "exact": 0.3333}
    assert declared.score == 0.75
    assert declared.scores == {"f1": 0.75, "exact": 0.5}


def test_withhold_keeps_a_column_unknown_when_a_graded_case_cannot_fill_it() -> None:
    cases = [
        _scored(1, 1.0, {"f1": 1.0, "exact": 1.0}),
        _scored(2, 0.5, {"f1": 0.5, "exact": None}),
        _failed(3),
    ]

    result = _finalize("withhold", cases)

    # OME-1268 rule unchanged: an unfilled column is unknown, never a mean over fewer Cases.
    assert result.scores == {"f1": 0.5, "exact": None}


@pytest.mark.parametrize("policy", ["withhold", "coverage_declare"])
def test_no_graded_case_publishes_the_zero_coverage_shape_under_both_policies(
    policy: FailurePolicy,
) -> None:
    result = _finalize(
        policy,
        [_failed(1), _failed(2)],
        scorer=lambda _: pytest.fail("the scorer must not run"),
    )

    assert result.score is None
    assert result.coverage == 0.0
    assert result.metrics == {}
    assert result.scores == {}


def test_withhold_hands_the_scorer_every_selected_case() -> None:
    seen: dict[str, list[int | str]] = {}

    def scorer_for(policy: FailurePolicy) -> Scorer:
        def scorer(cases: Sequence[CaseResult]) -> CandidateScore:
            seen[policy] = [case.case_id for case in cases]
            return CandidateScore(score=0.5, metrics={})

        return scorer

    cases = [_scored(1, 1.0), _failed(2), _scored(3, 0.0)]
    _finalize("withhold", cases, scorer=scorer_for("withhold"))
    _finalize("coverage_declare", cases, scorer=scorer_for("coverage_declare"))

    assert seen == {"withhold": [1, 2, 3], "coverage_declare": [1, 3]}


def test_a_textless_content_filter_refusal_adds_zero_under_withhold() -> None:
    selected = _selection(1, 2)
    refused = refusal_case_result(
        selected_case=selected[1],
        refusal=None,
        finish_reason="content_filter",
        grade=_grade(0.0),
    )
    # A textless refusal is a failed Case whose grade score is dropped: not measured.
    assert refused.status == "failed"
    assert refused.grade == _grade(None)

    result = _finalize("withhold", [_scored(1, 1.0), refused])

    assert result.score == 0.5
    assert result.coverage == 0.5


def _scored_with_metrics(case_id: int, score: float, *, answered: bool) -> CaseResult:
    case = _scored(case_id, score)
    assert case.grade is not None
    return case.model_copy(
        update={"grade": case.grade.model_copy(update={"metrics": {"answered": answered}})}
    )


def test_medxpert_accuracy_counts_an_ungraded_case_as_zero() -> None:
    cases = [
        _scored_with_metrics(1, 1.0, answered=True),
        _scored_with_metrics(2, 0.0, answered=False),
        _failed(3),
        _failed(4),
    ]

    result = medxpert_accuracy(cases)

    assert result.score == 0.25
    assert result.metrics["scored_cases"] == 2
    assert result.metrics["correct"] == 1
    assert result.metrics["answered"] == 1
    assert result.metrics["answered_rate"] == 0.5


# --- the policy reaches the finalizer through every shared path ----------------------------


def _recording_scorer(seen: list[list[int | str]]) -> Scorer:
    def scorer(cases: Sequence[CaseResult]) -> CandidateScore:
        seen.append([case.case_id for case in cases])
        return CandidateScore(score=0.5, metrics={})

    return scorer


# A row the fan-out collected as a failure: Case 2 never gets a grade.
_COLLECTED_ERROR = {"error": {"kind": "ResolutionError", "message": "the call 429'd"}}


@pytest.mark.parametrize(
    ("policy", "scored_ids"), [("withhold", [1, 2]), ("coverage_declare", [1])]
)
def test_the_batch_path_hands_the_scorer_the_cases_the_aggregations_policy_counts(
    policy: FailurePolicy, scored_ids: list[int]
) -> None:
    seen: list[list[int | str]] = []

    result = _path(_Hook(), failure_policy=policy).aggregate(
        json.dumps([_envelope(1, _grading(1)), _COLLECTED_ERROR]),
        benchmark_id="benchmark",
        benchmark_revision="rev",
        selected_cases=_selected(1, 2),
        grading_material=lambda case_id: (5, -3),
        scorer=_recording_scorer(seen),
    )

    assert seen == [scored_ids]
    assert result["coverage"] == 0.5


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("policy", "scored_ids"), [("withhold", [1, 2]), ("coverage_declare", [1])]
)
async def test_the_incremental_path_hands_the_scorer_the_cases_the_aggregations_policy_counts(
    policy: FailurePolicy, scored_ids: list[int]
) -> None:
    seen: list[list[int | str]] = []
    scoring = Scoring(
        _path(_Hook(), failure_policy=policy),
        "board",
        "v1",
        _selected(1, 2),
        lambda _: (5, -3),
        _recording_scorer(seen),
    )

    first = await scoring.grade_row(json.dumps(_envelope(1, _grading(1))), 0)
    result = await scoring.finish(json.dumps([first, _COLLECTED_ERROR]))

    assert seen == [scored_ids]
    assert result["coverage"] == 0.5
