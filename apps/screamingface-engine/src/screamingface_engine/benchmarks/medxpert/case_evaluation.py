"""Schema-validated MedXpertQA evaluation envelopes — lossless per-Case artifacts."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

CHECK_SCHEMA = "screamingface.medxpert-check.v1"
CASE_EVALUATION_SCHEMA = "screamingface.medxpert-case-evaluation.v1"

_CASE_EVALUATION_FIELDS = frozenset({"schema", "case_id", "attempts"})


def bind_case_evaluation(
    case_id: int,
    attempts: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Bundle one Case's checked attempt into the per-Case artifact."""

    selected = _positive(case_id, "case_id")
    if not attempts:
        raise ValueError("Case evaluation needs at least one attempt")
    bound: list[dict[str, Any]] = []
    for index, attempt in enumerate(attempts, start=1):
        if not isinstance(attempt, Mapping):
            raise ValueError(f"attempt {index} must be an object")
        if attempt.get("schema") != CHECK_SCHEMA:
            raise ValueError(f"attempt {index} must carry schema {CHECK_SCHEMA}")
        if attempt.get("case_id") != selected:
            raise ValueError(f"attempt {index} belongs to another Case")
        bound.append(dict(attempt))
    return {"schema": CASE_EVALUATION_SCHEMA, "case_id": selected, "attempts": bound}


def decode_case_evaluation(value: object, expected_case_id: int) -> dict[str, Any]:
    """Validate one exact aggregate input envelope without shape inference.

    INVARIANT: no inference. The aggregate reads only envelopes this accepted, so a malformed row
    fails here rather than becoming a silently missing score.
    """

    selected = _positive(expected_case_id, "expected_case_id")
    if not isinstance(value, Mapping):
        raise ValueError("Case evaluation must be an object")
    _require(value, CASE_EVALUATION_SCHEMA, selected, "Case evaluation")
    unknown = set(value) - _CASE_EVALUATION_FIELDS
    if unknown:
        raise ValueError(f"Case evaluation carries unknown fields {sorted(unknown)}")
    attempts = value.get("attempts")
    if not isinstance(attempts, Sequence) or isinstance(attempts, str) or not attempts:
        raise ValueError("Case evaluation needs at least one attempt")
    return {
        "schema": CASE_EVALUATION_SCHEMA,
        "case_id": selected,
        "attempts": [_decoded_attempt(a, i, selected) for i, a in enumerate(attempts, start=1)],
    }


def _decoded_attempt(attempt: object, index: int, case_id: int) -> dict[str, Any]:
    if not isinstance(attempt, Mapping):
        raise ValueError(f"attempt {index} must be an object")
    _require(attempt, CHECK_SCHEMA, case_id, f"attempt {index}")
    return dict(attempt)


def _require(value: Mapping[str, Any], schema: str, case_id: int, label: str) -> None:
    if value.get("schema") != schema:
        raise ValueError(f"{label} must carry schema {schema}")
    if value.get("case_id") != case_id:
        raise ValueError(f"{label} belongs to another Case")


def _positive(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"{label} must be a positive integer")
    return value


__all__ = [
    "CASE_EVALUATION_SCHEMA",
    "CHECK_SCHEMA",
    "bind_case_evaluation",
    "decode_case_evaluation",
]
