"""OME-1039/OME-1097: the ordered failure checks every rubric board grades through.

INVARIANT: every unusable state becomes a VISIBLE failed Case with a named failure code —
never a silently missing one. The checks, most-broken first:

    missing_rubric_asset → missing_case_row → case_error → incomplete_verdicts
    → no_positive_points

Message texts come from the BOARD's injected mapping so extraction keeps each board's
failure output byte-identical (gdpval says "criterion" where healthbench says "rubric
item"). The spine itself owns no message text.

OME-1097 dissolved `CaseGrader` into the `grade_case` seam: the first three checks run
spine-side in `ScoredPath` before the hook is called; the last two come back from the
hook as failure codes. These tests drive the same ladder through the scored path with a
stub hook, so every pinned behavior survives the seam change.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import Any

from screamingface_engine.benchmarks.aggregation import SelectedCase
from screamingface_engine.benchmarks.case_execution import case_execution_payload
from screamingface_engine.benchmarks.contract import encode_candidate_invocation
from screamingface_engine.benchmarks.spine.exam import exam_scorer
from screamingface_engine.benchmarks.spine.rows import RowReader
from screamingface_engine.benchmarks.spine.scored import (
    CaseGradeOutcome,
    GradeRequest,
    ScoredPath,
)

MESSAGES = {
    "missing_rubric_asset": "test: rubric asset gone",
    "missing_case_row": "test: no row reached the aggregate",
    "case_error": "test: error row collected",
    "incomplete_verdicts": "test: verdicts incomplete",
    "no_positive_points": "test: no positive points",
}


class BoardError(ValueError):
    """Stands in for a board's own ``AggregateError``."""


def _case_score(points: list[int], verdicts: Mapping[int, bool]) -> float | None:
    if not any(point > 0 for point in points):
        return None
    best = sum(point for point in points if point > 0)
    earned = sum(point for index, point in enumerate(points, start=1) if verdicts.get(index))
    return max(0.0, earned / best)


async def _hook(request: GradeRequest) -> CaseGradeOutcome:
    """A stub board hook — the fused marking the old per-board callables performed."""

    row = request.row
    verdicts = {int(key): value for key, value in dict(row.get("verdicts", {})).items()}
    invalid = int(row.get("invalid", 0))
    material = request.material
    assert isinstance(material, Sequence)
    points = [int(value) for value in material]
    checks = [
        {
            "type": "rubric",
            "id": str(position),
            "label": f"criterion {position}",
            "outcome": "MET" if met else "UNMET",
            "evidence": [],
            "metadata": {},
        }
        for position, met in sorted(verdicts.items())
    ]
    metrics = {"judged": len(verdicts), "expected": len(points), "invalid_replies": invalid}
    complete = len(verdicts) == len(points) and not invalid
    score = _case_score(points, verdicts) if complete else None
    if score is None:
        code = "no_positive_points" if complete else "incomplete_verdicts"
        return CaseGradeOutcome(score=None, metrics=metrics, checks=checks, failure_code=code)
    return CaseGradeOutcome(score=score, metrics=metrics, checks=checks)


PATH = ScoredPath(
    reader=RowReader(
        benchmark_label="TestBoard",
        error_type=BoardError,
        decode_case_evaluation=lambda grading, case_id: dict(grading),  # type: ignore[arg-type]
    ),
    grade_case=_hook,
    failure_messages=MESSAGES,
    method="rubric",
    grading_failure_code="test_grading_failed",
    grading_failure_message="test: the grader could not grade this Case",
)

CASE = SelectedCase(case_id=7, input="question 7", metadata={})


def _case_result(
    row: dict[str, Any] | None,
    points: list[int] | None,
) -> dict[str, Any]:
    """Run one Case through the scored path; ``row=None`` models a Case with no row."""

    rows: list[object] = []
    if row is not None:
        if "error" in row:
            rows.append(dict(row))
        else:
            body = dict(row)
            grading = {"case": {"status": "answered", **dict(body.pop("case", {}))}, **body}
            rows.append(
                case_execution_payload(
                    7, encode_candidate_invocation("output-7", "stop", None), [grading]
                )
            )
    result = PATH.aggregate(
        json.dumps(rows),
        benchmark_id="test-board",
        benchmark_revision="rev",
        selected_cases=[CASE],
        grading_material=lambda case_id: points,
        scorer=exam_scorer(lambda scores: sum(scores) / len(scores) if scores else None),
    )
    return result["cases"][0]


