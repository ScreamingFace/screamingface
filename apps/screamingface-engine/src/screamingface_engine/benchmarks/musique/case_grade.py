"""Schema-validated MuSiQue-Ans evaluation envelopes — lossless per-Case artifacts.

A check record holds what one reply COMMITTED (spec D6, D7): the answer it wrote after its last
`Answer:`, the paragraph numbers after its last `Supporting paragraphs:`, and whether each label
was found at all. It holds no grade; the answer key is applied once, at aggregation.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

CHECK_SCHEMA = "screamingface.musique-check.v1"
CASE_GRADE_SCHEMA = "screamingface.musique-case-evaluation.v1"

_CASE_GRADE_FIELDS = frozenset({"schema", "case_id", "attempts"})

# INVARIANT: every field the grade reads is validated HERE, on the way in. A missing `answer`
# read as "" would score 0 with no failure reported, and a missing flag read as False would
# report a format failure the reply never made.
_VERDICT_FLAGS = ("answer_line", "support_line")


def build_case_grade(
    case_id: int,
    attempts: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Bundle one Case's checked attempt into the per-Case artifact."""

    selected: int = _positive(case_id, "case_id")
    if not attempts:
        raise ValueError("Case evaluation needs at least one attempt")
    bound: list[dict[str, Any]] = []
    for index, attempt in enumerate(attempts, start=1):
        if not isinstance(attempt, Mapping):
            raise ValueError(f"attempt {index} must be an object")
        _require(attempt, CHECK_SCHEMA, selected, f"attempt {index}")
        _require_verdict(attempt, f"attempt {index}")
        bound.append(dict(attempt))
    return {"schema": CASE_GRADE_SCHEMA, "case_id": selected, "attempts": bound}


def decode_case_grade(value: object, expected_case_id: int) -> dict[str, Any]:
    """Validate one exact aggregate input envelope without shape inference.

    INVARIANT: no inference. The aggregate reads only envelopes this accepted, so a malformed row
    fails here rather than becoming a silently wrong score.
    """

    selected: int = _positive(expected_case_id, "expected_case_id")
    if not isinstance(value, Mapping):
        raise ValueError("Case evaluation must be an object")
    _require(value, CASE_GRADE_SCHEMA, selected, "Case evaluation")
    unknown: set[str] = set(value) - _CASE_GRADE_FIELDS
    if unknown:
        raise ValueError(f"Case evaluation carries unknown fields {sorted(unknown)}")
    attempts: object = value.get("attempts")
    if not isinstance(attempts, Sequence) or isinstance(attempts, str) or not attempts:
        raise ValueError("Case evaluation needs at least one attempt")
    return {
        "schema": CASE_GRADE_SCHEMA,
        "case_id": selected,
        "attempts": [_decoded_attempt(a, i, selected) for i, a in enumerate(attempts, start=1)],
    }


def _decoded_attempt(attempt: object, index: int, case_id: int) -> dict[str, Any]:
    """Validate one attempt inside a decoded envelope."""

    if not isinstance(attempt, Mapping):
        raise ValueError(f"attempt {index} must be an object")
    _require(attempt, CHECK_SCHEMA, case_id, f"attempt {index}")
    _require_verdict(attempt, f"attempt {index}")
    return dict(attempt)


def _require_verdict(attempt: Mapping[str, Any], label: str) -> None:
    """Every field the grade reads must be present and well-typed."""

    if not isinstance(attempt.get("answer"), str):
        raise ValueError(f"{label} must carry a text answer")
    for flag in _VERDICT_FLAGS:
        if not isinstance(attempt.get(flag), bool):
            raise ValueError(f"{label} must carry a boolean {flag}")
    support: object = attempt.get("support")
    # WHY `type(n) is int`: a JSON `true` is an int to Python, and would cite paragraph 1.
    if not isinstance(support, list) or not all(
        type(number) is int and number >= 0 for number in support
    ):
        raise ValueError(f"{label} support must be a list of paragraph numbers")


def _require(value: Mapping[str, Any], schema: str, case_id: int, label: str) -> None:
    """Refuse a record of another schema or another Case."""

    if value.get("schema") != schema:
        raise ValueError(f"{label} must carry schema {schema}")
    if value.get("case_id") != case_id:
        raise ValueError(f"{label} belongs to another Case")


def _positive(value: object, label: str) -> int:
    """Return ``value`` when it is a positive Case id, else refuse naming ``label``."""

    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"{label} must be a positive integer")
    return value


__all__ = [
    "CASE_GRADE_SCHEMA",
    "CHECK_SCHEMA",
    "build_case_grade",
    "decode_case_grade",
]
