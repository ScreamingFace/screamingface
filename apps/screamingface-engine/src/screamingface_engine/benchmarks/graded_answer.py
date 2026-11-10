"""Outcome-preserving envelope between Candidate Invocation and Benchmark grading."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from screamingface_engine.benchmarks.case_grading_report import report_case_grading
from screamingface_engine.benchmarks.case_result_store import (
    CaseResultStoreError,
    bound_case_results,
)
from screamingface_engine.benchmarks.contract import (
    CaseId,
    decode_candidate_invocation,
    validate_case_id,
)
from screamingface_engine.benchmarks.failure_classes import (
    benchmark_contract_error as _contract_error,
)
from screamingface_engine.benchmarks.grading_endpoints import (
    CandidateAnswer,
    candidate_answer,
    compact_json,
)
from url4.peer.server import Request, Url4Node

GRADED_ANSWER_ROUTE = "/benchmarks/case-execution"
GRADED_ANSWER_SCHEMA = "screamingface.case-execution.v1"
_FIELDS = frozenset({"case_id", "candidate_invocation", "grading"})
# FEATURE (OME-1458): the N Attempts of one Case, each its own case-execution envelope, joined
# into one row so the per-Case fan-out still yields exactly one row per Case.
CASE_ATTEMPTS_ROUTE = "/benchmarks/case-attempts"
CASE_ATTEMPTS_SCHEMA = "screamingface.case-attempts.v1"
# FEATURE (OME-1833): what the route hands url4 when the run has a Case-result store, e.g.
# {"schema":"screamingface.case-execution-ref.v1","case_id":7,"key":"6"} (~90 B, not ~12.5 KB).
CASE_EXECUTION_REF_SCHEMA = "screamingface.case-execution-ref.v1"
_REF_FIELDS = frozenset({"schema", "case_id", "key"})


@dataclass(frozen=True, slots=True)
class GradedAnswer:
    """One preserved Candidate answer plus either grading output or a grading error."""

    case_id: CaseId
    # None only for a graded row read back from the Case-result store, which is parked
    # without its Candidate Invocation (OME-1833). Every grading error keeps it.
    candidate: CandidateAnswer | None
    grading: object | None
    error: Mapping[str, object] | None


def install_graded_answer_endpoint(node: Url4Node) -> None:
    """Install the shared envelope route once in every Benchmark Runner world."""

    node.endpoint(GRADED_ANSWER_ROUTE)(_graded_answer_route)
    node.endpoint(CASE_ATTEMPTS_ROUTE)(_case_attempts_route)


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
    """Decode the shared envelope without interpreting Benchmark-owned grading data.

    A reference row (OME-1833) is resolved through the run's Case-result store first. This is
    the one decoder of a case-execution row, so every reader (the aggregate, the Attempts
    join, an early per-Case grade) resolves references without knowing they exist.
    """

    reference: Mapping[str, object] | None = _reference(value)
    if reference is not None:
        return _stored_graded_answer(reference)
    case_id, candidate, grading = _decode_graded_answer(value)
    return _outcome(case_id, candidate, grading)


def _outcome(case_id: CaseId, candidate: CandidateAnswer | None, grading: object) -> GradedAnswer:
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


def _graded_answer_route(request: Request) -> str:
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
        raise _contract_error(str(exc)) from exc
    envelope: dict[str, object] = graded_answer_payload(case_id, invocation, grading)
    failed = isinstance(grading[0], Mapping) and "error" in grading[0]
    report_case_grading(case_id, "failed" if failed else "completed")
    store = bound_case_results()
    if store is None:
        # WHY inline without a store: a test, a remote peer or a world outside a run keeps
        # today's envelope byte for byte.
        return compact_json(envelope)
    # WHY drop the Candidate Invocation from a graded row: the grading already re-records the
    # answer, and only a grading error is read with its Candidate (OME-1833 dedup).
    parked: dict[str, object] = (
        envelope
        if failed
        else {name: value for name, value in envelope.items() if name != "candidate_invocation"}
    )
    key: str = store.append(parked)
    return compact_json({"schema": CASE_EXECUTION_REF_SCHEMA, "case_id": case_id, "key": key})


def _reference(value: object) -> Mapping[str, object] | None:
    """The reference row ``value`` is, or None for anything else (an inline envelope)."""

    decoded: object = value
    # WHY a cheap prefix test first: an inline envelope is large JSON text, and decoding it
    # twice just to learn it is not a reference would double the reader's work.
    if isinstance(value, str) and CASE_EXECUTION_REF_SCHEMA in value[:80]:
        try:
            decoded = json.loads(value)
        except ValueError:
            decoded = None
    if not isinstance(decoded, Mapping) or decoded.get("schema") != CASE_EXECUTION_REF_SCHEMA:
        return None
    if set(decoded) != _REF_FIELDS or not isinstance(decoded.get("key"), str):
        raise ValueError("Case execution reference has an invalid shape")
    return decoded


def _stored_graded_answer(reference: Mapping[str, object]) -> GradedAnswer:
    """Resolve one reference to the envelope its route parked; fail closed on anything else.

    INVARIANT: a reference resolves to its own Case's row or raises ``CaseResultStoreError``.
    It never resolves to an empty row or to another Case's row.
    """

    store = bound_case_results()
    if store is None:
        raise CaseResultStoreError("no Case-result store is bound to resolve this reference")
    claimed: object = reference.get("case_id")
    if not isinstance(claimed, int | str):
        raise ValueError("Case execution reference must name its Case")
    case_id = validate_case_id(claimed)
    record: dict[str, object] = store.read(str(reference["key"]))
    if record.get("schema") != GRADED_ANSWER_SCHEMA or not {"schema", "case_id", "grading"} <= set(
        record
    ) <= {"schema", *_FIELDS}:
        raise CaseResultStoreError("parked Case execution has an invalid shape")
    if record.get("case_id") != case_id:
        raise CaseResultStoreError("parked Case execution belongs to another Case")
    grading: object = record["grading"]
    if isinstance(grading, str | bytes) or not isinstance(grading, Sequence) or len(grading) != 1:
        raise CaseResultStoreError("parked Case execution grading must hold one outcome")
    invocation: object = record.get("candidate_invocation")
    if invocation is not None and not isinstance(invocation, str):
        raise CaseResultStoreError("parked Candidate Invocation must be JSON text")
    assert case_id is not None
    candidate: CandidateAnswer | None = None if invocation is None else candidate_answer(invocation)
    outcome: GradedAnswer = _outcome(case_id, candidate, grading[0])
    if outcome.error is not None and outcome.candidate is None:
        raise CaseResultStoreError("a parked grading error lost its Candidate Invocation")
    return outcome


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


def _case_attempts_route(request: Request) -> str:
    """Join one Case's ``attempt_1..attempt_N`` rows into one Attempts row, in order.

    Each Attempt arrives as the one-row list its collecting iterate produced (2026-11-10,
    ``protocol._attempted_case``): the case-execution envelope, or ``{"error": {...}}`` when
    the Attempt's Candidate call errored. The row is kept as it came; the marking room files an
    error row as a failed Attempt by the error's code.
    """

    try:
        payload = json.loads(request.context)
        if not isinstance(payload, Mapping) or "case_id" not in payload:
            raise ValueError("Case attempts context must be a JSON object carrying case_id")
        case_id = validate_case_id(payload["case_id"])
        assert case_id is not None
        names: list[str] = [name for name in payload if name != "case_id"]
        expected: list[str] = [f"attempt_{index}" for index in range(1, len(names) + 1)]
        if len(names) < 2 or names != expected:
            raise ValueError("Case attempts context must carry attempt_1..attempt_N, N >= 2")
        attempts: list[object] = [
            _attempt_row(name, json.loads(value) if isinstance(value, str) else value)
            for name, value in ((name, payload[name]) for name in names)
        ]
    except (TypeError, ValueError) as exc:
        raise _contract_error(str(exc)) from exc
    return compact_json({"schema": CASE_ATTEMPTS_SCHEMA, "case_id": case_id, "attempts": attempts})


def _attempt_row(name: str, value: object) -> object:
    """The one row an Attempt's collecting iterate produced, out of its list."""

    if isinstance(value, Sequence) and not isinstance(value, str | bytes) and len(value) == 1:
        return value[0]
    raise ValueError(f"Case attempts context's {name} must carry exactly one row")


__all__ = [
    "CASE_EXECUTION_REF_SCHEMA",
    "CASE_ATTEMPTS_ROUTE",
    "CASE_ATTEMPTS_SCHEMA",
    "case_attempts",
    "GRADED_ANSWER_ROUTE",
    "GRADED_ANSWER_SCHEMA",
    "GradedAnswer",
    "graded_answer_matches",
    "graded_answer_payload",
    "graded_answer",
    "install_graded_answer_endpoint",
]
