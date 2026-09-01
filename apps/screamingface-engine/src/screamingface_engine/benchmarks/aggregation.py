"""Cross-Benchmark Candidate finalization and score publication policy."""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
)

from screamingface_engine.benchmarks.contract import (
    CandidateResult,
    CaseGrade,
    CaseId,
    CaseResult,
    CorrectiveExecution,
    Failure,
    OperationOutput,
    candidate_coverage,
    validate_case_id,
)
from screamingface_engine.benchmarks.evaluation import CandidateAnswer
from screamingface_engine.grading_accounting import reconcile_candidate_grading_accounting


class SelectedCase(BaseModel):
    """One immutable public Case selected by the Benchmark protocol."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    case_id: CaseId
    input: str = Field(min_length=1)
    metadata: dict[str, Any]

    @field_validator("case_id")
    @classmethod
    def _validate_case_id(cls, value: CaseId) -> CaseId:
        validated = validate_case_id(value)
        assert validated is not None
        return validated


@dataclass(frozen=True, slots=True)
class PublicError:
    """Safe operational diagnostics suitable for the public result contract."""

    kind: str | None
    code: str
    message: str
    retryable: bool | None


@dataclass(frozen=True, slots=True)
class CandidateScore:
    """A Benchmark scorer's result over the finalizer's gradeable Case subset."""

    # HealthBench's official penalty-bearing result can be negative.
    score: float
    metrics: dict[str, Any]


Scorer = Callable[[Sequence[CaseResult]], CandidateScore]


def finalize_candidate_result(
    *,
    benchmark_id: str,
    benchmark_revision: str,
    selected_cases: Sequence[SelectedCase | Mapping[str, Any]],
    cases: Sequence[CaseResult | Mapping[str, Any]],
    scorer: Scorer,
    failures: Sequence[Failure | Mapping[str, Any]] = (),
) -> CandidateResult:
    """Preserve Cases and score exactly the subset carrying numeric Benchmark grades."""

    selection = [
        case if isinstance(case, SelectedCase) else SelectedCase.model_validate(case)
        for case in selected_cases
    ]
    produced_cases = [
        case if isinstance(case, CaseResult) else CaseResult.model_validate(case) for case in cases
    ]
    typed_failures = [
        failure if isinstance(failure, Failure) else Failure.model_validate(failure)
        for failure in failures
    ]
    selected_ids = [case.case_id for case in selection]
    if len(selected_ids) != len(set(selected_ids)):
        raise ValueError("selected Case sequence cannot contain duplicate case_id values")
    produced_ids = [case.case_id for case in produced_cases]
    if len(produced_ids) != len(set(produced_ids)):
        raise ValueError("CandidateResult cannot contain duplicate case_id values")
    unexpected = set(produced_ids) - set(selected_ids)
    if unexpected:
        raise ValueError(
            f"CandidateResult contains unselected case_id values {sorted(unexpected, key=str)!r}"
        )
    produced_by_id = {case.case_id: case for case in produced_cases}
    typed_cases = [
        produced_by_id.get(selected.case_id)
        or CaseResult(
            status="failed",
            case_id=selected.case_id,
            input=selected.input,
            output=None,
            finish_reason=None,
            refusal=None,
            grade=None,
            failures=[
                Failure(
                    stage="aggregation",
                    code="case_result_missing",
                    message="the selected Case produced no Case Result",
                    retryable=None,
                    case_id=selected.case_id,
                    metadata={},
                )
            ],
            metadata=selected.metadata,
        )
        for selected in selection
    ]

    gradeable = tuple(
        case for case in typed_cases if case.grade is not None and case.grade.score is not None
    )
    scored = scorer(gradeable) if gradeable else None
    result = CandidateResult(
        benchmark_id=benchmark_id,
        benchmark_revision=benchmark_revision,
        case_count=len(typed_cases),
        score=scored.score if scored is not None else None,
        coverage=candidate_coverage(typed_cases, len(typed_cases)),
        metrics=scored.metrics if scored is not None else {},
        cases=typed_cases,
        failures=typed_failures,
    )
    reconcile_candidate_grading_accounting(result)
    return result


def public_error(
    error: Mapping[str, Any],
    *,
    default_code: str,
    default_message: str,
) -> PublicError:
    """Retain useful error fields without publishing runner internals or credentials."""

    kind = _public_identifier(error.get("kind"))
    code = _public_identifier(error.get("code")) or default_code
    message = _public_message(error.get("message"), default=default_message)
    retryable = error.get("retryable")
    if not isinstance(retryable, bool):
        permanent = error.get("permanent")
        retryable = not permanent if isinstance(permanent, bool) else None
    return PublicError(kind=kind, code=code, message=message, retryable=retryable)


def _public_identifier(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()[:80]
    return normalized if re.fullmatch(r"[A-Za-z0-9_.:-]+", normalized) else None


def _public_message(value: object, *, default: str) -> str:
    if not isinstance(value, str) or not value.strip():
        return default
    normalized = " ".join(value.split())[:200]
    lowered = normalized.casefold()
    internal_markers = (
        "traceback (most recent call last)",
        'file "',
        "/users/",
        "/private/",
        "/tmp/",
        "/var/",
        "/home/",
    )
    return (
        default
        if any(marker in lowered for marker in internal_markers)
        or any(pattern.search(normalized) for pattern in _SENSITIVE_ERROR_PATTERNS)
        else normalized
    )


_SENSITIVE_ERROR_PATTERNS = (
    # Absolute/relative POSIX, drive-letter Windows, and UNC paths. Public
    # diagnostics retain the bounded default instead of trying to redact an
    # unbounded path grammar piecemeal.
    re.compile(r"(?i)(?:^|[\s'\"(])(?:/|\.{1,2}/)[^\s'\")]+"),
    re.compile(r"(?i)(?:^|[\s'\"(])[a-z]:\\[^\s'\")]+"),
    re.compile(r"(?i)(?:^|[\s'\"(])\\\\[^\\\s]+\\[^\s'\")]+"),
    re.compile(
        r"(?i)(?:^|[^A-Za-z0-9])(?:[A-Za-z0-9]+[_-])*"
        r"(?:authorization|password|passwd|pwd|secret|token|cookie|api[_-]?key|"
        r"access[_-]?key)\s*[:=]"
    ),
    re.compile(r"(?i)\bbearer\s+\S+"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{8,}\b"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
)


def scored_case_result(
    *,
    selected_case: SelectedCase,
    output: str,
    finish_reason: str | None,
    grade: CaseGrade | Mapping[str, Any],
    metadata: Mapping[str, Any] | None = None,
    execution: CorrectiveExecution | Mapping[str, Any] | None = None,
    operations: Sequence[OperationOutput | Mapping[str, Any]] | None = None,
) -> CaseResult:
    """Construct one scored Case without exposing the wire envelope to adapters."""

    typed_grade = grade if isinstance(grade, CaseGrade) else CaseGrade.model_validate(grade)
    stop_reason, rounds_executed = _execution_fields(execution)
    return CaseResult(
        status="scored",
        case_id=selected_case.case_id,
        input=selected_case.input,
        output=output,
        finish_reason=finish_reason,
        refusal=None,
        stop_reason=stop_reason,
        rounds_executed=rounds_executed,
        grade=typed_grade,
        failures=[],
        metadata=_case_metadata(selected_case, metadata),
        operations=_operation_outputs(operations),
    )


def failed_case_result(
    *,
    selected_case: SelectedCase,
    failures: Sequence[Failure | Mapping[str, Any]],
    output: str | None = None,
    finish_reason: str | None = None,
    grade: CaseGrade | Mapping[str, Any] | None = None,
    metadata: Mapping[str, Any] | None = None,
    execution: CorrectiveExecution | Mapping[str, Any] | None = None,
    operations: Sequence[OperationOutput | Mapping[str, Any]] | None = None,
) -> CaseResult:
    """Construct one failed Case while retaining any safe partial grading evidence."""

    typed_grade = (
        grade if isinstance(grade, CaseGrade) or grade is None else CaseGrade.model_validate(grade)
    )
    typed_failures = [
        failure if isinstance(failure, Failure) else Failure.model_validate(failure)
        for failure in failures
    ]
    stop_reason, rounds_executed = _execution_fields(execution)
    return CaseResult(
        status="failed",
        case_id=selected_case.case_id,
        input=selected_case.input,
        output=output,
        finish_reason=finish_reason,
        refusal=None,
        stop_reason=stop_reason,
        rounds_executed=rounds_executed,
        grade=typed_grade,
        failures=typed_failures,
        metadata=_case_metadata(selected_case, metadata),
        operations=_operation_outputs(operations),
    )


def refused_case_result(
    *,
    selected_case: SelectedCase,
    refusal: str | None,
    grade: CaseGrade | Mapping[str, Any],
    finish_reason: str | None = None,
    failures: Sequence[Failure | Mapping[str, Any]] = (),
    metadata: Mapping[str, Any] | None = None,
    execution: CorrectiveExecution | Mapping[str, Any] | None = None,
    operations: Sequence[OperationOutput | Mapping[str, Any]] | None = None,
) -> CaseResult:
    """Construct a refused Case after normal Benchmark grading."""

    typed_grade = grade if isinstance(grade, CaseGrade) else CaseGrade.model_validate(grade)
    typed_failures = [
        failure if isinstance(failure, Failure) else Failure.model_validate(failure)
        for failure in failures
    ]
    stop_reason, rounds_executed = _execution_fields(execution)

    return CaseResult(
        status="refused",
        case_id=selected_case.case_id,
        input=selected_case.input,
        output=None,
        finish_reason=finish_reason,
        refusal=refusal,
        stop_reason=stop_reason,
        rounds_executed=rounds_executed,
        grade=typed_grade,
        failures=typed_failures,
        metadata=_case_metadata(selected_case, metadata),
        operations=_operation_outputs(operations),
    )


def grading_failure_case_result(
    *,
    selected_case: SelectedCase,
    candidate: CandidateAnswer,
    error: Mapping[str, Any],
    method: str,
    default_code: str = "grading_failed",
    default_message: str = "the Benchmark could not grade this Case",
) -> CaseResult:
    """Retain a completed Candidate outcome when subsequent grading fails."""

    diagnostic = public_error(
        error,
        default_code=default_code,
        default_message=default_message,
    )
    metadata: dict[str, Any] = {}
    if diagnostic.kind is not None:
        metadata["error_kind"] = diagnostic.kind
    failure = Failure(
        stage="grading",
        code=diagnostic.code,
        message=diagnostic.message,
        retryable=diagnostic.retryable,
        case_id=selected_case.case_id,
        metadata=metadata,
    )
    grade = CaseGrade(method=method, score=None, metrics={}, checks=[])
    if candidate.status == "refused":
        return refused_case_result(
            selected_case=selected_case,
            refusal=candidate.refusal,
            finish_reason=candidate.finish_reason,
            grade=grade,
            failures=[failure],
            execution=candidate.execution,
            operations=candidate.operations,
        )
    return failed_case_result(
        selected_case=selected_case,
        output=candidate.output,
        finish_reason=candidate.finish_reason,
        grade=grade,
        failures=[failure],
        execution=candidate.execution,
        operations=candidate.operations,
    )


def _operation_outputs(
    operations: Sequence[OperationOutput | Mapping[str, Any]] | None,
) -> list[OperationOutput] | None:
    """Normalize adapter-supplied operations; absence stays absence (OME-843)."""

    if operations is None:
        return None
    return [
        operation
        if isinstance(operation, OperationOutput)
        else OperationOutput.model_validate(operation)
        for operation in operations
    ]


def _case_metadata(
    selected_case: SelectedCase, metadata: Mapping[str, Any] | None
) -> dict[str, Any]:
    return {**selected_case.metadata, **dict(metadata or {})}


def _execution_fields(
    execution: CorrectiveExecution | Mapping[str, Any] | None,
) -> tuple[Literal["passed", "max_rounds"] | None, int | None]:
    if execution is None:
        return None, None
    typed = (
        execution
        if isinstance(execution, CorrectiveExecution)
        else CorrectiveExecution.model_validate(execution)
    )
    return typed.stop_reason, typed.rounds_executed


__all__ = [
    "CandidateScore",
    "Scorer",
    "SelectedCase",
    "failed_case_result",
    "finalize_candidate_result",
    "grading_failure_case_result",
    "public_error",
    "refused_case_result",
    "scored_case_result",
]
