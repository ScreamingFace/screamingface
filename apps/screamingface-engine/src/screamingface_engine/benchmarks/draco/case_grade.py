"""Exact DRACO framing between URL4 execution and benchmark Aggregation.

INVARIANT: decoding accepts only the declared envelope and direct fields. It never searches
recursively for plausible grading records because that could bind unrelated nested output.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import Any

from screamingface_engine.benchmarks.contract import is_valid_corrective_execution
from screamingface_engine.benchmarks.draco.records import CASE_SCHEMA, CHECK_SCHEMA
from screamingface_engine.benchmarks.draco.validation import (
    has_text,
    optional_integer,
    require_positive_integer,
)
from screamingface_engine.benchmarks.draco.verdict import SCHEMA as VERDICT_SCHEMA

CRITERION_EVALUATION_SCHEMA = "screamingface.draco-criterion-evaluation.v1"
CASE_GRADE_SCHEMA = "screamingface.draco-case-evaluation.v1"
_CRITERION_FIELDS = frozenset({"schema", "case", "check", "evidence"})
_CASE_FIELDS = frozenset({"schema", "case", "checks", "evidence"})


def build_criterion_grade(
    case_id: int,
    case_record: Mapping[str, Any] | None,
    check_record: Mapping[str, Any],
    evidence: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Bind one Check and its ordered Judge Evidence to an Engine-known Case."""

    selected_id = require_positive_integer(case_id, "DRACO Case id")
    case = dict(case_record) if case_record else None
    if case is not None and not _valid_case(case, selected_id):
        raise ValueError("DRACO Criterion evaluation carries an invalid Case record")
    check = dict(check_record)
    if not _valid_check(check, selected_id):
        raise ValueError("DRACO Criterion evaluation carries an invalid Check record")
    selected_evidence = [dict(item) for item in evidence]
    if not selected_evidence:
        raise ValueError("DRACO Criterion evaluation must contain Judge Evidence")
    criterion_id = str(check["criterion_id"])
    for sequence, item in enumerate(selected_evidence, start=1):
        if not _valid_evidence(item, selected_id, criterion_id, sequence):
            raise ValueError("DRACO Criterion evaluation carries invalid Judge Evidence")
    return {
        "schema": CRITERION_EVALUATION_SCHEMA,
        "case": case,
        "check": check,
        "evidence": selected_evidence,
    }


