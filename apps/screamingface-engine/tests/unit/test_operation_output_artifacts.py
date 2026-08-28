"""Candidate operation outputs survive the Case artifact boundary."""

from __future__ import annotations

import json

from screamingface_engine.benchmarks.aggregation import SelectedCase, scored_case_result
from screamingface_engine.benchmarks.case_records import bind_case_record
from screamingface_engine.benchmarks.contract import OperationOutput
from screamingface_engine.benchmarks.evaluation import CandidateAnswer


def test_case_record_carries_operations_only_when_attributed() -> None:
    cases = json.dumps([{"id": 1, "input": "Explain DiD estimators."}])
    base = {
        "status": "completed",
        "text": "fused",
        "output": "fused",
        "finish_reason": "stop",
        "refusal": None,
        "execution": None,
    }
    attributed = bind_case_record(
        cases,
        case_id=1,
        candidate=CandidateAnswer(
            **base,
            operations=(
                OperationOutput(
                    operation_id="op_model_1",
                    output="alpha",
                    finish_reason="stop",
                    accounting=None,
                ),
            ),
        ),
        schema="example.case.v1",
        benchmark="EXAMPLE",
    )
    solo = bind_case_record(
        cases,
        case_id=1,
        candidate=CandidateAnswer(**base, operations=None),
        schema="example.case.v1",
        benchmark="EXAMPLE",
    )

    assert attributed["operations"] == [
        {
            "operation_id": "op_model_1",
            "output": "alpha",
            "finish_reason": "stop",
            "accounting": None,
        }
    ]
    # INVARIANT: absence stays absence — an unattributed Candidate keeps the legacy shape.
    assert "operations" not in solo


def test_scored_case_result_exports_operations_only_when_present() -> None:
    selected = SelectedCase(case_id=1, input="Explain DiD estimators.", metadata={})
    grade = {"method": "rubric", "score": 1.0, "metrics": {}, "checks": []}

    attributed = scored_case_result(
        selected_case=selected,
        output="fused",
        finish_reason="stop",
        grade=grade,
        operations=[
            {
                "operation_id": "op_model_1",
                "output": "alpha",
                "finish_reason": "stop",
                "accounting": None,
            }
        ],
    ).model_dump(by_alias=True)
    solo = scored_case_result(
        selected_case=selected,
        output="fused",
        finish_reason="stop",
        grade=grade,
    ).model_dump(by_alias=True)

    assert attributed["operations"] == [
        {
            "operation_id": "op_model_1",
            "output": "alpha",
            "finish_reason": "stop",
            "accounting": None,
        }
    ]
    assert "operations" not in solo
