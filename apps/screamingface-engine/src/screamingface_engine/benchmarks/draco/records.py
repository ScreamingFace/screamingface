"""Engine-bound DRACO Case and Check records carried through ordinary URL4 output."""

from __future__ import annotations

from screamingface_engine.benchmarks.case_records import build_case_record
from screamingface_engine.benchmarks.draco.validation import (
    require_positive_integer,
    require_text,
)
from screamingface_engine.benchmarks.grading_endpoints import CandidateAnswer

CASE_SCHEMA = "screamingface.draco-case-record.v1"
CHECK_SCHEMA = "screamingface.draco-check-record.v1"
_CRITERION_TYPES = frozenset({"positive", "negative"})


def case_record(
    raw_cases: str,
    *,
    case_id: int,
    candidate: CandidateAnswer,
) -> dict[str, object]:
    """Build evaluator text and exact Candidate outcome to one Engine-owned Case."""

    return build_case_record(
        raw_cases,
        case_id=case_id,
        candidate=candidate,
        schema=CASE_SCHEMA,
        benchmark="DRACO",
    )


def check_record(
    requirement: str,
    *,
    case_id: int,
    criterion_id: str,
    criterion_type: str,
) -> dict[str, object]:
    """Build one public criterion description to Engine-known Case identity."""

    selected_type = require_text(criterion_type, "criterion_type")
    if selected_type not in _CRITERION_TYPES:
        raise ValueError(f"unsupported DRACO criterion_type {selected_type!r}")
    return {
        "schema": CHECK_SCHEMA,
        "case_id": require_positive_integer(case_id, "case_id"),
        "criterion_id": require_text(criterion_id, "criterion_id"),
        "criterion_type": selected_type,
        "requirement": require_text(requirement, "criterion requirement"),
    }


__all__ = ["CASE_SCHEMA", "CHECK_SCHEMA", "case_record", "check_record"]
