"""Wire names shared by Engine-owned Benchmarks and Candidate Invocation."""

from __future__ import annotations

import json
import math
from collections.abc import Mapping, Sequence
from typing import Any, Literal, cast

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictInt,
    StrictStr,
    field_validator,
    model_validator,
)

from screamingface_engine.operation_accounting import (
    OperationAccounting,
    OperationCache,
    OperationUsage,
)

CANDIDATE_ROUTE = "/benchmarks/candidate"
# The source name a client binds its Candidate expression under, so the protocol's `$candidate`
# resolves. Published in every Benchmark resource: a client cannot be expected to infer it.
CANDIDATE_BINDING = "candidate"
CANDIDATE_INPUT_SCHEMA = "screamingface.candidate-input.v1"
CANDIDATE_INVOCATION_SCHEMA = "screamingface.candidate-invocation.v1"
CANDIDATE_RESULT_SCHEMA = "screamingface.candidate-result.v1"
CANDIDATE_MESSAGE_ROLES = frozenset({"system", "developer", "user", "assistant"})
CaseId = StrictInt | StrictStr
Outcome = Literal["MET", "UNMET", "PASS", "FAIL"]
FailureStage = Literal["candidate", "grading", "aggregation"]
CaseStatus = Literal["scored", "refused", "failed"]
CandidateInvocationStatus = Literal["completed", "refused"]


class _StrictWireModel(BaseModel):
    """Closed producer value: every structural wire key is intentional."""

    model_config = ConfigDict(extra="forbid", strict=True)

    @field_validator("metadata", "metrics", check_fields=False)
    @classmethod
    def _validate_open_json_mapping(cls, value: object) -> object:
        return _json_value(value)


class EvidenceProducer(_StrictWireModel):
    """The deterministic or model-backed producer of one Evidence item."""

    type: str = Field(min_length=1)
    id: str = Field(min_length=1)


class Evidence(_StrictWireModel):
    """One auditable observation supporting a Check."""

    sequence: int = Field(ge=1)
    producer: EvidenceProducer
    valid: bool
    outcome: Outcome | None = Field(default=None, exclude_if=lambda value: value is None)
    explanation: str | None = Field(default=None, exclude_if=lambda value: value is None)
    raw_output: Any
    metadata: dict[str, Any]
    accounting: OperationAccounting | None

    @field_validator("raw_output")
    @classmethod
    def _validate_raw_output(cls, value: object) -> object:
        return _json_value(value)

    @model_validator(mode="after")
    def _enforce_validity(self) -> Evidence:
        if not self.valid and (self.outcome is not None or self.explanation is not None):
            raise ValueError("invalid Evidence cannot claim an outcome or explanation")
        return self


class Check(_StrictWireModel):
    """One named deterministic or rubric requirement."""

    type: str = Field(min_length=1)
    id: str = Field(min_length=1)
    label: str
    outcome: Literal["MET", "UNMET"] | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    score: float | None = Field(
        default=None, ge=0.0, le=1.0, exclude_if=lambda value: value is None
    )
    evidence: list[Evidence]
    metadata: dict[str, Any]

    @field_validator("score", mode="before")
    @classmethod
    def _validate_score(cls, value: object) -> object:
        return _finite_score(value)


class CaseGrade(_StrictWireModel):
    """Benchmark-specific grading projected into the shared Case envelope."""

    method: str = Field(min_length=1)
    # HealthBench deliberately permits negative penalty-bearing Case scores.
    score: float | None = Field(le=1.0)
    metrics: dict[str, Any]
    checks: list[Check]

    @field_validator("score", mode="before")
    @classmethod
    def _validate_score(cls, value: object) -> object:
        return _finite_score(value)


class Failure(_StrictWireModel):
    """A bounded public failure attributable to a Case or Candidate."""

    stage: FailureStage
    code: str = Field(min_length=1)
    message: str = Field(min_length=1)
    retryable: bool | None
    case_id: CaseId | None
    metadata: dict[str, Any]

    @field_validator("case_id")
    @classmethod
    def _validate_case_id(cls, value: CaseId | None) -> CaseId | None:
        return validate_case_id(value, optional=True)