def _sole_failure(case: Mapping[str, Any]) -> Mapping[str, Any]:
    assert case["status"] == "failed"
    assert len(case["failures"]) == 1
    return case["failures"][0]


def test_missing_rubric_asset_is_the_first_check() -> None:
    case = _case_result({"verdicts": {}}, None)
    failure = _sole_failure(case)
    assert (failure["stage"], failure["code"]) == ("grading", "missing_rubric_asset")
    assert failure["message"] == MESSAGES["missing_rubric_asset"]
    assert case["grade"]["score"] is None


def test_missing_case_row_surfaces_the_collected_orphan_error() -> None:
    # WHY: an on_error=collect row loses its Case identity, so a mid-chain error
    # surfaces as a missing row — the orphan payload carries the actual cause, and
    # the public metadata retains only the sanitized source_error, never raw rows.
    orphan = {"error": {"message": "boom 0", "type": "api_error"}}
    case = _case_result(orphan, [5, -3])
    failure = _sole_failure(case)
    assert (failure["stage"], failure["code"]) == ("candidate", "missing_case_row")
    assert failure["message"] == "boom 0"
    assert failure["metadata"]["source_error"]["message"] == "boom 0"
    assert "collected_errors" not in failure["metadata"]


def test_missing_case_row_without_orphans_keeps_the_board_message() -> None:
    case = _case_result(None, [5, -3])
    failure = _sole_failure(case)
    assert failure["code"] == "missing_case_row"
    assert failure["message"] == MESSAGES["missing_case_row"]
    assert failure["retryable"] is None


def test_an_identified_error_row_becomes_case_error_with_its_source_attached() -> None:
    row = {"case_id": 7, "error": {"message": "judge exploded", "type": "api_error"}}
    case = _case_result(row, [5, -3])
    failure = _sole_failure(case)
    assert (failure["stage"], failure["code"]) == ("candidate", "case_error")
    assert failure["message"] == "judge exploded"
    assert failure["metadata"]["source_error"]["message"] == "judge exploded"


def test_incomplete_verdicts_fail_with_judged_and_expected_counts() -> None:
    case = _case_result({"verdicts": {1: True}}, [5, -3])
    failure = _sole_failure(case)
    assert (failure["stage"], failure["code"]) == ("grading", "incomplete_verdicts")
    assert failure["metadata"] == {"judged": 1, "expected": 2}
    assert case["grade"]["score"] is None


def test_complete_but_unscorable_case_names_no_positive_points() -> None:
    # WHY distinct from incomplete_verdicts: a complete-but-unscorable Case means the
    # baked asset lost its guaranteed positive item — a baked-asset defect, not judge loss.
    case = _case_result({"verdicts": {1: True, 2: False}}, [0, -3])
    failure = _sole_failure(case)
    assert (failure["stage"], failure["code"]) == ("grading", "no_positive_points")
    assert case["grade"]["score"] is None


def test_a_fully_judged_case_scores_without_failures() -> None:
    row = {
        "verdicts": {1: True, 2: False},
        "case": {"status": "completed", "output": "an answer", "finish_reason": "stop"},
    }
    case = _case_result(row, [4, 4])
    assert case["status"] == "scored"
    assert case["failures"] == []
    assert case["grade"]["score"] == 0.5
    assert case["output"] == "an answer"


def test_a_graded_refusal_is_scored_and_still_carries_its_numeric_grade() -> None:
    # INVARIANT (OME-1037): a refusal the board graded is an ordinary scored Case.
    row = {
        "verdicts": {1: False, 2: False},
        "case": {
            "status": "refused",
            "refusal": "I cannot help with that.",
            "finish_reason": "content_filter",
        },
    }
    case = _case_result(row, [4, 4])
    assert case["status"] == "scored"
    assert case["refusal"] == "I cannot help with that."
    assert case["grade"]["score"] == 0.0
