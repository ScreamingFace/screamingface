"""Engine-bound GDPval Case and rubric records, carried through ordinary URL4 output."""

from __future__ import annotations

from screamingface_engine.benchmarks.case_records import bind_case_record
from screamingface_engine.benchmarks.evaluation import CandidateAnswer

CASE_SCHEMA = "screamingface.gdpval-case-record.v1"
RUBRIC_SCHEMA = "screamingface.gdpval-rubric-record.v1"


def bind_case(
    raw_cases: str,
    *,
    case_id: int,
    candidate: CandidateAnswer,
) -> dict[str, object]:
    """Bind the work request and the exact Candidate outcome to one Engine-owned Case."""

    return bind_case_record(
        raw_cases,
        case_id=case_id,
        candidate=candidate,
        schema=CASE_SCHEMA,
        benchmark="GDPval",
    )


def bind_rubric_item(rubric_item: str, *, case_id: int, rubric_id: int) -> dict[str, object]:
    """Bind one rendered ``[points] criterion`` line to Engine-known identities.

    INVARIANT: the numeric points live ONLY in the private rubric assets. This record carries the
    rendered line for audit; the aggregate reads points from disk, never from anything that has
    passed through a model.
    """

    if isinstance(rubric_id, bool) or not isinstance(rubric_id, int) or rubric_id < 1:
        raise ValueError("rubric_id must be a positive integer")
    return {
        "schema": RUBRIC_SCHEMA,
        "case_id": _case_id(case_id),
        "rubric_id": rubric_id,
        "rubric_item": _text(rubric_item, "rubric_item"),
    }


def _case_id(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int | str):
        raise ValueError("case_id must be a positive integer")
    try:
        selected = int(value)
    except ValueError:
        raise ValueError("case_id must be a positive integer") from None
    if selected < 1:
        raise ValueError("case_id must be a positive integer")
    return selected


def _text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be non-empty text")
    return value


__all__ = ["CASE_SCHEMA", "RUBRIC_SCHEMA", "bind_case", "bind_rubric_item"]
