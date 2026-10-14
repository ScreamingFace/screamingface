"""An abstained Case: decoded, mirrored and counted (OME-1289 gap, AB#17).

STORY: as a researcher, a Case where the combine step abstained is marked, so I can tell "no
answer" from "wrong answer" without changing the report.v1 bytes of any other Case.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

import screamingface as sf
from screamingface._evaluation.results import _case_result
from screamingface._ui.report_view import report_html
from screamingface.errors import ExecutionError


def _scored(
    case_id: int = 1, *, output: str = "", score: float = 0.0, **extra: Any
) -> sf.CaseResult:
    return sf.CaseResult(
        case_id=case_id,
        input=f"Question {case_id}",
        output=output,
        finish_reason="stop",
        grade=sf.CaseGrade(method="fixture", score=score, metrics={}, checks=()),
        failures=(),
        metadata={},
        **extra,
    )


def _wire(**change: Any) -> dict[str, Any]:
    return {**_scored().to_dict(), **change}


def test_sdk_decodes_abstained_and_counts_it() -> None:
    abstained = _case_result(_wire(abstained=True))

    assert abstained.abstained is True
    assert list(abstained.to_dict())[-1] == "abstained"
    assert abstained.to_dict()["abstained"] is True
    plain = _case_result(_wire())
    assert plain.abstained is False
    assert "abstained" not in plain.to_dict()
    with_operations = _case_result(
        _wire(
            abstained=True,
            operations=[
                {
                    "operation_id": "op_model_1",
                    "output": "",
                    "finish_reason": "stop",
                    "accounting": None,
                }
            ],
        )
    )
    assert list(with_operations.to_dict())[-2:] == ["operations", "abstained"]
    assert _case_result(json.loads(json.dumps(abstained.to_dict()))).abstained is True

    for bad in (False, "yes", 1, None):
        with pytest.raises(ExecutionError, match="abstained must be true"):
            _case_result(_wire(abstained=bad))


def _failed_wire() -> dict[str, Any]:
    failed = sf.CaseResult(
        case_id=1,
        input="Question 1",
        output=None,
        finish_reason=None,
        grade=None,
        failures=(
            sf.Failure(stage="candidate", code="candidate_failed", message="failed", case_id=1),
        ),
        metadata={},
    )
    return failed.to_dict()


def test_abstained_only_marks_a_scored_empty_answer_with_score_zero() -> None:
    wrong_wires = [
        {**_failed_wire(), "abstained": True},
        {**_scored(score=0.5).to_dict(), "abstained": True},
        {**_scored(output="x").to_dict(), "abstained": True},
        {
            **sf.CaseResult(
                case_id=1,
                input="q",
                output=None,
                finish_reason="stop",
                refusal="No.",
                grade=sf.CaseGrade(method="fixture", score=0.0, metrics={}, checks=()),
                failures=(),
                metadata={},
            ).to_dict(),
            "abstained": True,
        },
    ]
    for wire in wrong_wires:
        with pytest.raises(ExecutionError, match="abstained Case"):
            _case_result(wire)
    for build in (
        lambda: _scored(score=0.5, abstained=True),
        lambda: _scored(output="x", abstained=True),
        lambda: sf.CaseResult(
            case_id=1,
            input="q",
            output=None,
            finish_reason="stop",
            refusal="No.",
            grade=sf.CaseGrade(method="fixture", score=0.0, metrics={}, checks=()),
            failures=(),
            metadata={},
            abstained=True,
        ),
        lambda: sf.CaseResult(
            case_id=1,
            input="q",
            output=None,
            finish_reason=None,
            grade=None,
            failures=(
                sf.Failure(stage="candidate", code="candidate_failed", message="f", case_id=1),
            ),
            metadata={},
            abstained=True,
        ),
    ):
        with pytest.raises(ValueError, match="an abstained Case is a scored empty answer"):
            build()
    with pytest.raises(TypeError, match="abstained must be a bool"):
        _scored(abstained="yes")  # type: ignore[arg-type]


def _report(*cases: sf.CaseResult) -> sf.Report:
    from test_report import candidate

    result = candidate("opus", cases=cases)
    return sf.Report(benchmark=result.benchmark, case_count=len(cases), candidates=(result,))


def test_abstained_count_and_the_report_card_text() -> None:
    cases = (
        *(_scored(index, abstained=True) for index in (1, 2)),
        *(_scored(index, output="right", score=1.0) for index in range(3, 8)),
        *(_scored(index, output="wrong", score=0.0) for index in range(8, 11)),
    )
    with_abstains = _report(*cases)
    without = _report(*(case for case in cases if not case.abstained))

    assert with_abstains.candidates[0].abstained_count == 2
    assert without.candidates[0].abstained_count == 0
    assert "2 abstained" in report_html(with_abstains)
    assert "abstained" not in report_html(without)
    assert "abstained_count" not in with_abstains.to_json()
    assert with_abstains.to_dict()["candidates"][0]["cases"][0]["abstained"] is True  # type: ignore[index]
    assert "abstained" not in without.to_dict()["candidates"][0]["cases"][0]  # type: ignore[index]
