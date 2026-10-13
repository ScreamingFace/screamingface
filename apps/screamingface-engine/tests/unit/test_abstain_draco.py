"""DRACO keeps an abstained Case whose judge returned no usable verdict, and its means follow.

FEATURE: an abstained Case is kept (scored 0.0) when the grader still returned its zeroed metric
block, so DRACO's cross-Case reduction reads a complete grade for it (OME-1289, erd section 9).
STORY: as a DRACO researcher, a vote that found no answer costs one Case, and the judge's
failure to rate the empty answer does not turn it into a hole in the report.
INVARIANT defended: `draco_scorer` reads `metrics[key]` on every scored Case, so the abstained
Case must carry the full block; the hand-computed means below pin that.
"""

from __future__ import annotations

import json
from typing import Any

from test_draco_failure_integrity import _RUBRIC, _scored_row, _selected

from screamingface_engine.benchmarks.contract import encode_candidate_invocation
from screamingface_engine.benchmarks.draco import grade as agg
from screamingface_engine.benchmarks.draco.case_grade import (
    build_case_grade,
    build_criterion_grade,
)
from screamingface_engine.benchmarks.draco.records import CASE_SCHEMA, CHECK_SCHEMA
from screamingface_engine.benchmarks.draco.verdict import SCHEMA as VERDICT_SCHEMA
from screamingface_engine.benchmarks.graded_answer import graded_answer_payload

_ABST = encode_candidate_invocation("", "stop", None, abstained=True)


def _abstained_row_with_unusable_verdict(case_id: int) -> dict[str, object]:
    """An abstained Case (empty answer, marked) whose only judge reply was invalid."""
    case_record: dict[str, Any] = {
        "schema": CASE_SCHEMA,
        "case_id": case_id,
        "status": "completed",
        "input": f"Question {case_id}",
        "answer": "",
        "output": "",
        "finish_reason": "stop",
        "refusal": None,
        "execution": None,
        "metadata": {},
        "candidate_abstained": True,
    }
    check = {
        "schema": CHECK_SCHEMA,
        "case_id": case_id,
        "criterion_id": "c1",
        "criterion_type": "positive",
        "requirement": "Correct",
    }
    verdict = {
        "schema": VERDICT_SCHEMA,
        "case_id": case_id,
        "criterion_id": "c1",
        "sequence": 1,
        "producer_type": "model",
        "producer_id": "fixture-judge",
        "valid": False,
        "reason": "the judge reply was not JSON",
        "raw_output": "not json",
    }
    grading = build_case_grade(
        case_id, [build_criterion_grade(case_id, case_record, check, [verdict])]
    )
    return graded_answer_payload(case_id, _ABST, [grading])


def test_an_abstained_case_with_no_usable_verdict_is_kept_and_the_means_follow() -> None:
    answered = _scored_row(1)
    rows = json.dumps(
        [
            graded_answer_payload(
                1, encode_candidate_invocation("Answer 1", "stop", None), [answered]
            ),
            _abstained_row_with_unusable_verdict(2),
        ]
    )

    result = agg.aggregate(
        rows, {1: _RUBRIC, 2: _RUBRIC}, "draco", selected_cases=_selected(1, 2), judge_passes=1
    )

    answered_case, abstained_case = result["cases"]
    assert answered_case["grade"]["score"] == 1.0
    assert abstained_case["status"] == "scored"
    assert abstained_case["abstained"] is True
    assert (abstained_case["grade"]["score"], abstained_case["failures"]) == (0.0, [])
    # The zeroed block the DRACO hook returned is kept on the Case.
    assert abstained_case["grade"]["metrics"] == {
        "normalized_score_sd": 0.0,
        "pass_rate": 0.0,
        "pass_rate_sd": 0.0,
        "accuracy": None,
        "accuracy_pass_rate": None,
        "axis_scores": {},
        "axis_pass_rates": {},
        "coverage": 0.0,
        "coverage_sd": 0.0,
        "n_runs": 0,
        "verdicts_expected": 1,
        "verdicts_accepted": 0,
        "verdicts_rejected": 1,
        "verdicts_invalid": 1,
        "verdicts_missing": 0,
    }
    # By hand, over the 2 scored Cases (1.0 and 0.0 each, one verdict expected per Case):
    assert result["coverage"] == 1.0
    assert result["score"] == 0.5
    assert result["metrics"]["verdict_coverage"] == 0.5
    assert result["metrics"]["pass_rate"] == 0.5
    assert result["metrics"]["verdicts_expected"] == 2
    assert result["metrics"]["verdicts_accepted"] == 1
    assert result["metrics"]["verdicts_invalid"] == 1
    assert result["metrics"]["n_runs"] == 1
