"""Decode Engine Candidate outcomes into the stable public Report."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import Literal, cast

from screamingface._core.ports import _RunOutcome
from screamingface._evaluation.model import Candidate, _compiled_evaluation, _Evaluation
from screamingface._evaluation.operation_accounting import decode_operation_accounting
from screamingface._report_primitives import CaseId
from screamingface._report_primitives import _case_id as _validate_case_id
from screamingface.case_result import (
    CaseOperation,
    CaseStatus,
    StopReason,
)
from screamingface.discovery import BenchmarkInfo
from screamingface.errors import ExecutionError
from screamingface.report import (
    CandidateResult,
    CaseGrade,
    CaseResult,
    Check,
    Evidence,
    EvidenceProducer,
    Failure,
    MemberResult,
    Report,
    Usage,
)

# The marker pre-OME-892 Engines glued onto a cut result body. Recognized here so a run
# against an OLD Engine fails with the real cause instead of the generic "must be JSON".
_LEGACY_TRUNCATION_MARKER = "…[truncated]"


def _decoded_result_body(outcome: _RunOutcome) -> object:
    """Decode the root result body, naming truncation and unredeemed tickets precisely.

    FEATURE: deliver large results in full (OME-892). Order of the checks: (1) a None
    body means the transport failed to materialize an artifact outcome — a bug to name,
    not a TypeError to leak; (2) JSON that parses is returned; (3) unparseable JSON
    ending in the legacy marker is an OLD Engine's truncation — report the received byte
    count so the researcher learns what happened from the error alone; (4) anything else
    keeps the generic message.
    """
    body = outcome.result_body
    if body is None:
        raise ExecutionError(
            "SF Engine Candidate result artifact was not materialized by the transport"
        )
    try:
        return json.loads(body)
    except json.JSONDecodeError as exc:
        if body.endswith(_LEGACY_TRUNCATION_MARKER):
            # WHY "ends with the marker" phrasing: a body could conceivably end with
            # this literal for another reason — the error states the evidence (marker +
            # byte count) rather than asserting certainty about the cause.
            raise ExecutionError(
                "SF Engine candidate result is invalid JSON and ends with the Engine's "
                f"truncation marker at {len(body.encode('utf-8'))} bytes — most likely "
                "truncated by a pre-OME-892 Engine; upgrade the Engine to deliver large "
                "results whole, or run with a smaller limit",
                code="result_truncated",
                permanent=True,
            ) from exc
        raise ExecutionError("SF Engine Candidate result must be JSON") from exc


def report_from_outcomes(
    evaluation: _Evaluation,
    outcomes: tuple[tuple[Candidate, _RunOutcome], ...],
) -> Report:
    """Build one stable Report from independently executed Candidate roots."""

    candidates = tuple(
        _candidate_result(evaluation, candidate, outcome) for candidate, outcome in outcomes
    )
    return Report(
        benchmark=evaluation.benchmark,
        case_count=evaluation.case_count,
        candidates=candidates,
    )


def report_from_url4_outcome(candidate: Candidate, outcome: _RunOutcome) -> Report:
    """Decode an opaque replay after its result identifies the pinned Benchmark."""

    payload = _decoded_result_body(outcome)
    value = _mapping(payload, "Candidate result")
    if value.get("schema") != "screamingface.candidate-result.v1":
        raise ExecutionError("SF Engine Candidate result schema is unsupported")
    benchmark_id = _text(value.get("benchmark_id"), "Candidate benchmark_id")
    benchmark_revision = _text(
        value.get("benchmark_revision"),
        "Candidate benchmark_revision",
    )
    case_count = _positive_integer(value.get("case_count"), "Candidate case_count")
    benchmark = BenchmarkInfo(
        id=benchmark_id,
        revision=benchmark_revision,
        case_count=case_count,
    )
    evaluation = _compiled_evaluation(
        benchmark=benchmark,
        limit=None,
        case_count=case_count,
        candidates=(candidate,),
        required_models=candidate.models,
    )
    return report_from_outcomes(evaluation, ((candidate, outcome),))


def _candidate_result(
    evaluation: _Evaluation,
    candidate: Candidate,
    outcome: _RunOutcome,
) -> CandidateResult:
    value = _candidate_payload(evaluation, outcome)
    try:
        score, coverage, metrics, cases, failures = _candidate_components(
            value,
            evaluation,
            candidate,
        )
        return CandidateResult(
            benchmark=evaluation.benchmark,
            run_id=outcome.run_id,
            started_at=outcome.started_at,
            completed_at=outcome.completed_at,
            name=candidate.name,
            kind=candidate.kind,
            url4=candidate.url4,
            models=candidate.models,
            operations=candidate.operations,
            score=score,
            coverage=coverage,
            metrics=metrics,
            cases=cases,
            members=tuple(
                MemberResult(
                    operation_id=member.operation_id,
                    name=member.name,
                    kind=member.kind,
                    models=member.models,
                    failures=None,
                    duration_ms=None,
                    usage=None,
                )
                for member in candidate.members
            ),
            failures=failures,
            usage=outcome.root_usage or Usage(),
        )
    except (TypeError, ValueError) as exc:
        raise ExecutionError(f"SF Engine Candidate result is invalid: {exc}") from exc


def _candidate_payload(
    evaluation: _Evaluation,
    outcome: _RunOutcome,
) -> Mapping[str, object]:
    payload = _decoded_result_body(outcome)
    value = _mapping(payload, "Candidate result")
    _keys(
        value,
        required={
            "schema",
            "benchmark_id",
            "benchmark_revision",
            "case_count",
            "score",
            "coverage",
            "metrics",
            "cases",
            "failures",
        },
        label="Candidate result",
    )
    if value.get("schema") != "screamingface.candidate-result.v1":
        raise ExecutionError("SF Engine Candidate result schema is unsupported")
    if value.get("benchmark_id") != evaluation.benchmark.id:
        raise ExecutionError("SF Engine Candidate result has the wrong Benchmark id")
    if value.get("benchmark_revision") != evaluation.benchmark.revision:
        raise ExecutionError("SF Engine Candidate result has the wrong Benchmark revision")
    if _positive_integer(value.get("case_count"), "Candidate case_count") != evaluation.case_count:
        raise ExecutionError("SF Engine Candidate result has the wrong case count")
    return value


def _candidate_components(
    value: Mapping[str, object],
    evaluation: _Evaluation,
    candidate: Candidate,
) -> tuple[
    float | None,
    float,
    dict[str, object],
    tuple[CaseResult, ...],
    tuple[Failure, ...],
]:
    score_value = value.get("score")
    score = None if score_value is None else _number(score_value, "Candidate score")
    coverage = _coverage(value.get("coverage"))
    metrics = _metrics(value.get("metrics"))
    cases = _cases(_required(value, "cases", "Candidate result"))
    if len(cases) != evaluation.case_count:
        raise ExecutionError("SF Engine Candidate result has the wrong number of Cases")
    failures = _failures(_required(value, "failures", "Candidate result"), "Candidate failures")
    return score, coverage, metrics, cases, failures


def _mapping(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ExecutionError(f"{label} must be an object")
    return value


def _metrics(value: object) -> dict[str, object]:
    raw = _mapping(value, "Candidate metrics")
    if any(not isinstance(name, str) for name in raw):
        raise ExecutionError("Candidate metric names must be strings")
    return dict(raw)


def _cases(value: object) -> tuple[CaseResult, ...]:
    return tuple(_case_result(item) for item in _sequence(value, "Candidate cases"))


def _case_result(value: object) -> CaseResult:
    raw = _mapping(value, "Case Result")
    _keys(
        raw,
        required={
            "status",
            "case_id",
            "input",
            "output",
            "finish_reason",
            "refusal",
            "stop_reason",
            "rounds_executed",
            "grade",
            "failures",
            "metadata",
        },
        # WHY: `operations` (OME-843 member-output capture) is optional so pre-capture
        # Engines keep decoding; tolerance is for the key's absence only — present
        # content still decodes strictly below.
        optional={"operations"},
        label="Case Result",
    )
    case_id = _case_id(raw.get("case_id"), "Case Result case_id")
    operations_value = raw.get("operations")
    operations = None if operations_value is None else _case_operations(operations_value)
    grade_value = _required(raw, "grade", "Case Result")
    grade = None if grade_value is None else _case_grade(grade_value)
    failures = _failures(_required(raw, "failures", "Case Result"), "Case Result failures")
    finish_reason_value = _required(raw, "finish_reason", "Case Result")
    try:
        return CaseResult(
            status=_case_status(raw.get("status")),
            case_id=case_id,
            input=_nonempty_text(_required(raw, "input", "Case Result"), "Case Result input"),
            output=_optional_string(_required(raw, "output", "Case Result"), "Case Result output"),
            finish_reason=(
                None
                if finish_reason_value is None
                else _text(finish_reason_value, "Case Result finish_reason")
            ),
            refusal=_optional_text(raw.get("refusal"), "Case Result refusal"),
            stop_reason=_stop_reason(raw.get("stop_reason")),
            rounds_executed=_optional_positive_integer(
                raw.get("rounds_executed"), "Case Result rounds_executed"
            ),
            grade=grade,
            failures=failures,
            metadata=_mapping(_required(raw, "metadata", "Case Result"), "Case Result metadata"),
            operations=operations,
        )
    except (TypeError, ValueError) as exc:
        raise ExecutionError(f"Case Result is invalid: {exc}") from exc


def _case_operations(value: object) -> tuple[CaseOperation, ...]:
    return tuple(_case_operation(item) for item in _sequence(value, "Case Result operations"))


def _case_operation(value: object) -> CaseOperation:
    raw = _mapping(value, "Case Operation")
    _keys(
        raw,
        required={"operation_id", "output", "finish_reason", "accounting"},
        label="Case Operation",
    )
    finish_reason_value = raw.get("finish_reason")
    try:
        return CaseOperation(
            operation_id=_nonempty_text(raw.get("operation_id"), "Case Operation operation_id"),
            output=_optional_string(raw.get("output"), "Case Operation output"),
            finish_reason=(
                None
                if finish_reason_value is None
                else _text(finish_reason_value, "Case Operation finish_reason")
            ),
            accounting=decode_operation_accounting(
                raw.get("accounting"), "Case Operation accounting"
            ),
        )
    except (TypeError, ValueError) as exc:
        raise ExecutionError(f"Case Operation is invalid: {exc}") from exc


def _case_grade(value: object) -> CaseGrade:
    raw = _mapping(value, "Case Grade")
    _keys(raw, required={"method", "score", "metrics", "checks"}, label="Case Grade")
    score_value = raw.get("score")
    try:
        return CaseGrade(
            method=_nonempty_text(raw.get("method"), "Case Grade method"),
            score=None if score_value is None else _number(score_value, "Case Grade score"),
            metrics=_mapping(raw.get("metrics"), "Case Grade metrics"),
            checks=tuple(
                _check(item) for item in _sequence(raw.get("checks"), "Case Grade checks")
            ),
        )
    except (TypeError, ValueError) as exc:
        raise ExecutionError(f"Case Grade is invalid: {exc}") from exc


def _check(value: object) -> Check:
    raw = _mapping(value, "Check")
    _keys(
        raw,
        required={"type", "id", "label", "evidence", "metadata"},
        optional={"outcome", "score"},
        label="Check",
    )
    score_value = raw.get("score")
    try:
        return Check(
            type=_nonempty_text(raw.get("type"), "Check type"),
            id=_nonempty_text(raw.get("id"), "Check id"),
            label=_string(raw.get("label"), "Check label"),
            evidence=tuple(
                _evidence(item) for item in _sequence(raw.get("evidence"), "Check evidence")
            ),
            outcome=_check_outcome(raw.get("outcome")),
            score=None if score_value is None else _number(score_value, "Check score"),
            metadata=_mapping(raw.get("metadata"), "Check metadata"),
        )
    except (TypeError, ValueError) as exc:
        raise ExecutionError(f"Check is invalid: {exc}") from exc


def _evidence(value: object) -> Evidence:
    raw = _mapping(value, "Evidence")
    _keys(
        raw,
        required={"sequence", "producer", "valid", "raw_output", "metadata", "accounting"},
        optional={"outcome", "explanation"},
        label="Evidence",
    )
    producer = _mapping(raw.get("producer"), "Evidence producer")
    _keys(producer, required={"type", "id"}, label="Evidence producer")
    valid = raw.get("valid")
    if not isinstance(valid, bool):
        raise ExecutionError("Evidence valid must be boolean")
    try:
        return Evidence(
            sequence=_positive_integer(raw.get("sequence"), "Evidence sequence"),
            producer=EvidenceProducer(
                type=_producer_type(producer.get("type")),
                id=_nonempty_text(producer.get("id"), "Evidence producer id"),
            ),
            valid=valid,
            outcome=_evidence_outcome(raw.get("outcome")),
            explanation=_optional_string(raw.get("explanation"), "Evidence explanation"),
            raw_output=_required(raw, "raw_output", "Evidence"),
            metadata=_mapping(raw.get("metadata"), "Evidence metadata"),
            accounting=decode_operation_accounting(raw.get("accounting"), "Evidence accounting"),
        )
    except (TypeError, ValueError) as exc:
        raise ExecutionError(f"Evidence is invalid: {exc}") from exc


def _failures(value: object, label: str) -> tuple[Failure, ...]:
    return tuple(_failure(item) for item in _sequence(value, label))


def _failure(value: object) -> Failure:
    raw = _mapping(value, "Failure")
    _keys(
        raw,
        required={"stage", "code", "message", "retryable", "case_id", "metadata"},
        label="Failure",
    )
    retryable = _required(raw, "retryable", "Failure")
    if retryable is not None and not isinstance(retryable, bool):
        raise ExecutionError("Failure retryable must be boolean or null")
    try:
        return Failure(
            stage=_failure_stage(raw.get("stage")),
            code=_nonempty_text(raw.get("code"), "Failure code"),
            message=_nonempty_text(raw.get("message"), "Failure message"),
            retryable=retryable,
            case_id=_failure_case_id(_required(raw, "case_id", "Failure")),
            metadata=_mapping(_required(raw, "metadata", "Failure"), "Failure metadata"),
        )
    except (TypeError, ValueError) as exc:
        raise ExecutionError(f"Failure is invalid: {exc}") from exc


def _sequence(value: object, label: str) -> Sequence[object]:
    if isinstance(value, str | bytes) or not isinstance(value, Sequence):
        raise ExecutionError(f"{label} must be an array")
    return value


def _required(value: Mapping[str, object], key: str, label: str) -> object:
    if key not in value:
        raise ExecutionError(f"{label} is missing {key!r}")
    return value[key]


def _keys(
    value: Mapping[str, object],
    *,
    required: set[str],
    label: str,
    optional: set[str] | None = None,
) -> None:
    present = set(value)
    if missing := sorted(required - present):
        raise ExecutionError(f"{label} is missing {missing[0]!r}")
    if unknown := sorted(present - required - (optional or set())):
        raise ExecutionError(f"{label} contains unsupported field {unknown[0]!r}")


def _positive_integer(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ExecutionError(f"{label} must be a positive integer")
    return value


def _optional_positive_integer(value: object, label: str) -> int | None:
    return None if value is None else _positive_integer(value, label)


def _text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ExecutionError(f"{label} must be non-empty text")
    return value


def _optional_text(value: object, label: str) -> str | None:
    return None if value is None else _text(value, label)


def _optional_string(value: object, label: str) -> str | None:
    if value is None or isinstance(value, str):
        return value
    raise ExecutionError(f"{label} must be text or null")


def _nonempty_text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise ExecutionError(f"{label} must be non-empty text")
    return value


def _string(value: object, label: str) -> str:
    if not isinstance(value, str):
        raise ExecutionError(f"{label} must be text")
    return value


def _producer_type(value: object) -> str:
    return _nonempty_text(value, "Evidence producer type")


def _check_outcome(value: object) -> Literal["MET", "UNMET"] | None:
    if value is None:
        return None
    if value == "MET":
        return "MET"
    if value == "UNMET":
        return "UNMET"
    raise ExecutionError("Check outcome must be MET, UNMET, or null")


def _evidence_outcome(
    value: object,
) -> Literal["MET", "UNMET", "PASS", "FAIL"] | None:
    if value is None:
        return None
    if not isinstance(value, str) or value not in {"MET", "UNMET", "PASS", "FAIL"}:
        raise ExecutionError("Evidence outcome must be MET, UNMET, PASS, FAIL, or null")
    return cast(Literal["MET", "UNMET", "PASS", "FAIL"], value)


def _case_status(value: object) -> CaseStatus:
    if value == "scored":
        return "scored"
    if value == "refused":
        return "refused"
    if value == "failed":
        return "failed"
    raise ExecutionError("Case Result status is unsupported")


def _stop_reason(value: object) -> StopReason | None:
    if value is None:
        return None
    if value in {"passed", "max_rounds"}:
        return cast(StopReason, value)
    raise ExecutionError("Case Result stop_reason must be passed, max_rounds, or null")


def _failure_stage(value: object) -> Literal["candidate", "grading", "aggregation"]:
    if value == "candidate":
        return "candidate"
    if value == "grading":
        return "grading"
    if value == "aggregation":
        return "aggregation"
    raise ExecutionError("Failure stage is unsupported")


def _failure_case_id(value: object) -> int | str | None:
    if value is None:
        return None
    return _case_id(value, "Failure case_id")


def _case_id(value: object, label: str) -> CaseId:
    try:
        return _validate_case_id(value, label)
    except (TypeError, ValueError) as exc:
        raise ExecutionError(str(exc)) from exc


def _number(value: object, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ExecutionError(f"{label} must be numeric")
    return float(value)


def _coverage(value: object) -> float:
    selected = _number(value, "Candidate coverage")
    if selected != selected or selected in {float("inf"), float("-inf")}:
        raise ExecutionError("Candidate coverage must be a finite number")
    if not 0.0 <= selected <= 1.0:
        raise ExecutionError("Candidate coverage must be between 0 and 1")
    return selected


__all__: list[str] = []
