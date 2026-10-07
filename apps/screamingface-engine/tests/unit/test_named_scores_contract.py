"""Named Scores on the Engine's wire and in the shared grading spine (OME-1268, PR 3 of 5).

FEATURE: a Benchmark with several scorers carries every score by name in a `scores` field
on each Case Grade and on the Candidate Result; `score` stays the Headline Score.

INVARIANT: the field is absent unless set, so every single-scorer Benchmark's payload is
byte-identical to before; an unscored Candidate carries none; the key set of a Case Grade
equals the row's declared names, headline first.
"""

from __future__ import annotations

import ast
import asyncio
import math
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError
from test_shared_grading_aggregation import MESSAGES, _decode, _envelope, _grading, _selected

from screamingface_engine.benchmarks.aggregation import (
    CandidateScore,
    SelectedCase,
    finalize_candidate_result,
)
from screamingface_engine.benchmarks.contract import CandidateResult, CaseGrade, CaseResult
from screamingface_engine.benchmarks.definition import INVERTED_GRADE_KEY, SCORES_KEY
from screamingface_engine.benchmarks.shared_grading.benchmark_aggregation import (
    BenchmarkAggregation,
    CaseGradeOutcome,
    CaseGradeReader,
    GradeRequest,
)

_SQUAD: dict[str, float | None] = {"f1": 0.667, "exact": 0.0}


def _grade(**overrides: Any) -> CaseGrade:
    values: dict[str, Any] = {
        "method": "inspect_scorer",
        "score": 0.667,
        "metrics": {},
        "checks": [],
    }
    values.update(overrides)
    return CaseGrade(**values)


def _case(case_id: int, grade: CaseGrade | None, **overrides: Any) -> CaseResult:
    values: dict[str, Any] = {
        "status": "scored" if grade is not None and grade.score is not None else "failed",
        "case_id": case_id,
        "input": "When was the Eiffel Tower built?",
        "output": "1889",
        "finish_reason": "stop",
        "refusal": None,
        "grade": grade,
        "failures": []
        if grade is not None and grade.score is not None
        else [
            {
                "stage": "grading",
                "code": "invalid_score_value",
                "message": "no score",
                "retryable": None,
                "case_id": case_id,
                "metadata": {},
            }
        ],
        "metadata": {},
    }
    values.update(overrides)
    return CaseResult(**values)


# --- the wire ------------------------------------------------------------------------


def test_case_grade_scores_is_absent_from_the_payload_when_empty() -> None:
    # INVARIANT: every single-scorer Benchmark's Case Grade serializes exactly as before.
    assert SCORES_KEY not in _grade().model_dump()
    assert _grade(scores={}).model_dump() == _grade().model_dump()


def test_case_grade_scores_round_trips_when_set() -> None:
    assert _grade(scores=_SQUAD).model_dump()[SCORES_KEY] == _SQUAD


@pytest.mark.parametrize("value", [math.nan, math.inf, True])
def test_case_grade_scores_values_must_be_finite_or_none(value: object) -> None:
    with pytest.raises(ValidationError, match="finite"):
        _grade(scores={"f1": 0.5, "exact": value})


def test_case_grade_scores_allows_none_for_a_scorer_that_could_not_grade() -> None:
    assert _grade(scores={"f1": 0.5, "exact": None}).scores == {"f1": 0.5, "exact": None}


def test_case_grade_scores_keys_must_be_non_empty_strings() -> None:
    with pytest.raises(ValidationError, match="name"):
        _grade(scores={"": 0.5})


def test_candidate_result_scores_is_absent_when_empty() -> None:
    result = CandidateResult(
        benchmark_id="inspect-squad",
        benchmark_revision="rev",
        case_count=1,
        score=0.667,
        coverage=1.0,
        metrics={},
        cases=[_case(1, _grade())],
        failures=[],
    )
    assert SCORES_KEY not in result.as_payload()


def test_candidate_result_scores_round_trips_when_set() -> None:
    result = CandidateResult(
        benchmark_id="inspect-squad",
        benchmark_revision="rev",
        case_count=1,
        score=0.667,
        coverage=1.0,
        metrics={},
        cases=[_case(1, _grade(scores=_SQUAD))],
        failures=[],
        scores=_SQUAD,
    )
    assert result.as_payload()[SCORES_KEY] == _SQUAD
    # Review Focus 1, Engine side: the payload re-validates as the same model.
    assert CandidateResult.model_validate(result.as_payload()) == result


