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
from screamingface_engine.benchmarks.evaluation import (
    CandidateAnswer,
    benchmark_unavailable,
    candidate_answer,
    compact_json,
)
from screamingface_engine.benchmarks.run_logs import record_successful_case_execution
from url4.peer.server import Request, Url4Node

CASE_EXECUTION_ROUTE = "/benchmarks/case-execution"
CASE_EXECUTION_SCHEMA = "screamingface.case-execution.v1"
_FIELDS = frozenset({"case_id", "candidate_invocation", "grading"})


@dataclass(frozen=True, slots=True)
class CaseExecutionOutcome:
    """One preserved Candidate answer plus either grading output or a grading error."""

    case_id: CaseId
    candidate: CandidateAnswer
    grading: object | None
    error: Mapping[str, object] | None


def install_case_execution(node: Url4Node) -> None:
    """Install the shared envelope route once in every Benchmark Runner world."""

    node.endpoint(CASE_EXECUTION_ROUTE)(_case_execution)


def _decode_case_execution(value: object) -> tuple[CaseId, CandidateAnswer, object]:
    """Decode one exact envelope into its Candidate outcome and grading outcome."""

    try:
        envelope = json.loads(value) if isinstance(value, str) else value
    except ValueError as exc:
        raise ValueError(f"Case execution must be JSON: {exc}") from None
    if not isinstance(envelope, Mapping):
        raise ValueError("Case execution must be a JSON object")
    if set(envelope) != {"schema", *_FIELDS} or envelope.get("schema") != CASE_EXECUTION_SCHEMA:
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


def case_execution_payload(
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
        "schema": CASE_EXECUTION_SCHEMA,
        "case_id": selected_case_id,
        "candidate_invocation": candidate_invocation,
        "grading": list(grading),
    }


def case_execution_outcome(value: object) -> CaseExecutionOutcome:
    """Decode the shared envelope without interpreting Benchmark-owned grading data."""

    case_id, candidate, grading = _decode_case_execution(value)
    if isinstance(grading, Mapping) and "error" in grading:
        error = grading["error"]
        if set(grading) != {"error"} or not isinstance(error, Mapping):
            raise ValueError("Case execution grading error has an invalid shape")
        return CaseExecutionOutcome(
            case_id=case_id,
            candidate=candidate,
            grading=None,
            error=dict(error),
        )
    return CaseExecutionOutcome(
        case_id=case_id,
        candidate=candidate,
        grading=grading,
        error=None,
    )


def case_execution_matches(outcome: CaseExecutionOutcome, expected_case_id: CaseId) -> bool:
    """Match URL4-carried integer ids without weakening genuine string identities."""

    return outcome.case_id == expected_case_id or (
        isinstance(expected_case_id, int)
        and not isinstance(expected_case_id, bool)
        and isinstance(outcome.case_id, str)
        and outcome.case_id == str(expected_case_id)
    )


def _case_execution(request: Request) -> str:
    try:
        payload = json.loads(request.context)
        if not isinstance(payload, Mapping):
            raise ValueError("Case execution context must be a JSON object")
        if set(payload) != _FIELDS:
            raise ValueError(
                "Case execution context must carry case_id, candidate_invocation, and grading"
            )
        case_id = validate_case_id(payload["case_id"])
        assert case_id is not None
        invocation = payload["candidate_invocation"]
        grading = payload["grading"]
        if not isinstance(invocation, str):
            raise ValueError("Case execution Candidate Invocation must be JSON text")
        if isinstance(grading, str):
            grading = json.loads(grading)
        if (
            isinstance(grading, str | bytes)
            or not isinstance(grading, Sequence)
            or len(grading) != 1
        ):
            raise ValueError("Case execution grading must contain exactly one outcome")
    except (TypeError, ValueError) as exc:
        raise benchmark_unavailable(str(exc)) from exc
    result = compact_json(case_execution_payload(case_id, invocation, grading))
    record_successful_case_execution(result)
    return result


__all__ = [
    "CASE_EXECUTION_ROUTE",
    "CASE_EXECUTION_SCHEMA",
    "CaseExecutionOutcome",
    "case_execution_matches",
    "case_execution_payload",
    "case_execution_outcome",
    "install_case_execution",
]
