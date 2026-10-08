"""OME-1458 — a Case asked N times: a Check is met if any Attempt met it.

FEATURE: a Benchmark that declares N Attempts asks each Case N times; each Attempt is graded by
the Benchmark's own Grading, then the shared marking room folds the N grades per Check.

STORY: "What is 6 times 7?" — Attempt 1 answers 41, Attempt 2 answers 42. The Case shows 42,
scores 1.0, and keeps both Attempts. For ARC-AGI-2's two-grid tasks, Attempt 1 getting grid A
and Attempt 2 getting grid B scores 1.0, the number the ARC Prize's own scorer computes.

INVARIANT: a Check graded neither 0 nor 1 never gets a guessed fold: the Case fails by name.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Sequence
from typing import Any

import pytest
from test_shared_grading_aggregation import MESSAGES, _decode, _selected

from screamingface_engine.benchmarks.aggregation import CandidateScore
from screamingface_engine.benchmarks.contract import (
    CaseGrade,
    CaseResult,
    Check,
    Failure,
    OperationOutput,
    encode_candidate_invocation,
)
from screamingface_engine.benchmarks.graded_answer import (
    CASE_ATTEMPTS_SCHEMA,
    graded_answer_payload,
)
from screamingface_engine.benchmarks.shared_grading.attempt_fold import (
    ATTEMPT_GRADE_NOT_PASS_FAIL,
    MET_BY_ATTEMPTS_KEY,
    fold_case_attempts,
)
from screamingface_engine.benchmarks.shared_grading.benchmark_aggregation import (
    BenchmarkAggregation,
    CaseGradeOutcome,
    CaseGradeReader,
    GradeRequest,
)

# --- building one Attempt's Case Result -------------------------------------------------


def _check(check_id: str, met: bool | None, *, score: float | None = None) -> Check:
    """One Check: met / missed, or (``met=None``) a partial ``score``."""

    return Check(
        type="exact_match",
        id=check_id,
        label=f"grid {check_id}",
        outcome=None if met is None else ("MET" if met else "UNMET"),
        score=score if met is None else (1.0 if met else 0.0),
        evidence=[],
        metadata={},
    )


def _attempt(output: str, checks: Sequence[Check], **overrides: Any) -> CaseResult:
    """One scored Attempt of Case 1: its answer and its own per-Check grade."""

    met: int = sum(1 for check in checks if check.outcome == "MET")
    values: dict[str, Any] = {
        "status": "scored",
        "case_id": 1,
        "input": "What is 6 times 7?",
        "output": output,
        "finish_reason": "stop",
        "refusal": None,
        "grade": CaseGrade(
            method="inspect_scorer",
            score=met / len(checks) if checks else 0.0,
            metrics={},
            checks=list(checks),
        ),
        "failures": [],
        "metadata": {},
    }
    values.update(overrides)
    return CaseResult(**values)


def _failed_attempt() -> CaseResult:
    """An Attempt whose Candidate gave no usable answer: no grade, one failure."""

    return CaseResult(
        status="failed",
        case_id=1,
        input="What is 6 times 7?",
        output=None,
        finish_reason=None,
        refusal=None,
        grade=None,
        failures=[
            Failure(
                stage="candidate",
                code="model_empty_content",
                message="the model returned no text",
                retryable=None,
                case_id=1,
                metadata={},
            )
        ],
        metadata={},
    )


# --- the fold, as a pure function -------------------------------------------------------


def test_one_check_any_attempt_met_scores_one() -> None:
    folded = fold_case_attempts(
        [_attempt("41", [_check("1", False)]), _attempt("42", [_check("1", True)])]
    )

    assert folded.status == "scored"
    assert folded.grade is not None and folded.grade.score == 1.0
    assert folded.output == "42"
    assert [attempt.output for attempt in folded.attempts or []] == ["41", "42"]


def test_two_checks_met_by_different_attempts_score_one() -> None:
    # WHY the ARC rule: the ARC Prize scorer credits each test grid on its own, so grid A from
    # Attempt 1 and grid B from Attempt 2 is a full task. "Best Attempt" would say 0.5.
    folded = fold_case_attempts(
        [
            _attempt("grid A right", [_check("A", True), _check("B", False)]),
            _attempt("grid B right", [_check("A", False), _check("B", True)]),
        ]
    )

    assert folded.grade is not None
    assert folded.grade.score == 1.0
    assert [check.outcome for check in folded.grade.checks] == ["MET", "MET"]


def test_the_shown_answer_is_the_first_best_attempt() -> None:
    folded = fold_case_attempts(
        [
            _attempt("half", [_check("A", True), _check("B", False)]),
            _attempt("half again", [_check("A", True), _check("B", False)]),
            _attempt("none", [_check("A", False), _check("B", False)]),
        ]
    )

    assert folded.output == "half"
    assert folded.grade is not None and folded.grade.score == 0.5


def test_a_folded_check_records_which_attempts_met_it() -> None:
    folded = fold_case_attempts(
        [
            _attempt("41", [_check("1", False)]),
            _attempt("42", [_check("1", True)]),
            _attempt("42", [_check("1", True)]),
        ]
    )

    assert folded.grade is not None
    assert folded.grade.checks[0].metadata[MET_BY_ATTEMPTS_KEY] == [2, 3]


def test_a_partial_check_fails_the_case_as_attempt_grade_not_pass_fail() -> None:
    # WHY: a Check graded 0.6 is neither met nor missed, and no Attempts paper reports a
    # "larger partial" fold, so the Case fails by name instead of guessing.
    folded = fold_case_attempts(
        [_attempt("41", [_check("1", False)]), _attempt("42", [_check("1", None, score=0.6)])]
    )

    assert folded.status == "failed"
    assert [failure.code for failure in folded.failures] == [ATTEMPT_GRADE_NOT_PASS_FAIL]
    assert folded.failures[0].metadata == {"attempt": 2, "check_id": "1"}
    assert folded.attempts is not None and len(folded.attempts) == 2


def test_a_failed_attempt_is_kept_and_the_case_is_graded_from_the_rest() -> None:
    folded = fold_case_attempts([_failed_attempt(), _attempt("42", [_check("1", True)])])

    assert folded.status == "scored"
    assert folded.grade is not None and folded.grade.score == 1.0
    assert folded.attempts is not None
    assert [attempt.status for attempt in folded.attempts] == ["failed", "scored"]


def test_every_attempt_failed_is_attempt_ones_failure_with_the_attempts_list() -> None:
    folded = fold_case_attempts([_failed_attempt(), _failed_attempt()])

    assert folded.status == "failed"
    assert [failure.code for failure in folded.failures] == ["model_empty_content"]
    assert folded.attempts is not None and len(folded.attempts) == 2


def test_check_ids_that_differ_across_attempts_are_a_contract_error() -> None:
    with pytest.raises(ValueError, match="different Checks"):
        fold_case_attempts(
            [_attempt("41", [_check("1", False)]), _attempt("42", [_check("2", True)])]
        )


def test_named_scores_with_attempts_are_refused() -> None:
    named = _attempt("42", [_check("1", True)])
    assert named.grade is not None
    named = named.model_copy(
        update={"grade": named.grade.model_copy(update={"scores": {"f1": 1.0, "exact": 1.0}})}
    )

    with pytest.raises(ValueError, match="Named Scores"):
        fold_case_attempts([_attempt("41", [_check("1", False)]), named])


def test_case_operations_move_onto_each_attempt() -> None:
    # WHY: each Attempt carries its own cost records and the Case none, so a call is billed
    # once, on the Attempt that made it (the SDK sums Attempts, never the Case-level copy).
    operation = OperationOutput(
        operation_id="op", output="41", finish_reason="stop", accounting=None
    )
    first = _attempt("41", [_check("1", False)], operations=[operation])
    second = _attempt(
        "42", [_check("1", True)], operations=[operation.model_copy(update={"output": "42"})]
    )

    folded = fold_case_attempts([first, second])

    assert folded.operations is None
    assert folded.attempts is not None
    assert [attempt.operations for attempt in folded.attempts] == [
        first.operations,
        second.operations,
    ]


def test_one_attempt_is_not_a_fold() -> None:
    with pytest.raises(ValueError, match="at least two"):
        fold_case_attempts([_attempt("42", [_check("1", True)])])


# --- through the shared marking room ----------------------------------------------------


class _ExactMatch:
    """A stand-in Benchmark Grading: one Check per expected token, met if the answer has it.

    It simulates an exact-match scorer graded per output grid; it does not prove anything about
    a judge, which never runs here.
    """

    async def __call__(self, request: GradeRequest) -> CaseGradeOutcome:
        answer: str = getattr(request.answer, "text", "") or ""
        expected: list[str] = list(request.material)  # type: ignore[call-overload]
        checks: list[dict[str, Any]] = [
            _check(token, token in answer).model_dump() for token in expected
        ]
        met: int = sum(1 for check in checks if check["outcome"] == "MET")
        return CaseGradeOutcome(score=met / len(checks), metrics={}, checks=checks)


def _row(case_id: int, output: str) -> dict[str, object]:
    """One Attempt's case-execution envelope, its Candidate having answered ``output``."""

    return graded_answer_payload(
        case_id,
        encode_candidate_invocation(output, "stop", None),
        [
            {
                "case": {
                    "case_id": case_id,
                    "status": "completed",
                    "output": output,
                    "finish_reason": "stop",
                    "refusal": None,
                    "execution": None,
                    "metadata": {},
                }
            }
        ],
    )


