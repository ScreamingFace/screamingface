"""OME-807's public failure policy through the shared Benchmark seams."""

from __future__ import annotations

from collections.abc import Sequence

import pytest
from pydantic import ValidationError

from screamingface_engine.benchmarks.aggregation import (
    CandidateScore,
    SelectedCase,
    finalize_candidate_result,
    refused_case_result,
)
from screamingface_engine.benchmarks.contract import (
    CandidateResult,
    CaseGrade,
    CaseResult,
    Failure,
    encode_candidate_invocation,
)
from screamingface_engine.benchmarks.evaluation import candidate_answer


def _grade(score: float | None = 1.0) -> CaseGrade:
    return CaseGrade(method="test", score=score, metrics={}, checks=[])


def _scored(case_id: int, score: float = 1.0) -> CaseResult:
    return CaseResult(
        status="scored",
        case_id=case_id,
        input=f"input {case_id}",
        output=f"output {case_id}",
        finish_reason="stop",
        refusal=None,
        grade=_grade(score),
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


def _selected(*case_ids: int) -> list[SelectedCase]:
    return [
        SelectedCase(case_id=case_id, input=f"input {case_id}", metadata={}) for case_id in case_ids
    ]


def test_refusal_is_normal_benchmark_input_and_can_carry_a_numeric_grade() -> None:
    exact = "I cannot provide those instructions."
    answer = candidate_answer(encode_candidate_invocation("", "content_filter", exact))
    assert answer.refusal is not None
    case = refused_case_result(
        selected_case=SelectedCase(case_id=1, input="question", metadata={}),
        refusal=answer.refusal,
        finish_reason=answer.finish_reason,
        grade=_grade(0.0),
    )

    assert answer.text == exact
    assert answer.output is None
    assert answer.refusal == exact
    assert case.status == "refused"
    assert case.refusal == exact
    assert case.output is None
    assert case.grade is not None and case.grade.score == 0.0
    assert case.failures == []


def test_refusal_retains_a_missing_grade_when_later_grading_fails() -> None:
    failure = Failure(
        stage="grading",
        code="judge_unavailable",
        message="the Judge was unavailable",
        retryable=True,
        case_id=1,
        metadata={},
    )
    case = refused_case_result(
        selected_case=SelectedCase(case_id=1, input="question", metadata={}),
        refusal="I cannot answer.",
        grade=_grade(None),
        failures=[failure],
    )

    assert case.status == "refused"
    assert case.grade is not None and case.grade.score is None
    assert case.failures == [failure]


def test_partial_candidate_scores_only_gradeable_cases_and_declares_coverage() -> None:
    observed: list[int | str] = []

    def scorer(cases: Sequence[CaseResult]) -> CandidateScore:
        observed.extend(case.case_id for case in cases)
        return CandidateScore(score=0.25, metrics={"pass_rate": 0.25})

    result = finalize_candidate_result(
        benchmark_id="benchmark",
        benchmark_revision="revision",
        selected_cases=_selected(1, 2, 3),
        cases=[_scored(1), _failed(2), _scored(3, 0.0)],
        scorer=scorer,
    )

    assert observed == [1, 3]
    assert result.score == 0.25
    assert result.coverage == 0.6667
    assert result.metrics == {"pass_rate": 0.25}
    assert [case.case_id for case in result.cases] == [1, 2, 3]


def test_no_gradeable_cases_publish_the_explicit_zero_coverage_shape() -> None:
    result = finalize_candidate_result(
        benchmark_id="benchmark",
        benchmark_revision="revision",
        selected_cases=_selected(1),
        cases=[_failed(1)],
        scorer=lambda _: pytest.fail("the scorer must not run"),
    )

    assert result.score is None
    assert result.coverage == 0.0
    assert result.metrics == {}


def test_candidate_contract_rejects_derived_coverage_drift_and_metrics_coverage() -> None:
    values = {
        "benchmark_id": "benchmark",
        "benchmark_revision": "revision",
        "case_count": 2,
        "score": 1.0,
        "coverage": 0.5,
        "metrics": {"pass_rate": 1.0},
        "cases": [_scored(1), _failed(2)],
        "failures": [],
    }
    assert CandidateResult(**values).coverage == 0.5

    with pytest.raises(ValidationError, match="coverage"):
        CandidateResult(**{**values, "coverage": 1.0})
    with pytest.raises(ValidationError, match="metrics.coverage"):
        CandidateResult(**{**values, "metrics": {"coverage": 0.5}})


def test_a_grading_failure_row_propagates_the_original_code_and_retryability() -> None:
    # OME-993 chain pin: the case-evaluation seam re-raises a collected upstream
    # failure, url4 collects it WITH code+permanent, and this fold must publish that
    # original cause — code, message, retryable — on the grading-stage Failure.
    from screamingface_engine.benchmarks.aggregation import grading_failure_case_result

    answer = candidate_answer(encode_candidate_invocation("the answer", "stop", None))
    case = grading_failure_case_result(
        selected_case=SelectedCase(case_id=4, input="question", metadata={}),
        candidate=answer,
        error={
            "kind": "ResolutionError",
            "message": "Criterion evaluation 2 failed upstream: aigateway request "
            "failed with status 429",
            "code": "aigateway_http_429",
            "permanent": False,
        },
        method="rubric",
        default_code="draco_grading_failed",
        default_message="the DRACO grader could not grade this Case",
    )

    (failure,) = case.failures
    assert failure.stage == "grading"
    assert failure.code == "aigateway_http_429"
    assert failure.retryable is True
    assert "429" in failure.message
    assert failure.metadata["error_kind"] == "ResolutionError"
    assert case.output == "the answer"