def test_an_unscored_candidate_result_has_no_scores() -> None:
    # INVARIANT: like metrics — an infrastructure failure never becomes a plausible number.
    with pytest.raises(ValidationError, match="scores"):
        CandidateResult(
            benchmark_id="inspect-squad",
            benchmark_revision="rev",
            case_count=1,
            score=None,
            coverage=0.0,
            metrics={},
            cases=[_case(1, _grade(score=None))],
            failures=[],
            scores={"f1": 0.0},
        )


_SDK_VOCABULARY = (
    Path(__file__).resolve().parents[4]
    / "packages"
    / "screamingface"
    / "src"
    / "screamingface"
    / "_catalogue_vocabulary.py"
)


@pytest.mark.skipif(not _SDK_VOCABULARY.exists(), reason="SDK package not present")
def test_scores_key_matches_the_sdk() -> None:
    """The SDK decodes the key by this exact spelling (OME-1268 PR 2); a rename on one side
    would surface only after a paid run, as an SDK refusing an unknown field."""

    tree = ast.parse(_SDK_VOCABULARY.read_text(encoding="utf-8"))
    sdk_keys: dict[str, str] = {
        getattr(node.target, "id", ""): node.value.value
        for node in ast.walk(tree)
        if isinstance(node, ast.AnnAssign)
        and isinstance(node.value, ast.Constant)
        and isinstance(node.value.value, str)
    }
    assert sdk_keys.get("SCORES_KEY") == SCORES_KEY
    assert sdk_keys.get("INVERTED_GRADE_KEY") == INVERTED_GRADE_KEY
    assert SCORES_KEY in CandidateResult.model_fields
    assert SCORES_KEY in CaseGrade.model_fields


# --- the reducer and the finalizer -------------------------------------------------------


def test_finalize_carries_the_scorers_named_scores_onto_the_result() -> None:
    cases = [
        _case(1, _grade(scores=_SQUAD)),
        _case(2, _grade(score=0.0, scores={"f1": 0.0, "exact": 0.0})),
    ]

    def scorer(graded: Any) -> CandidateScore:
        return CandidateScore(score=0.3335, metrics={}, scores={"f1": 0.3335, "exact": 0.0})

    result = finalize_candidate_result(
        benchmark_id="inspect-squad",
        benchmark_revision="rev",
        selected_cases=[
            SelectedCase(case_id=1, input="q1", metadata={}),
            SelectedCase(case_id=2, input="q2", metadata={}),
        ],
        cases=cases,
        scorer=scorer,
    )
    assert result.scores == {"f1": 0.3335, "exact": 0.0}
    assert result.score == 0.3335


def test_finalize_leaves_scores_absent_for_a_single_scorer_benchmark() -> None:
    def scorer(graded: Any) -> CandidateScore:
        return CandidateScore(score=0.667, metrics={})

    result = finalize_candidate_result(
        benchmark_id="inspect-gsm8k",
        benchmark_revision="rev",
        selected_cases=[SelectedCase(case_id=1, input="q1", metadata={})],
        cases=[_case(1, _grade())],
        scorer=scorer,
    )
    assert SCORES_KEY not in result.as_payload()


# --- the shared grading hook: the key set is validated where the row is known -------------


class _Hook:
    def __init__(self, outcome: CaseGradeOutcome) -> None:
        self.outcome = outcome

    async def __call__(self, request: GradeRequest) -> CaseGradeOutcome:
        await asyncio.sleep(0)
        return self.outcome


def _aggregation(outcome: CaseGradeOutcome, named_scores: tuple[str, ...]) -> BenchmarkAggregation:
    return BenchmarkAggregation(
        reader=CaseGradeReader(
            benchmark_label="Test", error_type=ValueError, decode_case_grade=_decode
        ),
        grade_case=_Hook(outcome),
        failure_messages=MESSAGES,
        method="inspect_scorer",
        grading_failure_code="test_grading_failed",
        grading_failure_message="test",
        named_scores=named_scores,
    )


def _rows() -> str:
    import json

    return json.dumps([_envelope(1, _grading(1))])


def _mean(graded: Any) -> CandidateScore:
    return CandidateScore(
        score=graded[0].grade.score, metrics={}, scores=dict(graded[0].grade.scores)
    )


def test_scored_result_writes_the_named_scores_into_the_grade() -> None:
    outcome = CaseGradeOutcome(score=0.667, metrics={}, checks=[], scores=_SQUAD)
    result = _aggregation(outcome, ("f1", "exact")).aggregate(
        _rows(),
        benchmark_id="inspect-squad",
        benchmark_revision="rev",
        selected_cases=_selected(1),
        grading_material=lambda case_id: {"target": "1889"},
        scorer=_mean,
    )
    assert result["cases"][0]["grade"][SCORES_KEY] == _SQUAD
    assert result[SCORES_KEY] == _SQUAD


