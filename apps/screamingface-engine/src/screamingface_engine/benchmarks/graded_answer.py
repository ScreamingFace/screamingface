"""Outcome-preserving envelope between Candidate Invocation and Benchmark grading."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from screamingface_engine.benchmarks.contract import (
    CaseId,
    decode_candidate_invocation,
    validate_case_id,
)
from screamingface_engine.benchmarks.grading_endpoints import (
    CandidateAnswer,
    candidate_answer,
)

GRADED_ANSWER_SCHEMA = "screamingface.case-execution.v1"
_FIELDS = frozenset({"case_id", "candidate_invocation", "grading"})
# FEATURE (OME-1458): the N Attempts of one Case, each its own case-execution envelope, joined
# into one row so the per-Case fan-out still yields exactly one row per Case.
CASE_ATTEMPTS_SCHEMA = "screamingface.case-attempts.v1"


@dataclass(frozen=True, slots=True)
class GradedAnswer:
    """One preserved Candidate answer plus either grading output or a grading error."""

    case_id: CaseId
    candidate: CandidateAnswer
    grading: object | None
    error: Mapping[str, object] | None


def _decode_graded_answer(value: object) -> tuple[CaseId, CandidateAnswer, object]:
    """Decode one exact envelope into its Candidate outcome and grading outcome."""

    try:
        envelope = json.loads(value) if isinstance(value, str) else value
    except ValueError as exc:
        raise ValueError(f"Case execution must be JSON: {exc}") from None
    if not isinstance(envelope, Mapping):
        raise ValueError("Case execution must be a JSON object")
    if set(envelope) != {"schema", *_FIELDS} or envelope.get("schema") != GRADED_ANSWER_SCHEMA:
        raise ValueError("Case execution has an invalid shape or schema")
    case_id = validate_case_id(envelope.get("case_id"))
    assert case_id is not None
    invocation = envelope.get("candidate_invocation")
    grading = envelope.get("grading")
    if not isinstance(invocation, str):
        raise ValueError("Case execution Candidate Invocation must be JSON text")
    candidate = candidate_answer(invocation)
    if isinstance(grading, str | bytes) or not isinstance(grading, Sequence) or len(grading) != 1:
        raise ValueError("Case execution grading must contain exactly one outcome")
    return case_id, candidate, grading[0]


def graded_answer_payload(
    case_id: CaseId,
    candidate_invocation: str,
    grading: Sequence[object],
) -> dict[str, object]:
    """Construct one exact envelope for endpoints and conformance fixtures."""

    selected_case_id = validate_case_id(case_id)
    assert selected_case_id is not None
    decode_candidate_invocation(candidate_invocation)
    if isinstance(grading, str | bytes) or len(grading) != 1:
        raise ValueError("Case execution grading must contain exactly one outcome")
    return {
        "schema": GRADED_ANSWER_SCHEMA,
        "case_id": selected_case_id,
        "candidate_invocation": candidate_invocation,
        "grading": list(grading),
    }


def graded_answer(value: object) -> GradedAnswer:
    """Decode the shared envelope without interpreting Benchmark-owned grading data."""

    case_id, candidate, grading = _decode_graded_answer(value)
    if isinstance(grading, Mapping) and "error" in grading:
        error = grading["error"]
        if set(grading) != {"error"} or not isinstance(error, Mapping):
            raise ValueError("Case execution grading error has an invalid shape")
        return GradedAnswer(
            case_id=case_id,
            candidate=candidate,
            grading=None,
            error=dict(error),
        )
    return GradedAnswer(
        case_id=case_id,
        candidate=candidate,
        grading=grading,
        error=None,
    )


def graded_answer_matches(outcome: GradedAnswer, expected_case_id: CaseId) -> bool:
    """Match URL4-carried integer ids without weakening genuine string identities."""

    return outcome.case_id == expected_case_id or (
        isinstance(expected_case_id, int)
        and not isinstance(expected_case_id, bool)
        and isinstance(outcome.case_id, str)
        and outcome.case_id == str(expected_case_id)
    )


def case_attempts(value: object) -> tuple[CaseId, list[object]] | None:
    """Decode a Case's Attempts envelope into its id and per-Attempt rows; None if not one.

    Each row is that Attempt's case-execution envelope, opaque here, read by the same reader
    that files a one-Attempt Case. None means the value is some other row (an ordinary
    case-execution envelope, or a collected error), which the caller files as before.
    """

    if not isinstance(value, Mapping) or value.get("schema") != CASE_ATTEMPTS_SCHEMA:
        return None
    if set(value) != {"schema", "case_id", "attempts"}:
        raise ValueError("Case attempts envelope has an invalid shape")
    case_id = validate_case_id(value.get("case_id"))
    assert case_id is not None
    attempts: object = value.get("attempts")
    if isinstance(attempts, str | bytes) or not isinstance(attempts, Sequence) or len(attempts) < 2:
        raise ValueError("Case attempts envelope must carry at least two attempts")
    return case_id, list(attempts)


__all__ = [
    "CASE_ATTEMPTS_SCHEMA",
    "case_attempts",
    "GRADED_ANSWER_SCHEMA",
    "GradedAnswer",
    "graded_answer_matches",
    "graded_answer_payload",
    "graded_answer",
]
