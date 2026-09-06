"""The generic finalizer owns cross-Benchmark score publication policy."""

from __future__ import annotations

from collections.abc import Sequence

import pytest

from screamingface_engine.benchmarks.aggregation import (
    CandidateScore,
    SelectedCase,
    failed_case_result,
    finalize_candidate_result,
    public_error,
    refusal_case_result,
    scored_case_result,
)
from screamingface_engine.benchmarks.contract import CaseGrade, CaseResult, Failure


def _scored(case_id: int) -> CaseResult:
    return CaseResult(
        status="scored",
        case_id=case_id,
        input=f"input {case_id}",
        output=f"output {case_id}",
        finish_reason="stop",
        refusal=None,
        grade=CaseGrade(method="test", score=1.0, metrics={}, checks=[]),
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
        grade=None,
        failures=[
            Failure(
                stage="candidate",
                code="candidate_failed",
                message="Candidate execution failed",
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


def test_all_scored_cases_are_passed_to_the_scorer_in_stable_order() -> None:
    observed: list[int | str] = []

    def scorer(cases: Sequence[CaseResult]) -> CandidateScore:
        observed.extend(case.case_id for case in cases)
        return CandidateScore(score=0.75, metrics={"pass_rate": 0.5})

    result = finalize_candidate_result(
        benchmark_id="benchmark",
        benchmark_revision="revision",
        selected_cases=_selected(2, 1),
        cases=[_scored(2), _scored(1)],
        scorer=scorer,
    )

    assert observed == [2, 1]
    assert [case.case_id for case in result.cases] == [2, 1]
    assert result.score == 0.75
    assert result.coverage == 1.0


def test_a_failed_case_is_excluded_while_the_gradeable_subset_is_scored() -> None:
    observed: list[int | str] = []

    def scorer(cases: Sequence[CaseResult]) -> CandidateScore:
        observed.extend(case.case_id for case in cases)
        return CandidateScore(score=1.0, metrics={"pass_rate": 1.0})

    result = finalize_candidate_result(
        benchmark_id="benchmark",
        benchmark_revision="revision",
        selected_cases=_selected(1, 2),
        cases=[_scored(1), _failed(2)],
        scorer=scorer,
    )

    assert observed == [1]
    assert result.score == 1.0
    assert result.coverage == 0.5


def test_a_candidate_level_failure_does_not_erase_gradeable_case_truth() -> None:
    failure = Failure(
        stage="aggregation",
        code="asset_unavailable",
        message="the scorer asset is unavailable",
        retryable=False,
        case_id=None,
        metadata={},
    )

    result = finalize_candidate_result(
        benchmark_id="benchmark",
        benchmark_revision="revision",
        selected_cases=_selected(1),
        cases=[_scored(1)],
        failures=[failure],
        scorer=lambda _: CandidateScore(score=1.0, metrics={"pass_rate": 1.0}),
    )

    assert result.score == 1.0
    assert result.coverage == 1.0
    assert result.failures == [failure]


def test_duplicate_case_identity_is_rejected_before_scoring() -> None:
    with pytest.raises(ValueError, match="duplicate case_id"):
        finalize_candidate_result(
            benchmark_id="benchmark",
            benchmark_revision="revision",
            selected_cases=_selected(1),
            cases=[_scored(1), _scored(1)],
            scorer=lambda _: pytest.fail("scorer must not run"),
        )


def test_a_missing_selected_case_is_retained_and_lowers_coverage() -> None:
    result = finalize_candidate_result(
        benchmark_id="benchmark",
        benchmark_revision="revision",
        selected_cases=[
            SelectedCase(case_id=1, input="input 1", metadata={}),
            SelectedCase(case_id=2, input="input 2", metadata={"split": "test"}),
        ],
        cases=[_scored(1)],
        scorer=lambda cases: CandidateScore(score=float(len(cases)), metrics={}),
    )

    assert [case.case_id for case in result.cases] == [1, 2]
    assert result.score == 1.0
    assert result.coverage == 0.5
    missing = result.cases[1]
    assert missing.status == "failed"
    assert missing.input == "input 2"
    assert missing.metadata == {"split": "test"}
    assert [failure.code for failure in missing.failures] == ["case_result_missing"]


def test_scorer_cannot_reintroduce_generic_metrics_coverage() -> None:
    with pytest.raises(ValueError, match="metrics.coverage"):
        finalize_candidate_result(
            benchmark_id="benchmark",
            benchmark_revision="revision",
            selected_cases=_selected(1),
            cases=[_scored(1)],
            scorer=lambda _: CandidateScore(score=1.0, metrics={"coverage": 1.0}),
        )


def test_finalizer_rejects_boolean_and_non_finite_scores() -> None:
    for score in (True, float("nan"), float("inf")):
        with pytest.raises(ValueError, match="finite number"):
            finalize_candidate_result(
                benchmark_id="benchmark",
                benchmark_revision="revision",
                selected_cases=_selected(1),
                cases=[_scored(1)],
                scorer=lambda _, score=score: CandidateScore(
                    score=score,  # type: ignore[arg-type]
                    metrics={"pass_rate": 1.0},
                ),
            )


def test_shared_case_constructors_own_the_public_case_envelope() -> None:
    selected = SelectedCase(case_id=7, input="question", metadata={"split": "test"})
    scored = scored_case_result(
        selected_case=selected,
        output="answer",
        finish_reason="stop",
        grade=CaseGrade(method="test", score=1.0, metrics={}, checks=[]),
    )
    failure = Failure(
        stage="grading",
        code="judge_failed",
        message="Judge failed",
        retryable=True,
        case_id=7,
        metadata={},
    )
    failed = failed_case_result(
        selected_case=selected,
        failures=[failure],
        output="answer",
        finish_reason="stop",
    )

    assert scored.status == "scored"
    assert scored.input == failed.input == "question"
    assert scored.metadata == failed.metadata == {"split": "test"}
    assert failed.status == "failed"
    assert failed.output == "answer"
    assert failed.failures == [failure]


def test_finalizer_does_not_coerce_a_string_score() -> None:
    with pytest.raises(ValueError):
        finalize_candidate_result(
            benchmark_id="benchmark",
            benchmark_revision="revision",
            selected_cases=_selected(1),
            cases=[_scored(1)],
            scorer=lambda _: CandidateScore(
                score="1",  # type: ignore[arg-type]
                metrics={"pass_rate": 1.0},
            ),
        )


def test_refusal_case_constructor_preserves_exact_text_and_normal_grade() -> None:
    # INVARIANT (OME-1037): a refusal the Benchmark graded is an ordinary SCORED
    # Case carrying the exact refusal text — no more `refused` case status.
    exact = "I can’t provide that dosage."
    case = refusal_case_result(
        selected_case=SelectedCase(case_id="health-7", input="Recommend a dosage.", metadata={}),
        refusal=exact,
        finish_reason="content_filter",
        grade=CaseGrade(method="test", score=0.0, metrics={}, checks=[]),
    )

    assert case.status == "scored"
    assert case.refusal == exact
    assert case.output is None
    assert case.grade is not None and case.grade.score == 0.0
    assert case.failures == []


def test_public_error_keeps_safe_diagnostics_and_rejects_internal_detail() -> None:
    safe = public_error(
        {
            "kind": "ResolutionError",
            "code": "provider_error",
            "message": "the provider was unavailable",
            "permanent": True,
        },
        default_code="case_execution_failed",
        default_message="Candidate Case execution failed",
    )
    assert safe.code == "provider_error"
    assert safe.message == "the provider was unavailable"
    assert safe.kind == "ResolutionError"
    assert safe.retryable is False

    unsafe = public_error(
        {
            "kind": "RuntimeError",
            "message": ('Traceback (most recent call last): File "/private/tmp/runner.py", line 4'),
        },
        default_code="case_execution_failed",
        default_message="Candidate Case execution failed",
    )
    assert unsafe.message == "Candidate Case execution failed"
    assert "/private/tmp" not in unsafe.message

    credentials = public_error(
        {
            "message": (
                r"request failed at C:\runner\job.py with password=hunter2 "
                "and access key AKIAIOSFODNN7EXAMPLE"
            )
        },
        default_code="case_execution_failed",
        default_message="Candidate Case execution failed",
    )
    assert credentials.message == "Candidate Case execution failed"


@pytest.mark.parametrize(
    "message",
    (
        "provider rejected OPENAI_API_KEY=abcdefgh",
        "request failed with client_secret=hunter2",
        "authentication used session_cookie=abcdef",
    ),
)
def test_public_error_rejects_compound_credential_assignments(message: str) -> None:
    diagnostic = public_error(
        {"message": message},
        default_code="case_execution_failed",
        default_message="Candidate Case execution failed",
    )

    assert diagnostic.message == "Candidate Case execution failed"


@pytest.mark.parametrize(
    "message",
    (
        "failed reading /etc/screamingface/private.json",
        r"failed reading \\server\share\private.json",
        "failed reading ./secrets/provider.json",
        "failed reading ../private/provider.json",
    ),
)
def test_public_error_rejects_common_filesystem_paths(message: str) -> None:
    diagnostic = public_error(
        {"message": message},
        default_code="case_execution_failed",
        default_message="Candidate Case execution failed",
    )

    assert diagnostic.message == "Candidate Case execution failed"
