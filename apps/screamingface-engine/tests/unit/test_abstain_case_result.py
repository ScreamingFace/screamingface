"""The Case wire carries ``abstained`` last, only when true, and only on a scored empty answer.

FEATURE: a Case whose Candidate abstained says so on the wire (OME-1289, erd section 9).
STORY: as a report reader, I tell an abstained Case from one the model answered badly.
INVARIANT defended: ``abstained`` is the last Case key and is written only when true, so a Case
with no mark is byte for byte what it was; and it cannot sit on a Case that is not a scored
empty answer worth 0.0, so a mismatch fails loudly instead of printing a contradictory report.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from pydantic import ValidationError
from test_combine_evidence_wire import _CASE_JSON, _case_with_operation, _evidence

from screamingface_engine.benchmarks.contract import (
    CaseGrade,
    CaseResult,
    Failure,
    OperationOutput,
)
from screamingface_engine.benchmarks.graded_results import encode_result


def _abstained_case(**overrides: Any) -> CaseResult:
    fields: dict[str, Any] = {
        "status": "scored",
        "case_id": 1,
        "input": "in",
        "output": "",
        "finish_reason": "stop",
        "refusal": None,
        "grade": CaseGrade(method="test", score=0.0, metrics={}, checks=[]),
        "failures": [],
        "metadata": {},
        "abstained": True,
    }
    fields.update(overrides)
    return CaseResult(**fields)


def _dump(case: CaseResult) -> str:
    return json.dumps(case.model_dump(by_alias=True), ensure_ascii=False, separators=(",", ":"))


def test_case_wire_abstained_key_is_last_and_only_when_true() -> None:
    plain = _abstained_case(abstained=False)
    marked = _abstained_case()
    with_operations = _abstained_case(
        operations=[
            OperationOutput(
                operation_id="op_synthesis_1",
                output="",
                finish_reason="stop",
                accounting=None,
                combine=_evidence(),
            )
        ]
    )

    assert "abstained" not in _dump(plain)
    assert _dump(marked).endswith(',"metadata":{},"abstained":true}')
    assert list(with_operations.model_dump(by_alias=True))[-2:] == ["operations", "abstained"]
    # EV-1: a Case with no mark is byte for byte what it was.
    assert _dump(_case_with_operation()) == _CASE_JSON
    assert "abstained" not in encode_result(_case_with_operation(), benchmark_id="b", revision="r")


def _failure() -> Failure:
    return Failure(
        stage="grading",
        code="case_error",
        message="m",
        retryable=None,
        case_id=1,
        metadata={},
    )


@pytest.mark.parametrize(
    "overrides",
    [
        {
            "status": "failed",
            "output": None,
            "grade": None,
            "failures": [_failure()],
        },
        {"grade": CaseGrade(method="test", score=0.5, metrics={}, checks=[])},
        {"output": "x"},
        {"output": None, "refusal": "I cannot."},
    ],
    ids=["failed-case", "score-not-zero", "has-output", "refusal"],
)
def test_an_abstained_case_is_a_scored_empty_answer_worth_zero(
    overrides: dict[str, Any],
) -> None:
    with pytest.raises(ValidationError, match="abstained Case is a scored empty answer"):
        _abstained_case(**overrides)
