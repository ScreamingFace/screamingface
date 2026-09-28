"""Transport completed grades independently of lossy progress observation."""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping, Sequence
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from screamingface_engine.benchmarks.aggregation import SelectedCase
from screamingface_engine.benchmarks.contract import CaseResult


class _GradedRow(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    schema_: Literal["screamingface.graded-case.v1"] = Field(alias="schema")
    benchmark_id: str
    revision: str
    result: CaseResult


def encode_result(result: CaseResult, *, benchmark_id: str, revision: str) -> str:
    return _GradedRow(
        schema="screamingface.graded-case.v1",
        benchmark_id=benchmark_id,
        revision=revision,
        result=result,
    ).model_dump_json(by_alias=True)


def decode_results(
    raw: str,
    *,
    benchmark_id: str,
    revision: str,
    selected: Sequence[SelectedCase],
    failure: Callable[[SelectedCase, int, list[dict[str, Any]] | None], CaseResult],
) -> list[CaseResult]:
    """Validate ordered transport; only a collected error uses board failure mapping.

    INVARIANT: a missing or invalid grade never causes a second grader invocation.
    """
    rows = json.loads(raw)
    if not isinstance(rows, list) or len(rows) > len(selected):
        raise ValueError("graded results must be an array within the selected Case count")
    results = []
    for index, case in enumerate(selected):
        if index >= len(rows):
            results.append(failure(case, index, None))
            continue
        row = json.loads(rows[index]) if isinstance(rows[index], str) else rows[index]
        results.append(_decode_row(row, case, index, benchmark_id, revision, failure))
    return results


def _decode_row(row, case, index, benchmark_id, revision, failure) -> CaseResult:
    if isinstance(row, Mapping) and "error" in row:
        if not isinstance(row["error"], Mapping) or set(row) - {"error", "case_id"}:
            raise ValueError("invalid collected Case failure")
        if "case_id" in row and row["case_id"] != case.case_id:
            raise ValueError("collected failure claims another selected Case")
        return failure(case, index, [dict(row)])
    try:
        decoded = _GradedRow.model_validate(row)
    except ValidationError as exc:
        # INVARIANT: contract errors must not echo answers or private grading evidence.
        raise ValueError("invalid graded Case result envelope") from exc
    if (decoded.benchmark_id, decoded.revision) != (benchmark_id, revision):
        raise ValueError("graded result belongs to another Benchmark or revision")
    result = decoded.result
    if (result.case_id, result.input, result.metadata) != (case.case_id, case.input, case.metadata):
        raise ValueError("graded result does not match the selected Case")
    if any(item.case_id not in (None, case.case_id) for item in result.failures):
        raise ValueError("graded result failure belongs to another Case")
    return result