class CaseResult(_StrictWireModel):
    """One selected Case with an explicit scored, refused, or failed outcome."""

    status: CaseStatus
    case_id: CaseId
    input: str = Field(min_length=1)
    output: str | None
    finish_reason: str | None
    refusal: str | None
    stop_reason: Literal["passed", "max_rounds"] | None = None
    rounds_executed: int | None = Field(default=None, ge=1)
    grade: CaseGrade | None
    failures: list[Failure]
    metadata: dict[str, Any]
    # WHY: excluded when None so unattributed and pre-OME-843 artifacts stay byte-identical;
    # consumers see the key only when named model operations were attributed.
    operations: list[OperationOutput] | None = Field(
        default=None, exclude_if=lambda value: value is None
    )

    @field_validator("case_id")
    @classmethod
    def _validate_case_id(cls, value: CaseId) -> CaseId:
        validated = validate_case_id(value)
        assert validated is not None
        return validated

    @field_validator("refusal")
    @classmethod
    def _validate_refusal(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("refusal must be non-empty text or null")
        return value

    @field_validator("finish_reason")
    @classmethod
    def _validate_finish_reason(cls, value: str | None) -> str | None:
        return validate_finish_reason(value)

    @model_validator(mode="after")
    def _enforce_status(self) -> CaseResult:
        if (self.stop_reason is None) != (self.rounds_executed is None):
            raise ValueError("stop_reason and rounds_executed must be present together")
        if any(failure.case_id != self.case_id for failure in self.failures):
            raise ValueError("every Case Failure must reference its own case_id")
        if self.status == "scored":
            _require_scored_case(self)
        elif self.status == "refused":
            _require_refused_case(self)
        else:
            _require_failed_case(self)
        return self


class OperationOutput(_StrictWireModel):
    """One Candidate operation's terminal output, keyed by its stable operation id.

    FEATURE: OME-843 member-output capture. ``output``/``finish_reason`` are null
    when the Engine could not attribute the call unambiguously — absence of
    evidence, never a positional guess.
    """

    operation_id: str = Field(min_length=1)
    output: str | None
    finish_reason: str | None
    accounting: OperationAccounting | None

    @field_validator("finish_reason")
    @classmethod
    def _validate_finish_reason(cls, value: str | None) -> str | None:
        return validate_finish_reason(value)


class CorrectiveExecution(_StrictWireModel):
    """The final, benchmark-neutral execution outcome of one corrective Recipe."""

    schema_version: Literal["screamingface.corrective-execution.v1"] = Field(
        default="screamingface.corrective-execution.v1", alias="schema"
    )
    stop_reason: Literal["passed", "max_rounds"]
    rounds_executed: int = Field(ge=1)


class CandidateInvocation(_StrictWireModel):
    """One exact terminal Candidate outcome used inside Benchmark execution."""

    schema_version: Literal["screamingface.candidate-invocation.v1"] = Field(
        default="screamingface.candidate-invocation.v1", alias="schema"
    )
    status: CandidateInvocationStatus
    output: str
    finish_reason: str | None
    refusal: str | None
    execution: CorrectiveExecution | None
    # WHY: excluded when None so an unattributed Candidate envelope stays byte-identical to
    # the pre-OME-843 contract — the key exists only when the Engine attributed named operations.
    operations: list[OperationOutput] | None = Field(
        default=None, exclude_if=lambda value: value is None
    )

    @field_validator("finish_reason")
    @classmethod
    def _validate_finish_reason(cls, value: str | None) -> str | None:
        return validate_finish_reason(value)

    @field_validator("refusal")
    @classmethod
    def _validate_refusal(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("Candidate Invocation refusal must be non-empty text or null")
        return value

    @model_validator(mode="after")
    def _enforce_status(self) -> CandidateInvocation:
        if self.status == "completed" and self.refusal is not None:
            raise ValueError("a completed Candidate Invocation cannot carry refusal text")
        if self.status == "refused" and self.output:
            raise ValueError("a refused Candidate Invocation must carry an empty output")
        return self


def is_valid_corrective_execution(value: object) -> bool:
    """Whether a nullable value is one complete corrective execution envelope."""

    if value is None:
        return True
    try:
        validate_corrective_execution(value)
    except ValueError:
        return False
    return True


def validate_corrective_execution(value: object) -> CorrectiveExecution:
    """Decode the exact versioned envelope accepted at Engine wire boundaries."""

    if (
        not isinstance(value, Mapping)
        or set(value) != {"schema", "stop_reason", "rounds_executed"}
        or value.get("schema") != "screamingface.corrective-execution.v1"
    ):
        raise ValueError("corrective execution has an invalid shape or schema")
    return CorrectiveExecution.model_validate(value)


def _require_scored_case(case: CaseResult) -> None:
    if (
        case.grade is None
        or case.grade.score is None
        or case.output is None
        or case.refusal is not None
        or case.failures
    ):
        raise ValueError(
            "a scored Case requires output and a numeric grade and cannot carry refusal or failures"
        )


def _require_refused_case(case: CaseResult) -> None:
    if case.output is not None or case.grade is None:
        raise ValueError("a refused Case requires no output and a Benchmark grade")
    if case.grade.score is not None and case.failures:
        raise ValueError("a graded refused Case cannot carry failures")
    if case.grade.score is None and (
        not case.failures or any(failure.stage != "grading" for failure in case.failures)
    ):
        raise ValueError("an ungraded refused Case requires one or more grading failures")


def _require_failed_case(case: CaseResult) -> None:
    # WHY no provider_refusal Failure-code check: no producer can emit one. The Candidate
    # adapter converts the runner's provider_refusal error into an ordinary refused
    # invocation before it can become a Failure, and url4's on_error=collect envelope
    # carries only kind+message — collected error codes always fall back to the
    # aggregate defaults. Refusals reach this contract only through `case.refusal`.
    if (
        not case.failures
        or case.refusal is not None
        or case.grade is not None
        and case.grade.score is not None
    ):
        raise ValueError("a failed Case requires failures, no refusal, and no numeric grade")


class CandidateResult(_StrictWireModel):
    """The `screamingface.candidate-result.v1` payload every Benchmark aggregate returns.

    Mental model: this class IS the producer side of the wire contract. An aggregate
    that hand-builds the dict can silently drop a field the SDK renders from (that is
    how an all-pass run once displayed every case as INCORRECT); an aggregate that
    constructs this model cannot — a wrong shape fails in its own unit tests with a
    named validator error. Invariants enforced here, once, instead of as prose in
    three benchmarks:

    - top-level `coverage` is the exact fraction of selected Cases carrying a
      numeric Benchmark grade. Generic `metrics.coverage` is forbidden because
      Benchmarks had used it for incompatible meanings.
    - with any numeric Case grade, the Candidate publishes the Benchmark score
      over exactly those Cases and may retain ungradeable failed Cases alongside it.
      Benchmark-specific metrics remain deliberately open.
    - with no numeric Case grade, `score is None`, `coverage == 0`, and
      `metrics == {}` — infrastructure failure never becomes a plausible zero.
    - `case_count` is EXACT: one entry per selected Case, scored or failed.

    Check-level MET/UNMET outcomes are pinned by ifeval's tests but not yet enforced
    here: draco's multi-run checks carry verdicts per judge pass and need a roll-up
    design before a single check-level outcome is honest (OME-773 follow-up).
    """

    model_config = ConfigDict(populate_by_name=True, extra="forbid", strict=True)

    schema_version: str = Field(default=CANDIDATE_RESULT_SCHEMA, alias="schema")
    benchmark_id: str
    benchmark_revision: str
    case_count: int = Field(ge=0)
    # WHY no lower bound: draco and ifeval scores live in [0, 1], but healthbench's
    # challenge metric is an UNCLIPPED mean over penalty-carrying rubrics — negative
    # scores are meaningful and rankable (clamping here would corrupt the metric).
    # Top-level coverage stays in [0, 1] regardless of a Benchmark's score range.
    score: float | None = Field(le=1.0)
    coverage: float = Field(ge=0.0, le=1.0)
    metrics: dict[str, Any]
    cases: list[CaseResult]
    failures: list[Failure]

    @field_validator("score", mode="before")
    @classmethod
    def _validate_score(cls, value: object) -> object:
        return _finite_score(value)

    @model_validator(mode="after")
    def _enforce_result_contract(self) -> CandidateResult:
        if self.schema_version != CANDIDATE_RESULT_SCHEMA:
            raise ValueError(f"CandidateResult schema must be {CANDIDATE_RESULT_SCHEMA!r}")
        if self.case_count != len(self.cases):
            raise ValueError("case_count must equal the number of retained cases")
        case_ids = [case.case_id for case in self.cases]
        if len(case_ids) != len(set(case_ids)):
            raise ValueError("CandidateResult cannot contain duplicate case_id values")
        if any(failure.case_id is not None for failure in self.failures):
            raise ValueError("a Candidate-level Failure cannot claim a case_id")
        _candidate_outcome(self)
        return self

    def as_payload(self) -> dict[str, Any]:
        """The wire dict — key names, order, and values as the v1 JSON expects."""

        return self.model_dump(by_alias=True)


def candidate_coverage(cases: Sequence[CaseResult], case_count: int) -> float:
    """The exact fraction of selected Cases carrying a numeric Benchmark grade.

    The ONE copy of the coverage formula: `finalize_candidate_result` produces with it
    and `_candidate_outcome` validates against it, so producer and validator cannot
    drift (they used to be two hand-synchronized `round(..., 4)` expressions).
    """

    gradeable = sum(1 for case in cases if case.grade is not None and case.grade.score is not None)
    return round(gradeable / case_count, 4) if case_count else 0.0


def _candidate_outcome(result: CandidateResult) -> None:
    if "coverage" in result.metrics:
        raise ValueError("metrics.coverage is replaced by top-level coverage")
    gradeable = [
        case for case in result.cases if case.grade is not None and case.grade.score is not None
    ]
    expected_coverage = candidate_coverage(result.cases, result.case_count)
    if result.coverage != expected_coverage:
        raise ValueError(
            f"coverage must equal numeric Case grades / selected Cases ({expected_coverage})"
        )
    if result.score is None:
        if result.metrics:
            raise ValueError("a failed or unscored Candidate cannot contain metrics")
        if gradeable:
            raise ValueError("an unscored Candidate cannot contain a numeric Case grade")
        if not result.failures and all(case.status == "scored" for case in result.cases):
            raise ValueError(
                "an unscored Candidate must be explained by a non-scored Case or Failure"
            )
        return
    if not gradeable:
        raise ValueError("a scored Candidate requires at least one numeric Case grade")


def validate_case_id(value: CaseId | None, *, optional: bool = False) -> CaseId | None:
    if value is None and optional:
        return None
    if isinstance(value, bool) or not isinstance(value, int | str):
        raise ValueError("case_id must be a non-boolean integer or non-blank string")
    if isinstance(value, str) and not value.strip():
        raise ValueError("case_id must be a non-boolean integer or non-blank string")
    return value


def validate_finish_reason(value: object) -> str | None:
    """Preserve any non-blank provider finish reason without freezing its vocabulary."""

    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ValueError("finish_reason must be non-empty provider text or null")
    return value


def _json_value(value: object) -> object:
    if not _is_json_value(value):
        raise ValueError("open wire fields must contain JSON values")
    return value


def _is_json_value(value: object) -> bool:
    value_type = type(value)
    valid = value is None or value_type in {str, bool, int}
    if value_type is float:
        valid = math.isfinite(cast(float, value))
    elif value_type is list:
        valid = all(_is_json_value(item) for item in cast(list[object], value))
    elif value_type is dict:
        valid = all(
            type(key) is str and _is_json_value(item)
            for key, item in cast(dict[object, object], value).items()
        )
    return valid


def _finite_score(value: object) -> object:
    if isinstance(value, bool):
        raise ValueError("score must be a finite number or null")
    if isinstance(value, int | float) and not math.isfinite(value):
        raise ValueError("score must be a finite number or null")
    return value


def validate_candidate_outcome(
    answer: object,
    output: object,
    refusal: object,
    *,
    status: CandidateInvocationStatus,
    benchmark: str,
) -> None:
    """Validate the evaluator-text/output/refusal triple every benchmark record binds.

    The ONE copy of the outcome-triple invariant (it used to live byte-identically in
    draco and healthbench records, with a drifted third variant in ifeval): the answer
    is the evaluator text, exactly one of output/refusal is carried, and the answer
    equals whichever one is present. `benchmark` only labels the error messages.
    """

    if not isinstance(answer, str):
        raise ValueError(f"{benchmark} Candidate answer must be text")
    if status == "completed":
        if not isinstance(output, str) or refusal is not None or answer != output:
            raise ValueError(
                f"{benchmark} completed Candidate must carry its exact evaluator text as output"
            )
        return
    if status != "refused":
        raise ValueError(f"{benchmark} Candidate status must be completed or refused")
    if output is not None:
        raise ValueError(f"{benchmark} refused Candidate cannot carry output")
    if refusal is not None and (not isinstance(refusal, str) or not refusal.strip()):
        raise ValueError(f"{benchmark} Candidate refusal must be non-empty text or null")
    if answer != (refusal or ""):
        raise ValueError(f"{benchmark} Candidate refusal must equal its evaluator text")


def encode_candidate_invocation(
    output: str,
    finish_reason: str | None,
    refusal: str | None,
    execution: CorrectiveExecution | None = None,
    *,
    status: CandidateInvocationStatus | None = None,
    operations: Sequence[OperationOutput] | None = None,
) -> str:
    """Encode one Candidate answer without discarding its provider-originated outcome."""

    invocation = CandidateInvocation(
        status=status or ("refused" if refusal is not None else "completed"),
        output=output,
        finish_reason=finish_reason,
        refusal=refusal,
        execution=execution,
        operations=None if operations is None else list(operations),
    )
    return json.dumps(
        invocation.model_dump(by_alias=True),
        ensure_ascii=False,
        separators=(",", ":"),
    )


def decode_candidate_invocation_record(value: str) -> CandidateInvocation:
    """Decode the exact Candidate Invocation envelope once into a typed value."""

    try:
        decoded = json.loads(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Candidate Invocation result is not JSON: {exc}") from None
    if not isinstance(decoded, Mapping) or decoded.get("schema") != CANDIDATE_INVOCATION_SCHEMA:
        raise ValueError("Candidate Invocation result has an unsupported schema")
    # WHY: `operations` (OME-843) is the one optional key — its absence keeps the
    # legacy shape valid, and no other deviation is tolerated.
    if set(decoded) - {"operations"} != {
        "schema",
        "status",
        "output",
        "finish_reason",
        "refusal",
        "execution",
    }:
        raise ValueError("Candidate Invocation result has an invalid shape")
    if decoded["execution"] is not None:
        validate_corrective_execution(decoded["execution"])
    try:
        return CandidateInvocation.model_validate(decoded)
    except ValueError as exc:
        raise ValueError(f"Candidate Invocation result is invalid: {exc}") from None


def decode_candidate_invocation(value: str) -> tuple[str, str | None, str | None]:
    """Decode and validate the internal value returned by the Candidate adapter."""

    decoded = decode_candidate_invocation_record(value)
    return decoded.output, decoded.finish_reason, decoded.refusal


def decode_candidate_execution(value: str) -> CorrectiveExecution | None:
    """Decode the optional execution provenance carried by a Candidate Invocation."""

    return decode_candidate_invocation_record(value).execution


__all__ = [
    "CANDIDATE_BINDING",
    "CANDIDATE_INPUT_SCHEMA",
    "CANDIDATE_INVOCATION_SCHEMA",
    "CANDIDATE_MESSAGE_ROLES",
    "CANDIDATE_RESULT_SCHEMA",
    "CANDIDATE_ROUTE",
    "CandidateInvocation",
    "CandidateInvocationStatus",
    "CaseId",
    "CaseGrade",
    "CaseResult",
    "CandidateResult",
    "CorrectiveExecution",
    "OperationOutput",
    "OperationAccounting",
    "OperationCache",
    "OperationUsage",
    "Check",
    "Evidence",
    "EvidenceProducer",
    "Failure",
    "candidate_coverage",
    "decode_candidate_execution",
    "decode_candidate_invocation",
    "decode_candidate_invocation_record",
    "encode_candidate_invocation",
    "is_valid_corrective_execution",
    "validate_candidate_outcome",
    "validate_corrective_execution",
    "validate_case_id",
    "validate_finish_reason",
]
