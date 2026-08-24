"""Schema-validated GDPval evaluation envelopes — lossless per-Case artifacts."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from screamingface_engine.benchmarks.gdpval.records import CASE_SCHEMA, RUBRIC_SCHEMA
from screamingface_engine.benchmarks.gdpval.verdict import SCHEMA as VERDICT_SCHEMA

RUBRIC_EVALUATION_SCHEMA = "screamingface.gdpval-rubric-evaluation.v1"
CASE_EVALUATION_SCHEMA = "screamingface.gdpval-case-evaluation.v1"

_RUBRIC_EVALUATION_FIELDS = frozenset({"schema", "case_id", "rubric_id", "rubric", "evidence"})
_CASE_EVALUATION_FIELDS = frozenset({"schema", "case_id", "case", "rubric_evaluations"})


def bind_rubric_evaluation(
    case_id: int,
    case_record: Mapping[str, Any] | None,
    rubric_record: Mapping[str, Any],
    evidence: Mapping[str, Any],
) -> dict[str, Any]:
    """Staple one criterion's record and its judge evidence into one envelope.

    Three papers stapled for one checklist line: what the Candidate submitted (the Case record),
    what the criterion was (the rubric record), and what the judge decided (the evidence) — after
    checking all three carry the right schema and belong to this Case and criterion.

    WHY the Case record may be ``None``: a Case with 44 criteria would otherwise store the
    Candidate's full submission 44 times. The full record rides the FIRST row only; the rest
    carry ``{}`` -> ``None`` here. ``bind_case_evaluation`` reassembles it.
    """

    selected = _positive(case_id, "case_id")
    if case_record is not None:
        _require_schema(case_record, CASE_SCHEMA, "Case record")
        _require_case(case_record, selected, "Case record")
    _require_schema(rubric_record, RUBRIC_SCHEMA, "Rubric record")
    _require_case(rubric_record, selected, "Rubric record")
    _require_schema(evidence, VERDICT_SCHEMA, "Rubric verdict")
    _require_case(evidence, selected, "Rubric verdict")
    if evidence.get("rubric_id") != rubric_record.get("rubric_id"):
        raise ValueError("Rubric verdict and record disagree on rubric_id")
    return {
        "schema": RUBRIC_EVALUATION_SCHEMA,
        "case_id": selected,
        "rubric_id": rubric_record.get("rubric_id"),
        "case": dict(case_record) if case_record is not None else None,
        "rubric": dict(rubric_record),
        "evidence": dict(evidence),
    }


def bind_case_evaluation(
    case_id: int,
    rubric_evaluations: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Bundle one Case's criterion rows into the per-Case artifact, hoisting the Case record.

    The inverse of the dedup above: exactly ONE incoming row must carry the embedded Case record.
    Zero carriers or two both raise, as does a duplicated ``rubric_id`` — either means the
    fan-out upstream misbehaved, and a quietly-wrong artifact would poison scoring.
    """

    selected = _positive(case_id, "case_id")
    if not rubric_evaluations:
        raise ValueError("Case evaluation needs at least one rubric evaluation")
    case_record: dict[str, Any] | None = None
    rows: list[dict[str, Any]] = []
    seen: set[Any] = set()
    for index, row in enumerate(rubric_evaluations, start=1):
        _require_schema(row, RUBRIC_EVALUATION_SCHEMA, f"Rubric evaluation {index}")
        _require_case(row, selected, f"Rubric evaluation {index}")
        rubric_id = row.get("rubric_id")
        if rubric_id in seen:
            raise ValueError(f"duplicate rubric_id {rubric_id!r} in Case {selected}")
        seen.add(rubric_id)
        embedded = row.get("case")
        if embedded is not None:
            if case_record is not None:
                raise ValueError(f"Case {selected} carries more than one Case record")
            if not isinstance(embedded, Mapping):
                raise ValueError("embedded Case record must be an object")
            case_record = dict(embedded)
        stripped = dict(row)
        stripped.pop("case", None)
        rows.append(stripped)
    if case_record is None:
        raise ValueError(f"Case {selected} carries no Case record")
    return {
        "schema": CASE_EVALUATION_SCHEMA,
        "case_id": selected,
        "case": case_record,
        "rubric_evaluations": rows,
    }


def decode_case_evaluation(value: object, expected_case_id: int) -> dict[str, Any]:
    """Validate one exact aggregate input envelope without shape inference.

    INVARIANT: no inference. The aggregate reads only envelopes this function accepted, so a
    malformed row fails here rather than becoming a silently missing score downstream.
    """

    selected = _positive(expected_case_id, "expected_case_id")
    if not isinstance(value, Mapping):
        raise ValueError("Case evaluation must be an object")
    _require_schema(value, CASE_EVALUATION_SCHEMA, "Case evaluation")
    _require_case(value, selected, "Case evaluation")
    unknown = set(value) - _CASE_EVALUATION_FIELDS
    if unknown:
        raise ValueError(f"Case evaluation carries unknown fields {sorted(unknown)}")
    case_record = value.get("case")
    if not isinstance(case_record, Mapping):
        raise ValueError("Case evaluation lacks its Case record")
    rows = value.get("rubric_evaluations")
    if not isinstance(rows, Sequence) or isinstance(rows, str) or not rows:
        raise ValueError("Case evaluation needs at least one rubric evaluation")
    return {
        "schema": CASE_EVALUATION_SCHEMA,
        "case_id": selected,
        "case": dict(case_record),
        "rubric_evaluations": _decode_rubric_evaluations(rows, selected),
    }


def _decode_rubric_evaluations(
    values: Sequence[object],
    case_id: int,
) -> list[dict[str, Any]]:
    decoded: list[dict[str, Any]] = []
    for index, row in enumerate(values, start=1):
        label = f"Rubric evaluation {index}"
        if not isinstance(row, Mapping):
            raise ValueError(f"{label} must be an object")
        _require_schema(row, RUBRIC_EVALUATION_SCHEMA, label)
        _require_case(row, case_id, label)
        unknown = set(row) - _RUBRIC_EVALUATION_FIELDS
        if unknown:
            raise ValueError(f"{label} carries unknown fields {sorted(unknown)}")
        decoded.append(dict(row))
    return decoded


def _require_schema(value: Mapping[str, Any], schema: str, label: str) -> None:
    if value.get("schema") != schema:
        raise ValueError(f"{label} must carry schema {schema}")


def _require_case(value: Mapping[str, Any], case_id: int, label: str) -> None:
    if value.get("case_id") != case_id:
        raise ValueError(f"{label} belongs to another Case")


def _positive(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"{label} must be a positive integer")
    return value


__all__ = [
    "CASE_EVALUATION_SCHEMA",
    "RUBRIC_EVALUATION_SCHEMA",
    "bind_case_evaluation",
    "bind_rubric_evaluation",
    "decode_case_evaluation",
]
