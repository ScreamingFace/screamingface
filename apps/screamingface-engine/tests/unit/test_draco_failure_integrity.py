"""DRACO partial results preserve the operational failure attached to each Case."""

from __future__ import annotations

import json

import pytest

from screamingface_engine.benchmarks.case_execution import case_execution_payload
from screamingface_engine.benchmarks.contract import encode_candidate_invocation
from screamingface_engine.benchmarks.draco import aggregate as agg
from screamingface_engine.benchmarks.draco.case_evaluation import (
    bind_case_evaluation,
    bind_criterion_evaluation,
)
from screamingface_engine.benchmarks.draco.records import CASE_SCHEMA, CHECK_SCHEMA

_RUBRIC = {
    "sections": [
        {"id": "correctness", "criteria": [{"id": "c1", "weight": 1}]},
    ]
}


def _scored_row(case_id: int) -> dict[str, object]:
    raw_output = json.dumps({"explanation": "fixture verdict", "criterion_status": "MET"})
    records = [
        {
            "schema": CASE_SCHEMA,
            "case_id": case_id,
            "status": "completed",
            "input": f"Question {case_id}",
            "answer": f"Answer {case_id}",
            "output": f"Answer {case_id}",
            "finish_reason": "stop",
            "refusal": None,
            "execution": None,
            "metadata": {},
        },
        {
            "schema": CHECK_SCHEMA,
            "case_id": case_id,
            "criterion_id": "c1",
            "criterion_type": "positive",
            "requirement": "Correct",
        },
        {
            "schema": agg.VERDICT_SCHEMA,
            "case_id": case_id,
            "criterion_id": "c1",
            "sequence": 1,
            "producer_type": "model",
            "producer_id": "fixture-judge",
            "criterion_status": "MET",
            "valid": True,
            "explanation": "fixture verdict",
            "raw_output": raw_output,
        },
    ]
    return bind_case_evaluation(
        case_id,
        [bind_criterion_evaluation(case_id, records[0], records[1], [records[2]])],
    )


def _selected(*case_ids: int) -> list[dict[str, object]]:
    return [{"id": case_id, "input": f"Question {case_id}"} for case_id in case_ids]


def _execution(row: dict[str, object]) -> dict[str, object]:
    case = row["case"]
    assert isinstance(case, dict)
    refusal = case["refusal"] if isinstance(case["refusal"], str) else None
    return case_execution_payload(
        int(case["case_id"]),
        encode_candidate_invocation(
            "" if refusal is not None else str(case["answer"]),
            str(case["finish_reason"]),
            refusal,
        ),
        [row],
    )


def test_partial_result_preserves_the_collected_case_error() -> None:
    rows = json.dumps(
        [
            _execution(_scored_row(1)),
            {
                "error": {
                    "kind": "ResolutionError",
                    "code": "provider_error",
                    "message": "provider request failed",
                }
            },
        ]
    )

    result = agg.aggregate(
        rows,
        {1: _RUBRIC, 2: _RUBRIC},
        "draco",
        selected_cases=_selected(1, 2),
        judge_passes=1,
    )

    assert result["case_count"] == 2
    assert result["score"] == 1.0
    assert result["coverage"] == 0.5
    assert result["cases"][0]["grade"]["score"] == 1.0
    expected_failure = [
        {
            "stage": "candidate",
            "code": "provider_error",
            "message": "provider request failed",
            "retryable": None,
            "case_id": 2,
            "metadata": {"row_index": 1, "error_kind": "ResolutionError"},
        }
    ]
    assert result["failures"] == []
    assert result["cases"][1] == {
        "status": "failed",
        "case_id": 2,
        "input": "Question 2",
        "output": None,
        "finish_reason": None,
        "refusal": None,
        "stop_reason": None,
        "rounds_executed": None,
        "grade": None,
        "failures": expected_failure,
        "metadata": {},
    }


def test_a_missing_selected_row_is_retained_and_lowers_coverage() -> None:
    result = agg.aggregate(
        json.dumps([_execution(_scored_row(1))]),
        {1: _RUBRIC, 2: _RUBRIC},
        "draco",
        selected_cases=_selected(1, 2),
        judge_passes=1,
    )

    assert result["score"] == 1.0
    assert result["coverage"] == 0.5
    assert [case["case_id"] for case in result["cases"]] == [1, 2]
    assert result["cases"][1]["failures"][0]["code"] == "case_result_missing"


def test_provider_refusal_is_retained_exactly_and_graded_normally() -> None:
    exact = "I can’t answer that request."
    row = _scored_row(1)
    case_record = row["case"]
    assert isinstance(case_record, dict)
    case_record.update(
        {
            "status": "refused",
            "answer": exact,
            "output": None,
            "finish_reason": "content_filter",
            "refusal": exact,
        }
    )
    result = agg.aggregate(
        json.dumps([_execution(row)]),
        {1: _RUBRIC},
        "draco",
        selected_cases=_selected(1),
        judge_passes=1,
    )

    case = result["cases"][0]
    assert result["score"] == 1.0
    assert result["coverage"] == 1.0
    assert case["status"] == "refused"
    assert case["refusal"] == exact
    assert case["finish_reason"] == "content_filter"
    assert case["grade"]["score"] == 1.0
    assert case["failures"] == []


