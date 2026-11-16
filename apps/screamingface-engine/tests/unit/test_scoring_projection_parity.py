"""Score identity: every Benchmark scorer scores a scoring projection as it scores the full Case.

FEATURE memory fix 3 (OME-1835), unit 2. For every Benchmark scorer and both failure policies,
scorer(cases) == scorer(projections) for score, metrics and scores (CandidateScore is a
dataclass, so == compares all three). The projection moved to benchmarks/scoring_projection.py;
this file keeps importing it from the old path, so the old path is pinned too.
"""

from collections.abc import Callable, Sequence

import pytest
from test_candidate_result_contract import _grade, _scored_case
from test_result_body import _fixtures

from screamingface_engine.activity.progress import scoring_projection
from screamingface_engine.benchmarks.aggregation import CandidateScore, policy_cases
from screamingface_engine.benchmarks.contract import CaseResult
from screamingface_engine.benchmarks.definition import FailurePolicy
from screamingface_engine.benchmarks.medxpert.aggregate import _accuracy as medxpert_accuracy
from screamingface_engine_inspect.single_shot import _accuracy as inspect_accuracy

Scorer = Callable[[Sequence[CaseResult]], CandidateScore]


def _mixed_cases() -> list[CaseResult]:
    fixtures = _fixtures()
    pool: list[CaseResult] = [
        *fixtures["non_ascii_and_emoji"].cases,
        *fixtures["failed_and_missing"].cases,
        *fixtures["attempts"].cases,
        *fixtures["operations_with_decision_and_charges"].cases,
        *fixtures["abstained"].cases,
        _scored_case(grade=_grade(score=0.0, metrics={"answered": False})),
        _scored_case(
            grade=_grade(
                score=0.5,
                metrics={
                    "answered": True,
                    "verdicts_expected": 4,
                    "verdicts_accepted": 3,
                    "verdicts_rejected": 1,
                },
            )
        ),
    ]
    return [case.model_copy(update={"case_id": index}) for index, case in enumerate(pool, start=1)]


def _named_cases() -> list[CaseResult]:
    failed = _fixtures()["failed_and_missing"].cases[1]
    return [
        _scored_case(1, grade=_grade(score=1.0, scores={"f1": 1.0, "exact": 1.0})),
        _scored_case(2, grade=_grade(score=0.334, scores={"f1": 0.334, "exact": 0.0})),
        _scored_case(3, grade=_grade(score=0.5, scores={"f1": 0.5, "exact": None})),
        failed.model_copy(update={"case_id": 4}),
    ]


def _assert_identity(scorer: Scorer, cases: list[CaseResult], policy: FailurePolicy) -> None:
    full = policy_cases(cases, policy)
    light = policy_cases([scoring_projection(case) for case in cases], policy)
    assert (full is None) == (light is None)
    if full is not None and light is not None:
        assert scorer(full) == scorer(light)


@pytest.mark.parametrize(
    "scorer",
    [medxpert_accuracy, inspect_accuracy],
    ids=["medxpert", "inspect"],
)
@pytest.mark.parametrize("policy", ["coverage_declare", "withhold"])
@pytest.mark.parametrize("cases", [_mixed_cases, _named_cases], ids=["mixed", "named"])
def test_every_scorer_scores_projections_as_it_scores_full_cases(
    scorer: Scorer, cases: Callable[[], list[CaseResult]], policy: FailurePolicy
) -> None:
    _assert_identity(scorer, cases(), policy)


def test_the_named_score_columns_survive_the_projection() -> None:
    full = policy_cases(_named_cases(), "coverage_declare")
    light = policy_cases([scoring_projection(case) for case in _named_cases()], "coverage_declare")
    assert full is not None
    assert light is not None
    projected = inspect_accuracy(light)
    assert projected.scores == inspect_accuracy(full).scores
    assert set(projected.scores) == {"f1", "exact"}
    assert isinstance(projected.scores["f1"], float)


def test_verdict_counts_survive_the_projection() -> None:
    cases = _mixed_cases()
    light = policy_cases([scoring_projection(case) for case in cases], "coverage_declare")
    full = policy_cases(cases, "coverage_declare")
    assert light is not None
    assert full is not None
    projected = inspect_accuracy(light)
    assert projected.metrics["verdicts_expected"] == 4
    assert projected.metrics["verdicts_accepted"] == 3
    assert projected.metrics["verdicts_rejected"] == 1
    assert projected == inspect_accuracy(full)
