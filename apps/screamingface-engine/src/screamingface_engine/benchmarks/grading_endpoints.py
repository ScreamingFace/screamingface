"""Installed URL4 evaluation capabilities shared by Engine-owned Benchmarks."""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from screamingface_engine.activity_kinds import ActivityKind
from screamingface_engine.benchmarks.contract import (
    CandidateInvocationStatus,
    CorrectiveLoopOutcome,
    OperationOutput,
    decode_candidate_invocation_record,
)
from screamingface_engine.benchmarks.failure_classes import (
    benchmark_contract_error,
)
from screamingface_engine.benchmarks.phases import observe_phase
from url4.core.errors import ResolutionError
from url4.peer.server import Request

JsonObject = dict[str, Any]
CaseGradeBuilder = Callable[[int, list[JsonObject]], JsonObject]
#: The async face (OME-1240): a judged benchmark's adapter awaits model calls, so its
#: code must be awaited by the node on the RUN's own loop — see case_evaluation.aggregate_code.
AsyncAggregateAdapter = Callable[[str, int], Awaitable[JsonObject]]


@dataclass(frozen=True, slots=True)
class CandidateAnswer:
    """One Candidate Invocation with evaluator text and exact public outcome fields."""

    status: CandidateInvocationStatus
    text: str
    output: str | None
    finish_reason: str | None
    refusal: str | None
    execution: CorrectiveLoopOutcome | None
    operations: tuple[OperationOutput, ...] | None = None
    abstained: bool = False


def candidate_answer(value: str) -> CandidateAnswer:
    """Decode one invocation; refusals remain ordinary Benchmark-checkable text."""

    invocation = decode_candidate_invocation_record(value)
    return CandidateAnswer(
        status=invocation.status,
        text=invocation.refusal or invocation.output,
        output=invocation.output if invocation.status == "completed" else None,
        finish_reason=invocation.finish_reason,
        refusal=invocation.refusal,
        execution=invocation.execution,
        operations=None if invocation.operations is None else tuple(invocation.operations),
        abstained=invocation.abstained,
    )


def case_grade_endpoint(
    *,
    label: str,
    item_name: str,
    bind: CaseGradeBuilder,
    error_context_head: int | None = None,
) -> Callable[[Request], str]:
    """Adapt one non-empty collection of evaluator records into a Case envelope route."""

    @observe_phase(ActivityKind.GRADING)
    def endpoint(request: Request) -> str:
        try:
            case_id = positive_case_id(request.intent)
            raw_items = json_array(request.context, label)
            if not raw_items:
                raise ValueError(f"{label} must be a non-empty JSON array")
            items = []
            for index, item in enumerate(raw_items, start=1):
                decoded = json_object(item, f"{item_name} {index}")
                # WHY (OME-993, GH #740): a one-key `{"error": ...}` item is url4's
                # `on_error=collect` capture of an UPSTREAM failure (e.g. a Judge call
                # that 429'd or ran out of tokens) — re-raise that original cause here.
                # Treating it as an evaluator record would reject its SHAPE instead
                # ("invalid Criterion envelope"), burying the real failure.
                _raise_collected_failure(decoded, f"{item_name} {index}")
                items.append(decoded)
            result = bind(case_id, items)
        except (OSError, TypeError, ValueError) as exc:
            detail = str(exc)
            if error_context_head is not None:
                detail += f"; context head: {request.context[:error_context_head]!r}"
            raise benchmark_contract_error(detail) from exc
        return compact_json(result)

    return endpoint


def positive_case_id(value: object) -> int:
    """One shared definition of the positive integer Case identity used by built-ins."""

    if isinstance(value, bool) or not isinstance(value, int | str):
        raise ValueError("case_id must be a positive integer")
    try:
        selected = int(value)
    except ValueError:
        raise ValueError("case_id must be a positive integer") from None
    if selected < 1:
        raise ValueError("case_id must be a positive integer")
    return selected


def json_object(value: object, label: str) -> JsonObject:
    """Decode a URL4 value that must be one JSON object."""

    decoded = _decode_json(value, label)
    if not isinstance(decoded, dict):
        raise benchmark_contract_error(f"{label} must be a JSON object")
    return decoded


def json_array(value: object, label: str) -> list[object]:
    """Decode a URL4 value that must be one JSON array."""

    decoded = _decode_json(value, label)
    if not isinstance(decoded, list):
        raise benchmark_contract_error(f"{label} must be a JSON array")
    return decoded


def _decode_json(value: object, label: str) -> object:
    if not isinstance(value, str):
        return value
    try:
        return json.loads(value)
    except ValueError as exc:
        raise benchmark_contract_error(f"{label} must be JSON: {exc}") from exc


def compact_json(value: object) -> str:
    """Encode a deterministic endpoint result without ASCII loss or padding."""

    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _raise_collected_failure(decoded: JsonObject, item_label: str) -> None:
    """Re-raise a url4 collected-error case as its original failure.

    INVARIANT: the detection mirrors the case-execution decoder's strictness — ONLY the
    exact one-key ``{"error": {...}}`` shape is a collected failure; anything else stays
    an evaluator record for the binder to validate. The re-raised error keeps the row's
    ``code`` and ``retryable`` (present since OME-924's url4 change) so retryability
    survives to the public CaseResult; a lean row (kind+message only) defaults to a
    retryable ``grading_dependency_failed``. With OME-924's fail-fast fan-outs an
    error case should no longer reach this route for the built-in benchmarks — this
    seam is the belt-and-braces guard for any other collect boundary.
    """
    if set(decoded) != {"error"}:
        return
    error = decoded.get("error")
    if not isinstance(error, dict):
        return
    kind = error.get("kind")
    message = error.get("message")
    detail = message if isinstance(message, str) and message.strip() else str(kind or "unknown")
    code = error.get("code")
    retryable = error.get("retryable")
    raise ResolutionError(
        f"{item_label} failed upstream: {detail}",
        code=code if isinstance(code, str) and code else "grading_dependency_failed",
        permanent=(not retryable) if isinstance(retryable, bool) else False,
    )


def benchmark_unavailable(detail: str) -> ResolutionError:
    """The bounded public failure for unavailable Benchmark assets or adapters."""

    return ResolutionError(detail, code="benchmark_unavailable", permanent=True)


def positive_count(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"{label} must be a positive integer")
    return value


__all__ = [
    "CandidateAnswer",
    "benchmark_unavailable",
    "candidate_answer",
    "case_grade_endpoint",
    "compact_json",
    "json_array",
    "json_object",
    "positive_case_id",
    "positive_count",
]
