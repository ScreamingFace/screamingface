"""Engine-bound HealthBench Case and Rubric records carried through ordinary URL4 output."""

from __future__ import annotations

from screamingface_engine.benchmarks.case_records import build_case_record
from screamingface_engine.benchmarks.grading_endpoints import CandidateAnswer

CASE_SCHEMA = "screamingface.healthbench-case-record.v1"
RUBRIC_SCHEMA = "screamingface.healthbench-rubric-record.v1"


def bind_case(
    raw_cases: str,
    *,
    case_id: int,
    candidate: CandidateAnswer,
) -> dict[str, object]:
    """Bind evaluator text and exact Candidate outcome to one Engine-owned Case."""

    return build_case_record(
        raw_cases,
        case_id=case_id,
        candidate=candidate,
        schema=CASE_SCHEMA,
        benchmark="HealthBench",
    )


def bind_rubric_item(
    rubric_item: str,
    *,
    case_id: int,
    rubric_id: int,
) -> dict[str, object]:
    """Bind one rendered ``[points] criterion`` line to Engine-known identities.

    WHY: the judge sees points in the rendered item (the official template's own
    examples reference negative point values) — there is no weight-blinding here,
    unlike DRACO. The numeric points still live ONLY in the private rubric assets;
    the aggregate reads them there, never from anything a model produced.
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
    selected = _optional_case_id(value)
    if selected is None or selected < 1:
        raise ValueError("case_id must be a positive integer")
    return selected


def _optional_case_id(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        return None
    try:
        return int(value)
    except ValueError:
        return None


def _text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be non-empty text")
    return value


__all__ = ["CASE_SCHEMA", "RUBRIC_SCHEMA", "bind_case", "bind_rubric_item"]
