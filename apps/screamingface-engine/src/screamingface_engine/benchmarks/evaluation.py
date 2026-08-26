"""Installed URL4 evaluation capabilities shared by Engine-owned Benchmarks."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from screamingface_engine.benchmarks.contract import (
    CandidateInvocationStatus,
    CorrectiveExecution,
    OperationOutput,
    decode_candidate_invocation_record,
)
from url4.core.errors import ResolutionError
from url4.peer.server import Request

JsonObject = dict[str, Any]
CaseEvaluationBinder = Callable[[int, list[JsonObject]], JsonObject]
AggregateAdapter = Callable[[str, int], JsonObject]


@dataclass(frozen=True, slots=True)
class CandidateAnswer:
    """One Candidate Invocation with evaluator text and exact public outcome fields."""

    status: CandidateInvocationStatus
    text: str
    output: str | None
    finish_reason: str | None
    refusal: str | None
    execution: CorrectiveExecution | None
    operations: tuple[OperationOutput, ...] | None = None


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
    )


def case_evaluation_endpoint(
    *,
    label: str,
    item_name: str,
    bind: CaseEvaluationBinder,
    error_context_head: int | None = None,
) -> Callable[[Request], str]:
    """Adapt one non-empty collection of evaluator records into a Case envelope route."""

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
            raise benchmark_unavailable(detail) from exc
        return compact_json(result)

    return endpoint


def aggregate_endpoint(
    *,
    label: str,
    available_case_count: int,
    aggregate: AggregateAdapter,
) -> Callable[[Request], str]:
    """Adapt ordered Case evaluations and their exact selection into Aggregation."""

    positive_count(available_case_count, "available_case_count")

    def endpoint(request: Request) -> str:
        selected_case_count = _aggregate_selection(request.intent, available_case_count, label)
        try:
            result = aggregate(request.context, selected_case_count)
        except (OSError, ValueError) as exc:
            raise benchmark_unavailable(str(exc)) from exc
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
        raise benchmark_unavailable(f"{label} must be a JSON object")
    return decoded


def json_array(value: object, label: str) -> list[object]:
    """Decode a URL4 value that must be one JSON array."""

    decoded = _decode_json(value, label)
    if not isinstance(decoded, list):
        raise benchmark_unavailable(f"{label} must be a JSON array")
    return decoded


def _decode_json(value: object, label: str) -> object:
    if not isinstance(value, str):
        return value
    try:
        return json.loads(value)
    except ValueError as exc:
        raise benchmark_unavailable(f"{label} must be JSON: {exc}") from exc


def compact_json(value: object) -> str:
    """Encode a deterministic endpoint result without ASCII loss or padding."""

    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _raise_collected_failure(decoded: JsonObject, item_label: str) -> None:
    """Re-raise a url4 collected-error row as its original failure.

    INVARIANT: the detection mirrors the case-execution decoder's strictness — ONLY the
    exact one-key ``{"error": {...}}`` shape is a collected failure; anything else stays
    an evaluator record for the binder to validate. The re-raised error keeps the row's
    ``code`` and ``retryable`` (present since OME-924's url4 change) so retryability
    survives to the public CaseResult; a lean row (kind+message only) defaults to a
    retryable ``grading_dependency_failed``. With OME-924's fail-fast fan-outs an
    error row should no longer reach this route for the built-in benchmarks — this
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


def _aggregate_selection(intent: str, available: int, label: str) -> int:
    operation, separator, raw_count = intent.partition(":")
    if operation != "aggregate" or not separator:
        raise _unsupported(label, intent)
    try:
        selected_case_count = int(raw_count)
        positive_count(selected_case_count, "selected_case_count")
    except ValueError as exc:
        raise benchmark_unavailable(str(exc)) from exc
    if selected_case_count > available:
        raise benchmark_unavailable(
            f"selected_case_count cannot exceed available_case_count ({available})"
        )
    return selected_case_count


def _unsupported(label: str, intent: str) -> ResolutionError:
    return ResolutionError(
        f"unsupported {label} operation {intent!r}",
        code="benchmark_operation_unsupported",
        permanent=True,
    )


def positive_count(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"{label} must be a positive integer")
    return value


__all__ = [
    "CandidateAnswer",
    "aggregate_endpoint",
    "benchmark_unavailable",
    "candidate_answer",
    "case_evaluation_endpoint",
    "compact_json",
    "json_array",
    "json_object",
    "positive_case_id",
    "positive_count",
]