def test_scored_result_refuses_a_key_set_that_differs_from_named_scores() -> None:
    # Review Focus / F4: the aggregation knows the row; a Case Grade whose keys drift from
    # the declared names fails loudly instead of publishing a column nobody declared.
    outcome = CaseGradeOutcome(score=0.667, metrics={}, checks=[], scores={"f1": 0.667, "em": 0.0})
    with pytest.raises(ValueError, match="named_scores"):
        _aggregation(outcome, ("f1", "exact")).aggregate(
            _rows(),
            benchmark_id="inspect-squad",
            benchmark_revision="rev",
            selected_cases=_selected(1),
            grading_material=lambda case_id: {"target": "1889"},
            scorer=_mean,
        )


def test_scored_result_refuses_a_headline_column_that_differs_from_score() -> None:
    outcome = CaseGradeOutcome(score=0.5, metrics={}, checks=[], scores={"f1": 0.667, "exact": 0.0})
    with pytest.raises(ValueError, match="headline"):
        _aggregation(outcome, ("f1", "exact")).aggregate(
            _rows(),
            benchmark_id="inspect-squad",
            benchmark_revision="rev",
            selected_cases=_selected(1),
            grading_material=lambda case_id: {"target": "1889"},
            scorer=_mean,
        )


def test_a_hook_returning_scores_on_a_row_declaring_none_is_refused() -> None:
    # Review finding on #1249: without a declaration there is no key set to check against,
    # so a hook's columns must never reach the wire under nobody's name.
    outcome = CaseGradeOutcome(score=0.667, metrics={}, checks=[], scores=_SQUAD)
    with pytest.raises(ValueError, match="declares none"):
        _aggregation(outcome, ()).aggregate(
            _rows(),
            benchmark_id="inspect-squad",
            benchmark_revision="rev",
            selected_cases=_selected(1),
            grading_material=lambda case_id: {"target": "1889"},
            scorer=_mean,
        )


# --- the real reducer -----------------------------------------------------------------------


def _selected_cases(count: int) -> list[SelectedCase]:
    return [SelectedCase(case_id=n, input=f"q{n}", metadata={}) for n in range(1, count + 1)]


def test_the_real_reducer_averages_every_column_over_the_graded_cases_only() -> None:
    """Keelan's review finding #3 on #1249: the finalizer test above supplies precomputed
    columns, so an empty reducer passed. This runs the imported single-shot reducer itself:
    2 graded Cases (f1 1.0 / exact 1.0, f1 0.334 / exact 0.0) and 1 failed Case → the
    headline is mean(f1) = 0.667, exact 0.5, coverage 2/3, scores[headline] == score."""

    from screamingface_engine_inspect.single_shot import _accuracy

    result = finalize_candidate_result(
        benchmark_id="inspect-squad",
        benchmark_revision="rev",
        selected_cases=_selected_cases(3),
        cases=[
            _case(1, _grade(score=1.0, scores={"f1": 1.0, "exact": 1.0})),
            _case(2, _grade(score=0.334, scores={"f1": 0.334, "exact": 0.0})),
            _case(3, None),
        ],
        scorer=_accuracy,
    )
    assert result.score == 0.667
    assert result.scores == {"f1": 0.667, "exact": 0.5}
    assert result.scores["f1"] == result.score
    assert result.coverage == 0.6667  # 2 of 3 selected Cases carry a grade, rounded as published
    assert result.metrics["scored_cases"] == 2


def test_the_real_reducer_publishes_a_column_one_graded_case_could_not_fill_as_unknown() -> None:
    # Review finding on #1249: {f1 .5, exact None}, {f1 1, exact 1} must not publish exact
    # as 1.0 over ONE Case while f1 averages over two — every column shares the headline's
    # denominator, so the half-filled column is unknown.
    from screamingface_engine_inspect.single_shot import _accuracy

    result = finalize_candidate_result(
        benchmark_id="inspect-squad",
        benchmark_revision="rev",
        selected_cases=_selected_cases(2),
        cases=[
            _case(1, _grade(score=0.5, scores={"f1": 0.5, "exact": None})),
            _case(2, _grade(score=1.0, scores={"f1": 1.0, "exact": 1.0})),
        ],
        scorer=_accuracy,
    )
    assert result.score == 0.75
    assert result.scores == {"f1": 0.75, "exact": None}
