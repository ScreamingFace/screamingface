"""Shared helpers for the Answer, trace and abstain tests (not a test module; OME-1289 gap)."""

from __future__ import annotations

import copy
import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import screamingface as sf
from screamingface._evaluation.combine_evidence import decode_combine_evidence
from screamingface.case_result import CaseOperation, _bind_operation_graph
from screamingface.combine_evidence import CombineEvidence
from screamingface.operation import OperationInfo
from screamingface.operation_accounting import OperationAccounting

_DATA = Path(__file__).parent / "data" / "combine_evidence_cases.json"
_LABEL = "Case Operation combine"


def evidence_wires() -> dict[str, dict[str, Any]]:
    """The real Engine evidence bytes (generated once from the engine, tests/data)."""

    return json.loads(_DATA.read_text(encoding="utf-8"))


def evidence_cases() -> dict[str, CombineEvidence]:
    decoded = {
        name: decode_combine_evidence(copy.deepcopy(wire), _LABEL)
        for name, wire in evidence_wires().items()
    }
    return {name: evidence for name, evidence in decoded.items() if evidence is not None}


def fixture_graph(n: int, *, extra: Sequence[OperationInfo] = ()) -> tuple[OperationInfo, ...]:
    """op_model_1..n (model), op_synthesis_1 (combine, depends on them), then extra."""

    models = tuple(
        OperationInfo(id=f"op_model_{k}", kind="model", label=f"model {k}") for k in range(1, n + 1)
    )
    synthesis = OperationInfo(
        id="op_synthesis_1",
        kind="combine",
        label="synthesis",
        depends_on=tuple(f"op_model_{k}" for k in range(1, n + 1)),
    )
    return (*models, synthesis, *extra)


def fixture_case(
    name: str,
    outputs: Sequence[str | None] | None = None,
    accounting: OperationAccounting | None = None,
    *,
    case_id: int = 1,
) -> sf.CaseResult:
    """A scored Case whose operations are the model calls and one synthesis with the evidence."""

    evidence = evidence_cases()[name]
    count = len(evidence.members)
    texts: Sequence[str | None] = (
        [f"text {k}" for k in range(1, count + 1)] if outputs is None else outputs
    )
    operations = [
        CaseOperation(f"op_model_{k}", texts[k - 1], "stop", accounting)
        for k in range(1, count + 1)
    ]
    operations.append(CaseOperation("op_synthesis_1", "42", "stop", None, combine=evidence))
    return sf.CaseResult(
        case_id=case_id,
        input=f"Question {case_id}",
        output="x",
        finish_reason="stop",
        grade=sf.CaseGrade(method="fixture", score=1.0, metrics={}, checks=()),
        failures=(),
        metadata={},
        operations=operations,
    )


def bound(case: sf.CaseResult, operations: Sequence[OperationInfo]) -> sf.CaseResult:
    _bind_operation_graph(case, operations)
    return case
