"""OME-1097: the shared scored path behind the `grade_case` hook.

The scored path is the marking room: one row per Case comes back from the fan-out,
each script is marked against the board's rubric, and the marks fold into the exam
result. This module proves the marking room lives ONCE in the spine and that the
only per-board seam is `grade_case` — an async, data-in/data-out callable.

INVARIANT (the hourglass waist): a `GradeRequest` carries ONLY plain, serializable
data — kind-tagged payloads, the decoded row mapping, the board's grading material.
No `Path`, no engine objects, no callbacks. Three consumers force this: an enclave
judge across a privacy boundary, the inspect_evals scorer shim, and future agentic
boards whose answer is not a string.

INVARIANT: every unusable state stays a VISIBLE failed Case with a named code, and
message wording stays board-owned — the spine moves logic, never words.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import pytest

from screamingface_engine.benchmarks.aggregation import SelectedCase
from screamingface_engine.benchmarks.case_execution import case_execution_payload
from screamingface_engine.benchmarks.contract import encode_candidate_invocation
from screamingface_engine.benchmarks.spine.payloads import CasePayload, TextPayload
from screamingface_engine.benchmarks.spine.rows import RowReader, read_selected_cases
from screamingface_engine.benchmarks.spine.rubric import rubric_grade_case
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


def _decode(grading: object, expected_case_id: int) -> dict[str, Any]:
    """Stub board decoder: hand the grading envelope through untouched."""

    assert isinstance(grading, Mapping)
    return dict(grading)


def _mean(scores: Sequence[float]) -> float | None:
    return sum(scores) / len(scores) if scores else None


def _grading(case_id: int, *, status: str = "completed", **extra: Any) -> dict[str, Any]:
    """One decoded-row-shaped grading envelope with a hoisted candidate record."""

    refusal = extra.pop("refusal", None)
    return {
        "case": {
            "case_id": case_id,
            "status": status,
            "output": None if refusal else f"output-{case_id}",
            "finish_reason": "content_filter" if refusal else "stop",
            "refusal": refusal,
            "execution": None,
            "metadata": {},
        },
        **extra,
    }


def _envelope(case_id: int, grading: Mapping[str, Any]) -> dict[str, object]:
    return case_execution_payload(
        case_id,
        encode_candidate_invocation(f"output-{case_id}", "stop", None),
        [dict(grading)],
    )


def _selected(*case_ids: int) -> list[SelectedCase]:
    return [
        SelectedCase(case_id=case_id, input=f"input-{case_id}", metadata={}) for case_id in case_ids
    ]


class _Hook:
    """A recording stub `grade_case` — the board hook the spine must treat as opaque."""

    def __init__(self, outcome: CaseGradeOutcome | None = None) -> None:
        self.requests: list[GradeRequest] = []
        self.outcome = outcome or CaseGradeOutcome(
            score=0.5,
            metrics={"judged": 2, "expected": 2, "invalid_replies": 0},
            checks=[],
        )

    async def __call__(self, request: GradeRequest) -> CaseGradeOutcome:
        # WHY the sleep: proves the sync aggregate really drives an async hook —
        # a hook that suspends must still complete (enclave calls are network hops).
        await asyncio.sleep(0)
        self.requests.append(request)
        return self.outcome


def _path(hook: _Hook, **overrides: Any) -> ScoredPath:
    values: dict[str, Any] = {
        "reader": RowReader(
            benchmark_label="TestBoard",
            error_type=BoardError,
            decode_case_evaluation=_decode,
        ),
        "grade_case": hook,
        "failure_messages": MESSAGES,
        "method": "rubric",
        "grading_failure_code": "test_grading_failed",
        "grading_failure_message": "test: the grader could not grade this Case",
    }
    values.update(overrides)
    return ScoredPath(**values)


def _aggregate(
    path: ScoredPath,
    rows: Sequence[Mapping[str, Any]],
    selected: list[SelectedCase],
    material: Any = (5, -3),
) -> dict[str, Any]:
    return path.aggregate(
        json.dumps(rows),
        benchmark_id="test-board",
        benchmark_revision="rev",
        selected_cases=selected,
        grading_material=lambda case_id: material,
        mean=_mean,
    )


# ── payloads ────────────────────────────────────────────────────────────────


def test_text_payload_is_kind_tagged_and_frozen() -> None:
    payload = TextPayload(text="an answer")
    assert payload.kind == "text"
    with pytest.raises(AttributeError):
        payload.text = "rewritten"  # type: ignore[misc]
    # Today's union has one member; the alias is the extension point (OME-1103).
    assert CasePayload is TextPayload


# ── the hook contract ───────────────────────────────────────────────────────


def test_the_hook_receives_plain_kind_tagged_data() -> None:
    hook = _Hook()
    material = {"points": [5, -3]}
    result = _aggregate(_path(hook), [_envelope(1, _grading(1))], _selected(1), material=material)

    assert len(hook.requests) == 1
    request = hook.requests[0]
    assert request.case_id == 1
    assert request.input == TextPayload(text="input-1")
    assert request.answer == TextPayload(text="output-1")
    # The board's grading material and decoded row pass through untouched…
    assert request.material is material
    assert request.row["case"]["status"] == "completed"
    # …and the whole request is plain data: nothing here can hold a Path or an
    # engine object, so the same call works across an enclave boundary.
    assert not isinstance(request.material, Path)
    json.dumps({"row": dict(request.row), "material": material})
    assert result["cases"][0]["status"] == "scored"


def test_a_refusal_answer_stays_a_payload_and_a_scored_refusal() -> None:
    # INVARIANT (OME-1037): a refusal the board graded is an ordinary scored Case.
    hook = _Hook()
    grading = _grading(1, status="refused", refusal="I cannot help with that.")
    result = _aggregate(_path(hook), [_envelope(1, grading)], _selected(1))

    assert hook.requests[0].answer is None  # a refusal carries no output payload
    case = result["cases"][0]
    assert case["status"] == "scored"
    assert case["refusal"] == "I cannot help with that."
    assert case["grade"]["score"] == 0.5


def test_the_hook_grade_lands_in_the_case_result_verbatim() -> None:
    checks = [
        {
            "type": "rubric_item",
            "id": "1",
            "label": "[1] c1",
            "outcome": "MET",
            "evidence": [],
            "metadata": {"points": 5},
        }
    ]
    hook = _Hook(
        CaseGradeOutcome(
            score=0.25,
            metrics={"judged": 1, "expected": 1, "invalid_replies": 0},
            checks=checks,
        )
    )
    result = _aggregate(_path(hook), [_envelope(1, _grading(1))], _selected(1))

    grade = result["cases"][0]["grade"]
    assert grade["method"] == "rubric"
    assert grade["score"] == 0.25
    assert grade["metrics"] == {"judged": 1, "expected": 1, "invalid_replies": 0}
    assert [check["id"] for check in grade["checks"]] == ["1"]


def test_a_hook_failure_code_takes_the_board_wording_and_counts() -> None:
    hook = _Hook(
        CaseGradeOutcome(
            score=None,
            metrics={"judged": 1, "expected": 2, "invalid_replies": 0},
            checks=[],
            failure_code="incomplete_verdicts",
        )
    )
    result = _aggregate(_path(hook), [_envelope(1, _grading(1))], _selected(1))

    case = result["cases"][0]
    assert case["status"] == "failed"
    failure = case["failures"][0]
    assert (failure["stage"], failure["code"]) == ("grading", "incomplete_verdicts")
    assert failure["message"] == MESSAGES["incomplete_verdicts"]
    assert failure["metadata"] == {"judged": 1, "expected": 2}
    assert case["grade"]["score"] is None


# ── the pre-hook ladder: unusable states never reach the hook ───────────────


def test_missing_grading_material_never_calls_the_hook() -> None:
    hook = _Hook()
    result = _aggregate(_path(hook), [_envelope(1, _grading(1))], _selected(1), material=None)

    assert hook.requests == []
    failure = result["cases"][0]["failures"][0]
    assert (failure["stage"], failure["code"]) == ("grading", "missing_rubric_asset")
    assert failure["message"] == MESSAGES["missing_rubric_asset"]


def test_a_missing_row_surfaces_its_orphan_cause_without_the_hook() -> None:
    hook = _Hook()
    orphan = {"error": {"kind": "transport", "message": "boom"}}
    result = _aggregate(_path(hook), [orphan], _selected(1))

    assert hook.requests == []
    failure = result["cases"][0]["failures"][0]
    assert (failure["stage"], failure["code"]) == ("candidate", "missing_case_row")
    assert failure["message"] == "boom"


def test_an_identified_error_row_becomes_case_error_without_the_hook() -> None:
    hook = _Hook()
    row = {"case_id": 1, "error": {"kind": "api_error", "message": "judge exploded"}}
    result = _aggregate(_path(hook), [row], _selected(1))

    assert hook.requests == []
    failure = result["cases"][0]["failures"][0]
    assert (failure["stage"], failure["code"]) == ("candidate", "case_error")
    assert failure["message"] == "judge exploded"


def test_a_grading_failure_row_keeps_the_board_code_and_the_answer() -> None:
    hook = _Hook()
    grading_error = {"error": {"kind": "api_error", "message": "grading step failed"}}
    row = case_execution_payload(
        1, encode_candidate_invocation("output-1", "stop", None), [grading_error]
    )
    result = _aggregate(_path(hook), [row], _selected(1))

    assert hook.requests == []
    case = result["cases"][0]
    assert case["status"] == "failed"
    assert case["output"] == "output-1"  # the Candidate's answer is retained
    assert case["failures"][0]["stage"] == "grading"


def test_every_selected_case_stays_on_the_roll_call() -> None:
    # INVARIANT: dropping a failed Case inflates the mean — Case 2 must stay
    # visible as failed while Case 1 scores.
    hook = _Hook()
    result = _aggregate(_path(hook), [_envelope(1, _grading(1))], _selected(1, 2))

    by_id = {case["case_id"]: case["status"] for case in result["cases"]}
    assert by_id == {1: "scored", 2: "failed"}
    assert result["coverage"] == 0.5


# ── the shared exam scorer: mean is the parameter, vocabulary is fixed ──────


def test_exam_metric_vocabulary_is_pinned_and_the_mean_is_the_boards() -> None:
    graded = CaseGradeOutcome(
        score=1.0,
        metrics={"judged": 2, "expected": 2, "invalid_replies": 1},
        checks=[
            {
                "type": "rubric_item",
                "id": "1",
                "label": "[1] c1",
                "outcome": "MET",
                "evidence": [],
                "metadata": {},
            },
            {
                "type": "rubric_item",
                "id": "2",
                "label": "[1] c2",
                "outcome": "UNMET",
                "evidence": [],
                "metadata": {},
            },
        ],
    )
    hook = _Hook(graded)
    result = _aggregate(
        _path(hook),
        [_envelope(1, _grading(1)), _envelope(2, _grading(2))],
        _selected(1, 2),
    )

    assert result["score"] == 1.0  # _mean over [1.0, 1.0]
    assert set(result["metrics"]) == {
        "pass_rate",
        "scored_cases",
        "score_sd",
        "verdict_coverage",
        "judge_invalid_replies",
    }
    assert result["metrics"]["scored_cases"] == 2
    assert result["metrics"]["pass_rate"] == 0.5  # 2 MET of 4 judged
    assert result["metrics"]["judge_invalid_replies"] == 2
    assert result["metrics"]["verdict_coverage"] == 1.0
    assert result["metrics"]["score_sd"] == 0.0


# ── the shared rubric hook factory: both boards' marking, written once ──────


def _evidence(rubric_id: int, met: bool | None) -> dict[str, Any]:
    """met=None models an invalid judge reply."""

    valid = met is not None
    # WHY no producer_id: proves the factory stamps the board's judge identity onto
    # replies that arrive without one — even a malformed reply has a known producer.
    evidence: dict[str, Any] = {
        "rubric_id": rubric_id,
        "producer_type": "model",
        "valid": valid,
        "raw_output": "{}",
    }
    if valid:
        evidence["criteria_met"] = met
        evidence["explanation"] = "…"
    else:
        evidence["reason"] = "malformed"
    return evidence


def _evaluations(verdicts: Mapping[int, bool | None]) -> list[dict[str, Any]]:
    return [
        {
            "rubric_id": rubric_id,
            "rubric": {"rubric_item": f"[1] c{rubric_id}"},
            "evidence": _evidence(rubric_id, met),
        }
        for rubric_id, met in verdicts.items()
    ]


def _case_score(points: Sequence[int], verdicts: Mapping[int, bool]) -> float | None:
    best = sum(point for point in points if point > 0)
    if best <= 0:
        return None
    earned = sum(point for index, point in enumerate(points, start=1) if verdicts.get(index))
    return earned / best


def _request(verdicts: Mapping[int, bool | None], points: Sequence[int] | None) -> GradeRequest:
    return GradeRequest(
        case_id=1,
        input=TextPayload(text="input-1"),
        answer=TextPayload(text="output-1"),
        row={"case": {"status": "completed"}, "rubric_evaluations": _evaluations(verdicts)},
        material=points,
    )


def _run_hook(request: GradeRequest) -> CaseGradeOutcome:
    hook = rubric_grade_case(case_score=_case_score, judge_producer_id="test/judge")

    async def call() -> CaseGradeOutcome:
        return await hook(request)

    return asyncio.run(call())


def _grade(verdicts: Mapping[int, bool | None], points: Sequence[int] | None) -> CaseGradeOutcome:
    return _run_hook(_request(verdicts, points))


def test_rubric_hook_scores_complete_verdicts_with_the_board_formula() -> None:
    outcome = _grade({1: True, 2: False, 3: True}, [5, 3, -3])

    assert outcome.failure_code is None
    assert outcome.score == pytest.approx((5 - 3) / 8)
    assert outcome.metrics == {"judged": 3, "expected": 3, "invalid_replies": 0}
    checks = list(outcome.checks)
    assert [check["outcome"] for check in checks] == ["MET", "UNMET", "MET"]
    assert [check["metadata"] for check in checks] == [
        {"points": 5},
        {"points": 3},
        {"points": -3},
    ]
    assert checks[0]["evidence"][0]["producer"]["id"] == "test/judge"


def test_rubric_hook_reports_incomplete_verdicts_never_a_default() -> None:
    # INVARIANT: a missing verdict on a penalty item would erase the penalty —
    # partial verdict sets fail, they are never defaulted to "not hit".
    outcome = _grade({1: True}, [5, -3])

    assert outcome.failure_code == "incomplete_verdicts"
    assert outcome.score is None
    assert outcome.metrics == {"judged": 1, "expected": 2, "invalid_replies": 0}


def test_rubric_hook_counts_invalid_replies_and_fails_the_case() -> None:
    outcome = _grade({1: True, 2: None}, [5, -3])

    assert outcome.failure_code == "incomplete_verdicts"
    assert outcome.metrics["invalid_replies"] == 1
    # The invalid reply's check stays outcome-less: unjudged, not failed.
    invalid_check = list(outcome.checks)[1]
    assert "outcome" not in invalid_check
    assert invalid_check["evidence"][0]["metadata"] == {"rejection_reason": "malformed"}


def test_rubric_hook_names_a_complete_but_unscorable_case() -> None:
    outcome = _grade({1: True, 2: True}, [0, -3])

    assert outcome.failure_code == "no_positive_points"
    assert outcome.score is None


def test_rubric_hook_dedupes_duplicate_judge_entries() -> None:
    # Retry noise: the same rubric_id judged twice must not widen judged counts.
    evaluations = _evaluations({1: True}) + _evaluations({1: False})
    request = GradeRequest(
        case_id=1,
        input=TextPayload(text="input-1"),
        answer=None,
        row={"case": {"status": "completed"}, "rubric_evaluations": evaluations},
        material=[5],
    )
    outcome = _run_hook(request)

    assert outcome.metrics["judged"] == 1
    assert len(list(outcome.checks)) == 1  # last entry wins, one check per rubric_id


# ── the shared selected-cases reader ────────────────────────────────────────


def test_selected_cases_reader_returns_the_roll_call_in_order(tmp_path: Path) -> None:
    (tmp_path / "cases.json").write_text(
        json.dumps([{"id": 2, "input": "two"}, {"id": 1, "input": "one"}]), encoding="utf-8"
    )
    selected = read_selected_cases(
        tmp_path, (1, 2), benchmark_label="TestBoard", error_type=BoardError
    )
    assert [(case.case_id, case.input) for case in selected] == [(1, "one"), (2, "two")]


def test_selected_cases_reader_names_the_board_in_its_errors(tmp_path: Path) -> None:
    with pytest.raises(BoardError, match="TestBoard cases are unavailable"):
        read_selected_cases(tmp_path, (1,), benchmark_label="TestBoard", error_type=BoardError)

    (tmp_path / "cases.json").write_text(json.dumps([{"id": 1, "input": " "}]), encoding="utf-8")
    with pytest.raises(BoardError, match="TestBoard Case 1 has no public input"):
        read_selected_cases(tmp_path, (1,), benchmark_label="TestBoard", error_type=BoardError)
