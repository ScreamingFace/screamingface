"""Outcome-preserving envelope between Candidate Invocation and Benchmark grading."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence

from screamingface_engine.benchmarks.case_execution_contract import (
    CASE_EXECUTION_SCHEMA,
    CaseExecutionObservation,
    CaseExecutionOutcome,
    case_execution_matches,
    case_execution_outcome,
)
from screamingface_engine.benchmarks.contract import (
    CaseId,
    decode_candidate_invocation,
    validate_case_id,
)
from screamingface_engine.benchmarks.evaluation import (
    benchmark_unavailable,
    compact_json,
)
from screamingface_engine.benchmarks.run_logs import record_successful_case_execution
from url4.peer.server import Request, Url4Node

CASE_EXECUTION_ROUTE = "/benchmarks/case-execution"
_FIELDS = frozenset({"case_id", "candidate_invocation", "grading"})


def install_case_execution(node: Url4Node) -> None:
    """Install the shared envelope route once in every Benchmark Runner world."""

    node.endpoint(CASE_EXECUTION_ROUTE)(_case_execution)


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
    _observe_terminal(result)
    return result


def _observe_terminal(result: str) -> None:
    """Notify progress only when the authoritative return also decodes as a terminal."""

    try:
        observation = CaseExecutionObservation(raw=result, outcome=case_execution_outcome(result))
    except (TypeError, ValueError):
        # WHY silent: the exact Case return is authoritative. Progress decoding is observational
        # and may neither replace that value nor leak malformed private grading material.
        pass
    else:
        record_successful_case_execution(observation)


__all__ = [
    "CASE_EXECUTION_ROUTE",
    "CASE_EXECUTION_SCHEMA",
    "CaseExecutionObservation",
    "CaseExecutionOutcome",
    "case_execution_matches",
    "case_execution_payload",
    "case_execution_outcome",
    "install_case_execution",
]
