"""OME-1039: the shared five-rung failure ladder every rubric board grades through.

INVARIANT: every unusable state becomes a VISIBLE failed Case with a named failure code —
never a silently missing one. The rungs, most-broken first:

    missing_rubric_asset → missing_case_row → case_error → incomplete_verdicts
    → no_positive_points

Message texts come from the BOARD's injected mapping so extraction keeps each board's
failure output byte-identical (gdpval says "criterion" where healthbench says "rubric
item"). The ladder itself owns no message text.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from screamingface_engine.benchmarks.aggregation import SelectedCase
from screamingface_engine.benchmarks.spine.grading import CaseGrader

MESSAGES = {
    "missing_rubric_asset": "test: rubric asset gone",
    "missing_case_row": "test: no row reached the aggregate",
    "case_error": "test: error row collected",
    "incomplete_verdicts": "test: verdicts incomplete",
    "no_positive_points": "test: no positive points",
}


def _fields(row: Mapping[str, Any] | None) -> dict[str, Any]:
    row = row or {}
    return {
        "status": row.get("status", "answered"),
        "output": row.get("output"),
        "refusal": row.get("refusal"),
        "finish_reason": row.get("finish_reason"),
        "metadata": {},
        "execution": None,
        "operations": None,
    }


def _verdicts(row: Mapping[str, Any]) -> tuple[dict[int, bool], int]:
    raw = row.get("verdicts", {})
    return dict(raw), int(row.get("invalid", 0))


def _checks(row: Mapping[str, Any], points: list[int]) -> list[dict[str, Any]]:
    return [
        {
            "type": "rubric",
            "id": str(position),
            "label": f"criterion {position}",
            "outcome": "MET" if met else "UNMET",
            "evidence": [],
            "metadata": {},
        }
        for position, met in sorted(dict(row.get("verdicts", {})).items())
    ]


def _case_score(points: list[int], verdicts: Mapping[int, bool]) -> float | None:
    if not any(point > 0 for point in points):
        return None
    best = sum(point for point in points if point > 0)
    earned = sum(point for index, point in enumerate(points, start=1) if verdicts.get(index))
    return max(0.0, earned / best)


GRADER = CaseGrader(
    failure_messages=MESSAGES,
    case_score=_case_score,
    verdicts=_verdicts,
    checks=_checks,
    candidate_fields=_fields,
)

CASE = SelectedCase(case_id=7, input="question 7", metadata={})


def _sole_failure(result: Any) -> Any:
    assert result.status == "failed"
    assert len(result.failures) == 1
    return result.failures[0]


def test_missing_rubric_asset_is_the_first_rung() -> None:
    result, score, judged, met, invalid = GRADER.case_result(CASE, {"verdicts": {}}, None)
    failure = _sole_failure(result)
    assert (failure.stage, failure.code) == ("grading", "missing_rubric_asset")
    assert failure.message == MESSAGES["missing_rubric_asset"]
    assert (score, judged, met, invalid) == (None, 0, 0, 0)


def test_missing_case_row_surfaces_the_first_collected_orphan_error() -> None:
    # WHY: an on_error=collect row loses its Case identity, so a mid-chain error
    # surfaces as a missing row — the orphan payload carries the actual cause, and
    # the public metadata retains only the sanitized source_error, never raw rows.
    orphans = [{"error": {"message": f"boom {index}", "type": "api_error"}} for index in range(5)]
    result, score, *_ = GRADER.case_result(CASE, None, [5, -3], orphans)
    failure = _sole_failure(result)
    assert (failure.stage, failure.code) == ("candidate", "missing_case_row")
    assert failure.message == "boom 0"
    assert failure.metadata["source_error"]["message"] == "boom 0"
    assert "collected_errors" not in failure.metadata
    assert score is None


def test_missing_case_row_without_orphans_keeps_the_board_message() -> None:
    result, *_ = GRADER.case_result(CASE, None, [5, -3])
    failure = _sole_failure(result)
    assert failure.code == "missing_case_row"
    assert failure.message == MESSAGES["missing_case_row"]
    assert failure.retryable is None


def test_an_error_row_becomes_case_error_with_its_source_attached() -> None:
    row = {"error": {"message": "judge exploded", "type": "api_error"}}
    result, score, *_ = GRADER.case_result(CASE, row, [5, -3])
    failure = _sole_failure(result)
    assert (failure.stage, failure.code) == ("candidate", "case_error")
    assert failure.message == "judge exploded"
    assert failure.metadata["source_error"]["message"] == "judge exploded"
    assert score is None


def test_incomplete_verdicts_fail_with_judged_and_expected_counts() -> None:
    row = {"verdicts": {1: True}}
    result, score, judged, met, invalid = GRADER.case_result(CASE, row, [5, -3])
    failure = _sole_failure(result)
    assert (failure.stage, failure.code) == ("grading", "incomplete_verdicts")
    assert failure.metadata == {"judged": 1, "expected": 2}
    assert (score, judged, met, invalid) == (None, 1, 1, 0)


def test_complete_but_unscorable_case_names_no_positive_points() -> None:
    # WHY distinct from incomplete_verdicts: a complete-but-unscorable Case means the
    # baked asset lost its guaranteed positive item — a baked-asset defect, not judge loss.
    row = {"verdicts": {1: True, 2: False}}
    result, score, judged, met, invalid = GRADER.case_result(CASE, row, [0, -3])
    failure = _sole_failure(result)
    assert (failure.stage, failure.code) == ("grading", "no_positive_points")
    assert score is None
    assert (judged, met) == (2, 1)


def test_a_fully_judged_case_scores_without_failures() -> None:
    row = {"verdicts": {1: True, 2: False}, "output": "an answer", "finish_reason": "stop"}
    result, score, judged, met, invalid = GRADER.case_result(CASE, row, [4, 4])
    assert result.status == "scored"
    assert result.failures == []
    assert result.grade is not None and result.grade.score == 0.5
    assert score == 0.5
    assert (judged, met, invalid) == (2, 1, 0)


def test_a_refused_case_still_carries_its_numeric_grade() -> None:
    row = {
        "verdicts": {1: False, 2: False},
        "status": "refused",
        "refusal": "I cannot help with that.",
        "finish_reason": "content_filter",
    }
    result, score, *_ = GRADER.case_result(CASE, row, [4, 4])
    assert result.status == "refused"
    assert result.refusal == "I cannot help with that."
    assert score == 0.0