def _aggregate(rows: list[object], expected: list[str]) -> dict[str, Any]:
    """Run the shared marking room over one Case's Attempts row, scoring the mean."""

    aggregation = BenchmarkAggregation(
        reader=CaseGradeReader(
            benchmark_label="Test", error_type=ValueError, decode_case_grade=_decode
        ),
        grade_case=_ExactMatch(),
        failure_messages=MESSAGES,
        method="inspect_scorer",
        grading_failure_code="invalid_case_evaluation",
        grading_failure_message="test",
    )

    def scorer(cases: Sequence[CaseResult]) -> CandidateScore:
        scores: list[float] = [case.grade.score or 0.0 for case in cases if case.grade]
        return CandidateScore(score=sum(scores) / len(scores), metrics={})

    raw: str = json.dumps([{"schema": CASE_ATTEMPTS_SCHEMA, "case_id": 1, "attempts": rows}])
    return asyncio.run(
        aggregation.aggregate_async(
            raw,
            benchmark_id="attempts-probe",
            benchmark_revision="rev",
            selected_cases=_selected(1),
            grading_material=lambda _case_id: expected,
            scorer=scorer,
        )
    )


def test_the_marking_room_grades_each_attempt_and_folds_them() -> None:
    result = _aggregate([_row(1, "41"), _row(1, "42")], ["42"])

    case = result["cases"][0]
    assert result["score"] == 1.0
    assert case["output"] == "42"
    assert case["grade"]["score"] == 1.0
    assert [attempt["output"] for attempt in case["attempts"]] == ["41", "42"]
    assert [attempt["grade"]["score"] for attempt in case["attempts"]] == [0.0, 1.0]


def test_the_marking_room_folds_two_grids_per_check() -> None:
    result = _aggregate([_row(1, "grid A"), _row(1, "grid B")], ["A", "B"])

    assert result["cases"][0]["grade"]["score"] == 1.0


def test_a_collected_attempt_error_is_kept_and_the_case_graded_from_the_rest() -> None:
    error_row: dict[str, object] = {
        "case_id": 1,
        "error": {"kind": "ResolutionError", "message": "boom", "code": "upstream_error"},
    }

    result = _aggregate([error_row, _row(1, "42")], ["42"])

    case = result["cases"][0]
    assert case["status"] == "scored"
    assert [attempt["status"] for attempt in case["attempts"]] == ["failed", "scored"]
