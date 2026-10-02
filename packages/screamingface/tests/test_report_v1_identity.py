"""report.v1 byte identity for a reducer report (OME-1289 gap, RT#8 and RT-D2).

CHAR: these pass at once. The golden is the report.v1 export of a report with a model-only Case and
a Case whose operations carry accounting but no combine evidence. Every later commit keeps it, so
the new derivations (answers, trace) provably never leak into ``to_dict``.
"""

from __future__ import annotations

from pathlib import Path

from test_report import candidate, report

import screamingface as sf
from screamingface.case_result import CaseOperation
from screamingface.operation_accounting import OperationAccounting, OperationCache

GOLDEN = Path(__file__).parent / "data" / "report_v1_reducer_report.json"


def _accounting() -> OperationAccounting:
    return OperationAccounting(
        provider="provider",
        request_model="provider/opus",
        response_model="provider/opus",
        usage=sf.Usage(input_tokens=10, output_tokens=4, cost_usd="0.002"),
        provider_latency_ms=30,
        provider_attempts=1,
        cache=OperationCache(hits=0, misses=1, bypasses=0, unknown=0),
    )


def _case(case_id: int, operations: tuple[CaseOperation, ...] | None) -> sf.CaseResult:
    return sf.CaseResult(
        case_id=case_id,
        input=f"Question {case_id}",
        output=f"Answer {case_id}",
        finish_reason="stop",
        grade=sf.CaseGrade(method="fixture", score=1.0, metrics={}, checks=()),
        failures=(),
        metadata={},
        operations=operations,
    )


def reducer_report() -> sf.Report:
    model_only = _case(1, None)
    with_accounting = _case(
        2,
        (
            CaseOperation("op_opus", "Answer 2", "stop", _accounting()),
            CaseOperation("op_opus_aggregate", "Answer 2", "stop", None),
        ),
    )
    return report(candidate("opus", cases=(model_only, with_accounting)))


def _call_new_derivations(value: sf.Report) -> None:
    for candidate_result in value.candidates:
        for case in candidate_result.cases:
            for name in ("answers", "trace"):
                if hasattr(case, name):
                    getattr(case, name)()
    if hasattr(value, "trace_dict"):
        value.trace_dict()


def test_report_to_dict_is_byte_identical() -> None:
    value = reducer_report()
    _call_new_derivations(value)

    assert value.to_json() + "\n" == GOLDEN.read_text(encoding="utf-8")
