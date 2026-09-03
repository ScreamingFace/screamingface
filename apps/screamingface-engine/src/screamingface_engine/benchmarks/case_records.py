"""Shared binding of one Candidate outcome to one selected Benchmark Case."""

from __future__ import annotations

import json
from collections.abc import Mapping

from screamingface_engine.benchmarks.contract import validate_candidate_outcome
from screamingface_engine.benchmarks.evaluation import CandidateAnswer, positive_case_id


def bind_case_record(
    raw_cases: str,
    *,
    case_id: int,
    candidate: CandidateAnswer,
    schema: str,
    benchmark: str,
) -> dict[str, object]:
    """Bind generic Candidate fields without owning Benchmark-specific semantics."""

    selected_id = positive_case_id(case_id)
    validate_candidate_outcome(
        candidate.text,
        candidate.output,
        candidate.refusal,
        status=candidate.status,
        benchmark=benchmark,
    )
    cases = _decode_cases(raw_cases, benchmark)
    row = next(
        (
            value
            for value in cases
            if isinstance(value, Mapping) and _optional_case_id(value.get("id")) == selected_id
        ),
        None,
    )
    if row is None:
        raise ValueError(f"unknown {benchmark} Case {selected_id}")
    input_value = row.get("input")
    if not isinstance(input_value, str) or not input_value.strip():
        raise ValueError(f"{benchmark} Case {selected_id} input must be non-empty text")
    record: dict[str, object] = {
        "schema": schema,
        "case_id": selected_id,
        "input": input_value,
        "status": candidate.status,
        "answer": candidate.text,
        "output": candidate.output,
        "finish_reason": candidate.finish_reason,
        "refusal": candidate.refusal,
        "execution": (
            None if candidate.execution is None else candidate.execution.model_dump(by_alias=True)
        ),
        "metadata": {key: value for key, value in row.items() if key not in {"id", "input"}},
    }
    # INVARIANT: absence stays absence (OME-843) — an unattributed Candidate keeps its
    # legacy shape; the key exists only when the Engine attributed named model outputs.
    if candidate.operations is not None:
        record["operations"] = [
            operation.model_dump(by_alias=True) for operation in candidate.operations
        ]
    return record


def _decode_cases(raw_cases: str, benchmark: str) -> list[object]:
    try:
        cases = json.loads(raw_cases)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{benchmark} cases are not JSON: {exc}") from None
    if not isinstance(cases, list):
        raise ValueError(f"{benchmark} cases must be a JSON array")
    return cases


def _optional_case_id(value: object) -> int | None:
    try:
        return positive_case_id(value)
    except ValueError:
        return None


__all__ = ["bind_case_record"]