def test_corrective_execution_provenance_reaches_the_case_result() -> None:
    row = _scored_row(1)
    case_record = row["case"]
    assert isinstance(case_record, dict)
    case_record["execution"] = {
        "schema": "screamingface.corrective-execution.v1",
        "stop_reason": "max_rounds",
        "rounds_executed": 3,
    }

    result = agg.aggregate(
        json.dumps([_execution(row)]),
        {1: _RUBRIC},
        "draco",
        selected_cases=_selected(1),
        judge_passes=1,
    )

    case = result["cases"][0]
    assert case["stop_reason"] == "max_rounds"
    assert case["rounds_executed"] == 3
    assert case["grade"]["score"] == 1.0
    assert case["failures"] == []


def test_missing_selected_case_rubric_retains_the_case_and_lowers_coverage() -> None:
    result = agg.aggregate(
        json.dumps([_execution(_scored_row(1)), _execution(_scored_row(2))]),
        {1: _RUBRIC},
        "draco",
        selected_cases=_selected(1, 2),
        judge_passes=1,
    )

    assert result["case_count"] == 2
    assert result["score"] == 1.0
    assert result["coverage"] == 0.5
    assert result["cases"][0]["grade"]["score"] == 1.0
    assert result["cases"][1] == {
        "status": "failed",
        "case_id": 2,
        "input": "Question 2",
        "output": "Answer 2",
        "finish_reason": "stop",
        "refusal": None,
        "stop_reason": None,
        "rounds_executed": None,
        "grade": None,
        "failures": [
            {
                "stage": "grading",
                "code": "missing_case_rubric",
                "message": "the selected Case has no installed DRACO rubric",
                "retryable": None,
                "case_id": 2,
                "metadata": {"row_index": 1},
            }
        ],
        "metadata": {},
    }


def test_nested_draco_records_abort_as_protocol_corruption() -> None:
    rows = json.dumps([{"nested": {"records": _scored_row(1)}}])

    with pytest.raises(agg.AggregateError, match="Case execution has an invalid shape"):
        agg.aggregate(
            rows,
            {1: _RUBRIC},
            "draco",
            selected_cases=_selected(1),
        )


def test_invalid_judge_evidence_is_retained_under_an_unscored_grade() -> None:
    case = {
        "schema": CASE_SCHEMA,
        "case_id": 1,
        "status": "completed",
        "input": "Question 1",
        "answer": "Answer 1",
        "output": "Answer 1",
        "finish_reason": "stop",
        "refusal": None,
        "execution": None,
        "metadata": {},
    }
    check = {
        "schema": CHECK_SCHEMA,
        "case_id": 1,
        "criterion_id": "c1",
        "criterion_type": "positive",
        "requirement": "Correct",
    }
    invalid = {
        "schema": agg.VERDICT_SCHEMA,
        "case_id": 1,
        "criterion_id": "c1",
        "sequence": 1,
        "producer_type": "model",
        "producer_id": "fixture-judge",
        "valid": False,
        "reason": "invalid_json",
        "raw_output": "not json",
    }
    row = bind_case_evaluation(
        1,
        [bind_criterion_evaluation(1, case, check, [invalid])],
    )

    result = agg.aggregate(
        json.dumps([_execution(row)]),
        {1: _RUBRIC},
        "draco",
        selected_cases=_selected(1),
        judge_passes=1,
    )

    grade = result["cases"][0]["grade"]
    assert result["score"] is None
    assert grade["score"] is None
    assert grade["checks"][0]["evidence"] == [
        {
            "sequence": 1,
            "producer": {"type": "model", "id": "fixture-judge"},
            "valid": False,
            "raw_output": "not json",
            "accounting": None,
            "metadata": {"rejection_reason": "invalid_json"},
        }
    ]
    assert result["cases"][0]["failures"][0]["code"] == "no_valid_judge_verdict"


def test_a_row_claiming_another_selected_case_aborts() -> None:
    rows = json.dumps([_execution(_scored_row(1)), _execution(_scored_row(1))])

    with pytest.raises(agg.AggregateError, match="claims case_id 1, but the selected Case is 2"):
        agg.aggregate(
            rows,
            {1: _RUBRIC, 2: _RUBRIC},
            "draco",
            selected_cases=_selected(1, 2),
            judge_passes=1,
        )


def test_one_row_cannot_mix_verdicts_from_different_cases() -> None:
    row = _scored_row(1)
    foreign = _scored_row(2)
    evidence = row["evidence"]
    foreign_evidence = foreign["evidence"]
    assert isinstance(evidence, list)
    assert isinstance(foreign_evidence, list)
    evidence.append(foreign_evidence[0])
    rows = json.dumps([_execution(row)])

    with pytest.raises(agg.AggregateError, match="invalid DRACO Judge Evidence"):
        agg.aggregate(
            rows,
            {1: _RUBRIC, 2: _RUBRIC},
            "draco",
            selected_cases=_selected(1),
        )
