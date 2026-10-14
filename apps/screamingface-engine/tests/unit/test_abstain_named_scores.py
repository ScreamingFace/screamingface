"""An abstained Case scores 0.0 on every Named Score too (OME-1289 E4a, with OME-1268).

FEATURE: a Benchmark that declares Named Scores (MATH, SQuAD) publishes one column per name, and
the headline column must equal the Case score. An abstained Case scores 0.0, so every column of it
is 0.0 as well.
STORY: as a researcher, a vote that found no answer costs the candidate one wrong Case in every
Named Score, and the headline on the wire never disagrees with ``score``.
INVARIANT defended: the grader's columns are never read for an abstained Case, so a grading step
that failed but kept grade material (no columns) still scores the Case instead of raising.
"""

from __future__ import annotations

import json
from typing import Any

from test_abstain_families import _abstained_row
from test_named_scores_contract import _SQUAD, _aggregation, _mean, _selected

from screamingface_engine.benchmarks.definition import SCORES_KEY
from screamingface_engine.benchmarks.shared_grading.benchmark_aggregation import CaseGradeOutcome

_NAMES = ("f1", "exact")


def _abstained_result(outcome: CaseGradeOutcome) -> dict[str, Any]:
    return _aggregation(outcome, _NAMES).aggregate(
        json.dumps([_abstained_row(1)]),
        benchmark_id="inspect-squad",
        benchmark_revision="rev",
        selected_cases=_selected(1),
        grading_material=lambda case_id: {"target": "1889"},
        scorer=_mean,
    )


def test_an_abstained_case_scores_zero_on_every_named_score() -> None:
    result = _abstained_result(CaseGradeOutcome(score=0.667, metrics={}, checks=[], scores=_SQUAD))

    case = result["cases"][0]
    assert (case["status"], case.get("abstained")) == ("scored", True)
    assert case["grade"]["score"] == 0.0
    assert case["grade"][SCORES_KEY] == {"f1": 0.0, "exact": 0.0}
    assert result[SCORES_KEY] == {"f1": 0.0, "exact": 0.0}


def test_an_abstained_case_with_a_kept_grader_failure_scores_zero_without_columns() -> None:
    outcome = CaseGradeOutcome(
        score=None,
        metrics={"judged": 0, "expected": 1},
        checks=[],
        failure_code="incomplete_verdicts",
    )

    case = _abstained_result(outcome)["cases"][0]

    assert (case["status"], case["grade"]["score"]) == ("scored", 0.0)
    assert case["grade"][SCORES_KEY] == {"f1": 0.0, "exact": 0.0}