def build_case_grade(
    case_id: int,
    criteria: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Flatten ordered Criterion Evaluations into one authoritative Case Evaluation."""

    selected_id = require_positive_integer(case_id, "DRACO Case id")
    selected = _mapping_sequence(criteria, "DRACO Criterion evaluations")
    cases: list[dict[str, Any]] = []
    checks: list[dict[str, Any]] = []
    evidence: list[dict[str, Any]] = []
    criterion_ids: set[str] = set()
    for item in selected:
        case, check, items = _criterion_parts(item, selected_id)
        if case is not None:
            cases.append(case)
        criterion_id = str(check["criterion_id"])
        _require(
            criterion_id not in criterion_ids,
            f"DRACO Case evaluation repeats Check {criterion_id!r}",
        )
        criterion_ids.add(criterion_id)
        checks.append(check)
        evidence.extend(items)
    _require(
        len(cases) == 1,
        f"DRACO Case evaluation must carry exactly one Case record; found {len(cases)}",
    )
    return _case_envelope(cases[0], checks, evidence)


def decode_case_grade(
    value: Any,
    expected_case_id: int,
    *,
    judge_passes: int,
) -> dict[str, Any]:
    """Decode one exact Case Evaluation without searching nested text or values."""

    decoded = _root_object(value)
    _require(
        decoded is not None
        and set(decoded) == _CASE_FIELDS
        and decoded.get("schema") == CASE_GRADE_SCHEMA,
        "invalid DRACO Case Evaluation envelope",
    )
    assert decoded is not None
    case = _mapping(decoded.get("case"), "DRACO Case record")
    _require(_valid_case(case, expected_case_id), "invalid DRACO Case record")
    checks = _mapping_sequence(decoded.get("checks"), "DRACO Checks")
    evidence = _mapping_sequence(decoded.get("evidence"), "DRACO Judge Evidence")
    _validate_final_records(expected_case_id, checks, evidence, judge_passes)
    return _case_envelope(case, checks, evidence)


def _criterion_parts(
    item: Mapping[str, Any], case_id: int
) -> tuple[dict[str, Any] | None, dict[str, Any], list[dict[str, Any]]]:
    _require(
        set(item) == _CRITERION_FIELDS and item.get("schema") == CRITERION_EVALUATION_SCHEMA,
        "DRACO Case evaluation contains an invalid Criterion envelope",
    )
    raw_case = item.get("case")
    _require(
        raw_case is None or isinstance(raw_case, Mapping) and _valid_case(raw_case, case_id),
        "DRACO Case evaluation contains an invalid Case record",
    )
    case = dict(raw_case) if isinstance(raw_case, Mapping) else None
    check = _mapping(item.get("check"), "DRACO Check record")
    _require(_valid_check(check, case_id), "DRACO Case evaluation contains an invalid Check record")
    criterion_id = str(check["criterion_id"])
    evidence = _mapping_sequence(item.get("evidence"), "DRACO Judge Evidence")
    for sequence, value in enumerate(evidence, start=1):
        _require(
            _valid_evidence(value, case_id, criterion_id, sequence),
            "DRACO Case evaluation contains invalid Judge Evidence",
        )
    return case, check, evidence


def _validate_final_records(
    case_id: int,
    checks: Sequence[Mapping[str, Any]],
    evidence: Sequence[Mapping[str, Any]],
    judge_passes: int,
) -> None:
    _require(judge_passes > 0, "judge_passes must be positive")
    criterion_ids = [str(item.get("criterion_id")) for item in checks]
    _require(
        len(set(criterion_ids)) == len(criterion_ids)
        and all(_valid_check(item, case_id) for item in checks),
        "invalid DRACO Checks",
    )
    known = set(criterion_ids)
    sequences: dict[str, int] = {criterion_id: 0 for criterion_id in known}
    for item in evidence:
        criterion_id = str(item.get("criterion_id"))
        _require(criterion_id in known, "Judge Evidence names an unknown DRACO Check")
        sequences[criterion_id] += 1
        _require(
            _valid_evidence(item, case_id, criterion_id, sequences[criterion_id]),
            "invalid DRACO Judge Evidence",
        )
    _require(all(sequences.values()), "a DRACO Check carries no Judge Evidence")
    _require(
        all(count <= judge_passes for count in sequences.values()),
        f"a DRACO Check cannot carry more than {judge_passes} Judge Evidence records",
    )


def _case_envelope(
    case: Mapping[str, Any],
    checks: Sequence[Mapping[str, Any]],
    evidence: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    return {
        "schema": CASE_GRADE_SCHEMA,
        "case": dict(case),
        "checks": [dict(item) for item in checks],
        "evidence": [dict(item) for item in evidence],
    }


def _mapping(value: object, label: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{label} must be an object")
    return dict(value)


def _mapping_sequence(value: object, label: str) -> list[dict[str, Any]]:
    if (
        isinstance(value, str | bytes)
        or not isinstance(value, Sequence)
        or not value
        or not all(isinstance(item, Mapping) for item in value)
    ):
        raise ValueError(f"{label} must be a non-empty array of objects")
    return [dict(item) for item in value]


def _require(condition: object, message: str) -> None:
    if not condition:
        raise ValueError(message)


def _valid_case(value: Mapping[str, Any], case_id: int) -> bool:
    finish_reason = value.get("finish_reason")
    status = value.get("status")
    answer = value.get("answer")
    output = value.get("output")
    refusal = value.get("refusal")
    outcome_valid = isinstance(answer, str) and (
        status == "completed"
        and isinstance(output, str)
        and refusal is None
        and answer == output
        or status == "refused"
        and output is None
        and (refusal is None or has_text(refusal))
        and answer == (refusal or "")
    )
    return (
        value.get("schema") == CASE_SCHEMA
        and optional_integer(value.get("case_id")) == case_id
        and has_text(value.get("input"))
        and outcome_valid
        and (finish_reason is None or has_text(finish_reason))
        and "execution" in value
        and is_valid_corrective_execution(value.get("execution"))
        and isinstance(value.get("metadata"), Mapping)
    )


def _valid_check(value: Mapping[str, Any], case_id: int) -> bool:
    return (
        value.get("schema") == CHECK_SCHEMA
        and optional_integer(value.get("case_id")) == case_id
        and has_text(value.get("criterion_id"))
        and value.get("criterion_type") in {"positive", "negative"}
        and has_text(value.get("requirement"))
    )


def _valid_evidence(
    value: Mapping[str, Any],
    case_id: int,
    criterion_id: str,
    sequence: int,
) -> bool:
    if not (
        value.get("schema") == VERDICT_SCHEMA
        and optional_integer(value.get("case_id")) == case_id
        and value.get("criterion_id") == criterion_id
        and optional_integer(value.get("sequence")) == sequence
        and value.get("producer_type") == "model"
        and has_text(value.get("producer_id"))
        and isinstance(value.get("raw_output"), str)
        and type(value.get("valid")) is bool
    ):
        return False
    if value["valid"] is True:
        return value.get("criterion_status") in {"MET", "UNMET"} and isinstance(
            value.get("explanation"), str
        )
    return has_text(value.get("reason"))


def _root_object(value: Any) -> dict[str, Any] | None:
    decoded = value
    if isinstance(decoded, str):
        try:
            decoded = json.loads(decoded)
        except ValueError:
            return None
    return dict(decoded) if isinstance(decoded, Mapping) else None


__all__ = [
    "CASE_GRADE_SCHEMA",
    "CRITERION_EVALUATION_SCHEMA",
    "build_case_grade",
    "build_criterion_grade",
    "decode_case_grade",
]
