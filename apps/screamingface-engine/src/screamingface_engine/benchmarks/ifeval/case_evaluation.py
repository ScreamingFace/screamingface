"""Exact IFEval per-Case framing between URL4 execution and Aggregation."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import Any

from screamingface_engine.benchmarks.contract import is_valid_corrective_execution

CASE_EVALUATION_SCHEMA = "screamingface.ifeval-case-evaluation.v1"
CHECK_SCHEMA = "screamingface.ifeval-check.v1"
_FIELDS = frozenset({"schema", "case_id", "attempts"})


def bind_case_evaluation(
    case_id: int,
    attempts: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Bind ordered verifier attempts to one Engine-known IFEval Case."""

    selected_id = _positive_case_id(case_id)
    selected = [dict(attempt) for attempt in attempts]
    if not selected:
        raise ValueError("IFEval Case evaluation must contain at least one attempt")
    for sequence, attempt in enumerate(selected, start=1):
        if attempt.get("schema") != CHECK_SCHEMA:
            raise ValueError("IFEval Case evaluation contains an unsupported attempt schema")
        if _optional_case_id(attempt.get("case_id")) != selected_id:
            raise ValueError("IFEval Case evaluation contains an attempt for another Case")
        if _optional_case_id(attempt.get("attempt")) != sequence:
            raise ValueError("IFEval Case evaluation attempts must be consecutive and ordered")
    return {
        "schema": CASE_EVALUATION_SCHEMA,
        "case_id": selected_id,
        "attempts": selected,
    }


def decode_case_evaluation(
    value: Any,
    expected_case_id: int,
) -> tuple[dict[str, Any], ...] | None:
    """Decode one exact envelope without searching nested text or values."""

    decoded = _root_object(value)
    selected: tuple[dict[str, Any], ...] | None = None
    if (
        decoded is not None
        and set(decoded) == _FIELDS
        and decoded.get("schema") == CASE_EVALUATION_SCHEMA
        and _optional_case_id(decoded.get("case_id")) == expected_case_id
    ):
        attempts = decoded.get("attempts")
        if (
            not isinstance(attempts, str | bytes)
            and isinstance(attempts, Sequence)
            and bool(attempts)
            and all(isinstance(attempt, Mapping) for attempt in attempts)
        ):
            candidate = tuple(dict(attempt) for attempt in attempts)
            if all(
                attempt.get("schema") == CHECK_SCHEMA
                and _optional_case_id(attempt.get("case_id")) == expected_case_id
                and _optional_case_id(attempt.get("attempt")) == sequence
                for sequence, attempt in enumerate(candidate, start=1)
            ):
                selected = candidate
    return selected


def graded_record(
    value: Any,
    expected_case_id: int,
    expected_instruction_ids: Sequence[str],
) -> dict[str, Any]:
    """The one authentic verifier record inside an envelope — or a ``ValueError``.

    The strict gate the pre-fold aggregate ran per row (OME-1101 moved it here):
    exactly one attempt, bound to THIS Case by id AND by the private instruction
    vector, with real boolean verdict vectors and a coherent candidate outcome.
    Anything else raises — a record whose identity cannot be trusted aborts the
    run rather than grading the wrong Case.
    """

    records = decode_case_evaluation(value, expected_case_id)
    if records is None or len(records) != 1:
        raise ValueError("not a valid IFEval Case Evaluation")
    record = records[0]
    strict = record.get("strict")
    loose = record.get("loose")
    expected_ids = list(expected_instruction_ids)
    if not (
        record.get("schema") == CHECK_SCHEMA
        and record.get("valid") is True
        # INVARIANT: an authentic record for ANOTHER known Case is still not this row's
        # grade. The private instruction vector binds the record to the same Case too.
        and _optional_case_id(record.get("case_id")) == expected_case_id
        and record.get("instruction_id_list") == expected_ids
        and _is_bool_vector(strict, len(expected_ids))
        and _is_bool_vector(loose, len(expected_ids))
        and _record_content(record, len(expected_ids))
    ):
        raise ValueError("not a valid IFEval Case Evaluation")
    return record


def _is_bool_vector(value: object, expected_length: int) -> bool:
    """True only for the exact vector type emitted by deterministic verification."""

    return (
        isinstance(value, list)
        and len(value) == expected_length
        and all(type(item) is bool for item in value)
    )


def _record_content(record: Mapping[str, Any], instruction_count: int) -> bool:
    """One coherent candidate outcome: answer/refusal/status/execution agree."""

    status = record.get("status")
    refusal = record.get("refusal")
    answer = record.get("answer")
    return (
        isinstance(answer, str)
        and status in {"completed", "refused"}
        and "refusal" in record
        and (refusal is None or isinstance(refusal, str) and bool(refusal.strip()))
        and (
            status == "completed"
            and refusal is None
            or status == "refused"
            and answer == (refusal or "")
        )
        and "finish_reason" in record
        and (
            record["finish_reason"] is None
            or isinstance(record["finish_reason"], str)
            and bool(record["finish_reason"].strip())
        )
        and "execution" in record
        and is_valid_corrective_execution(record["execution"])
        and isinstance(record.get("descriptions"), list)
        and len(record["descriptions"]) == instruction_count
        and all(isinstance(value, str) and value for value in record["descriptions"])
        and isinstance(record.get("violations"), list)
        and all(isinstance(value, str) for value in record["violations"])
    )


def _root_object(value: Any) -> dict[str, Any] | None:
    decoded = value
    if isinstance(decoded, str):
        try:
            decoded = json.loads(decoded)
        except ValueError:
            return None
    return dict(decoded) if isinstance(decoded, Mapping) else None


def _positive_case_id(value: object) -> int:
    selected = _optional_case_id(value)
    if selected is None or selected < 1:
        raise ValueError("IFEval Case id must be a positive integer")
    return selected


def _optional_case_id(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int | str):
        return None
    try:
        return int(value)
    except ValueError:
        return None


__all__ = [
    "CASE_EVALUATION_SCHEMA",
    "CHECK_SCHEMA",
    "bind_case_evaluation",
    "decode_case_evaluation",
    "graded_record",
]
