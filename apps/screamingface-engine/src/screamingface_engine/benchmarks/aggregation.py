"""Cross-Benchmark Candidate finalization and score publication policy."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
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
    CorrectiveLoopOutcome,
    Failure,
    OperationOutput,
    candidate_coverage,
    is_declared_failure_code,
    validate_case_id,
)
from screamingface_engine.benchmarks.definition import FailurePolicy
from screamingface_engine.benchmarks.echoed_input import echoed_input
from screamingface_engine.benchmarks.failure_classes import (
    TIME_BASED_CODES,
    UPSTREAM_FALLBACK_CODE,
)
from screamingface_engine.benchmarks.grading_endpoints import CandidateAnswer
from screamingface_engine.capture_outcomes import record_case_results
from screamingface_engine.error_text import public_identifier, public_message
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
    # The pre-mapping upstream spelling when `code` was folded into upstream_error;
    # None whenever the upstream code was declared (or absent).
    source_code: str | None = None


@dataclass(frozen=True, slots=True)
class CandidateScore:
    """A Benchmark scorer's result over the finalizer's gradeable Case subset."""

    # HealthBench's official penalty-bearing result can be negative.
    score: float
    metrics: dict[str, Any]
    # FEATURE (OME-1268): the Named Score columns, each averaged over the same Cases as
    # `score`, headline first. Empty for every single-scorer Benchmark.
    scores: dict[str, float | None] = field(default_factory=dict)


# Scorer contract (OME-1642): under ``coverage_declare`` the scorer receives only the Cases that
# carry a numeric grade and averages over them. Under ``withhold`` it receives EVERY selected
# Case, so it must divide by ``len(cases)``, a Case with no numeric grade counting 0.
Scorer = Callable[[Sequence[CaseResult]], CandidateScore]


def gradeable_cases(cases: Sequence[CaseResult]) -> tuple[CaseResult, ...]:
    """The Cases that carry a numeric Benchmark grade."""

    return tuple(case for case in cases if case.grade is not None and case.grade.score is not None)


def policy_cases(
    cases: Sequence[CaseResult], failure_policy: FailurePolicy
) -> Sequence[CaseResult] | None:
    """The Cases a scorer receives under ``failure_policy``; None when no Case is graded.

    WHY one helper (OME-1642): the final result and the live progress projection must pick
    the same Cases, or a withhold Benchmark's in-run score would differ from its final one.
    """

    gradeable = gradeable_cases(cases)
    if not gradeable:
        return None
    return tuple(cases) if failure_policy == "withhold" else gradeable


def finalize_candidate_result(
    *,
    benchmark_id: str,
    benchmark_revision: str,
    selected_cases: Sequence[SelectedCase | Mapping[str, Any]],
    cases: Sequence[CaseResult | Mapping[str, Any]],
    scorer: Scorer,
    failure_policy: FailurePolicy,
    failures: Sequence[Failure | Mapping[str, Any]] = (),
    inverted_grade: bool = False,
) -> CandidateResult:
    """Preserve Cases and score them under the Benchmark's declared failure policy.

    FEATURE (OME-1642): ``failure_policy`` decides which Cases the scorer is given.
    ``coverage_declare`` hands it exactly the subset carrying numeric Benchmark grades (the
    failed Cases leave the score; coverage shows them). ``withhold`` hands it EVERY selected
    Case, failed ones included, so the scorer counts each one as 0 in the denominator. Under
    both, a Candidate with no numeric Case grade publishes ``score=None`` and the scorer never
    runs (R4), and coverage stays graded / selected.

    ``inverted_grade`` marks a Benchmark whose Case scores are already 1 − the eval's grade
    (OME-1400); it rides the result so a replayed report can show it.
    """

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
    # FEATURE: OME-1775 — R1 needs each Case's final result; every final Case result passes here,
    # once per Candidate. A Case that failed on time (in any Attempt) is noted as one a replay
    # may score.
    record_case_results(
        (case.case_id, case.status == "scored" or _failed_on_time(case)) for case in typed_cases
    )

    scoring_cases = policy_cases(typed_cases, failure_policy)
    scored = scorer(scoring_cases) if scoring_cases is not None else None
    # FEATURE (OME-1271): this is where a Candidate result leaves the engine, so here each
    # Case's echoed input loses its pictures' base64 to their placeholders.
    # INVARIANT: after the scorer, so grading and scoring saw the real Case; a text Case's
    # input is the same string, so its result is byte-identical.
    typed_cases = [
        case.model_copy(update={"input": echoed_input(case.input)}) for case in typed_cases
    ]
    result = CandidateResult(
        benchmark_id=benchmark_id,
        benchmark_revision=benchmark_revision,
        case_count=len(typed_cases),
        score=scored.score if scored is not None else None,
        coverage=candidate_coverage(typed_cases, len(typed_cases)),
        metrics=scored.metrics if scored is not None else {},
        cases=typed_cases,
        failures=typed_failures,
        inverted_grade=inverted_grade,
        scores=scored.scores if scored is not None else {},
    )
    reconcile_candidate_grading_accounting(result)
    return result


def _failed_on_time(case: CaseResult) -> bool:
    """True when wall time caused a failure of the Case or of one of its Attempts (OME-1775 R1).

    WHY each Attempt: when no Attempt scored, the Attempt fold keeps only Attempt 1's failures on
    the Case, so a later Attempt's timeout is only in ``case.attempts``.
    """
    attempt_failures = [failure for attempt in case.attempts or () for failure in attempt.failures]
    return any(_time_based(failure) for failure in [*case.failures, *attempt_failures])


def _time_based(failure: Failure) -> bool:
    """True when the failure's code, or an upstream code it carries, is in TIME_BASED_CODES.

    WHY the nested shape: the shared marking room keeps the upstream error under
    ``metadata["source_error"]`` (its ``code``, and ``source_code`` for a folded url4 code); only
    the grading stage writes ``source_code`` at the top level of the metadata.
    """
    source_error = failure.metadata.get("source_error")
    nested: Mapping[str, Any] = source_error if isinstance(source_error, Mapping) else {}
    codes = (
        failure.code,
        failure.metadata.get("source_code"),
        nested.get("code"),
        nested.get("source_code"),
    )
    return any(isinstance(code, str) and code in TIME_BASED_CODES for code in codes)


def public_error(
    error: Mapping[str, Any],
    *,
    default_code: str,
    default_message: str,
) -> PublicError:
    """Retain useful error fields without publishing runner internals or credentials."""

    kind = public_identifier(error.get("kind"))
    code = public_identifier(error.get("code")) or default_code
    message = public_message(error.get("message"), default=default_message)
    retryable = error.get("retryable")
    if not isinstance(retryable, bool):
        permanent = error.get("permanent")
        retryable = not permanent if isinstance(permanent, bool) else None
    # WHY the mapping (OME-1234, owner decision): upstream produces an open set of
    # codes the engine does not control, but Failure.code refuses anything undeclared.
    # Folding unknowns into upstream_error here — spelling preserved in source_code —
    # keeps the axis closed without letting routine gateway churn crash a paid run.
    source_code: str | None = None
    if not is_declared_failure_code(code):
        source_code = code
        code = UPSTREAM_FALLBACK_CODE
    return PublicError(
        kind=kind, code=code, message=message, retryable=retryable, source_code=source_code
    )


def scored_case_result(
    *,
    selected_case: SelectedCase,
    # str | None matches CaseResult.output: a completed row without usable answer
    # text still scores (the rubric judges the row's evidence, not this field).
    output: str | None,
    finish_reason: str | None,
    grade: CaseGrade | Mapping[str, Any],
    metadata: Mapping[str, Any] | None = None,
    execution: CorrectiveLoopOutcome | Mapping[str, Any] | None = None,
    operations: Sequence[OperationOutput | Mapping[str, Any]] | None = None,
    abstained: bool = False,
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
        abstained=abstained,
    )


def failed_case_result(
    *,
    selected_case: SelectedCase,
    failures: Sequence[Failure | Mapping[str, Any]],
    output: str | None = None,
    finish_reason: str | None = None,
    grade: CaseGrade | Mapping[str, Any] | None = None,
    metadata: Mapping[str, Any] | None = None,
    execution: CorrectiveLoopOutcome | Mapping[str, Any] | None = None,
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


def refusal_case_result(
    *,
    selected_case: SelectedCase,
    refusal: str | None,
    grade: CaseGrade | Mapping[str, Any],
    finish_reason: str | None = None,
    failures: Sequence[Failure | Mapping[str, Any]] = (),
    metadata: Mapping[str, Any] | None = None,
    execution: CorrectiveLoopOutcome | Mapping[str, Any] | None = None,
    operations: Sequence[OperationOutput | Mapping[str, Any]] | None = None,
) -> CaseResult:
    """Classify one refused Candidate Invocation into its case-level outcome.

    Mental model (OME-1037): the invocation layer says only "the Candidate did not
    answer"; THIS is the one place that decides what that means for the Case. A
    refusal the Benchmark graded (DRACO scoring a decline 1.0, another benchmark
    0.0) is an ordinary scored Case carrying the `refusal` text; a refusal the
    Benchmark could not grade is a failed Case led by a `provider_refusal` failure,
    followed by the grading failures, with the refusal text kept as evidence.

    Worked example: refusal="I won't help", grade.score=0.8, no failures → scored,
    refusal carried. refusal="I won't help", grade.score=None, one
    incomplete_verdicts failure → failed, failures=[provider_refusal,
    incomplete_verdicts]. refusal=None, grade.score=0.0 → failed with the score
    DROPPED: a textless refusal is exactly a content_filter provider decline
    (`runner/model_response.py` fires on content_filter OR non-null refusal, and
    content_filter turns normally carry null text), so the model never answered and
    a judge score over the empty answer would publish an infrastructure failure as
    a plausible grade. The grade's checks/metrics stay as audit evidence.
    """

    typed_grade = grade if isinstance(grade, CaseGrade) else CaseGrade.model_validate(grade)
    typed_failures = [
        failure if isinstance(failure, Failure) else Failure.model_validate(failure)
        for failure in failures
    ]
    stop_reason, rounds_executed = _execution_fields(execution)
    if typed_grade.score is not None and refusal is not None and not typed_failures:
        return CaseResult(
            status="scored",
            case_id=selected_case.case_id,
            input=selected_case.input,
            output=None,
            finish_reason=finish_reason,
            refusal=refusal,
            stop_reason=stop_reason,
            rounds_executed=rounds_executed,
            grade=typed_grade,
            failures=[],
            metadata=_case_metadata(selected_case, metadata),
            operations=_operation_outputs(operations),
        )
    if typed_grade.score is not None:
        # WHY: a failed Case cannot publish a numeric grade — the score over an
        # answer that never existed is dropped, the audit material retained.
        typed_grade = CaseGrade(
            method=typed_grade.method,
            score=None,
            metrics=typed_grade.metrics,
            checks=typed_grade.checks,
        )
    provider_refusal = Failure(
        stage="candidate",
        code="provider_refusal",
        # The runner's own classification message (`runner/model_response.py`).
        message="provider refused the request",
        retryable=False,
        case_id=selected_case.case_id,
        metadata={},
    )
    return CaseResult(
        status="failed",
        case_id=selected_case.case_id,
        input=selected_case.input,
        output=None,
        finish_reason=finish_reason,
        refusal=refusal,
        stop_reason=stop_reason,
        rounds_executed=rounds_executed,
        grade=typed_grade,
        failures=[provider_refusal, *typed_failures],
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
    if diagnostic.source_code is not None:
        # The upstream spelling that was folded into upstream_error — kept so on-call
        # can still see exactly what the gateway said.
        metadata["source_code"] = diagnostic.source_code
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
        return refusal_case_result(
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
    execution: CorrectiveLoopOutcome | Mapping[str, Any] | None,
) -> tuple[Literal["passed", "max_rounds"] | None, int | None]:
    if execution is None:
        return None, None
    typed = (
        execution
        if isinstance(execution, CorrectiveLoopOutcome)
        else CorrectiveLoopOutcome.model_validate(execution)
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
    "refusal_case_result",
    "scored_case_result",
]
