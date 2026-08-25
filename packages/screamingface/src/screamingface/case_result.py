"""Immutable, Benchmark-neutral Case Result values."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Literal

from screamingface._immutable_json import freeze_json, freeze_mapping, thaw_json, thaw_mapping
from screamingface._report_primitives import (
    CaseId,
    Failure,
    _case_id,
    _nonblank_text,
    _nonempty_text,
)

# The Engine's versioned wrapper for native multi-turn Candidate input; kept in lock-step
# with url4-cloud's `benchmarks/contract.py` CANDIDATE_INPUT_SCHEMA.
_CANDIDATE_INPUT_SCHEMA = "screamingface.candidate-input.v1"

type EvidenceOutcome = Literal["MET", "UNMET", "PASS", "FAIL"]
type CheckOutcome = Literal["MET", "UNMET"]

# The Engine's explicit per-Case outcome; kept in lock-step with url4-cloud's
# `benchmarks/contract.py` CaseStatus.
type CaseStatus = Literal["scored", "refused", "failed"]
type StopReason = Literal["passed", "max_rounds"]
# Which side refused a refused Case — derived from the two provider-verbatim signals
# the Engine's runner classifies a refusal from (OME-745, `runner/model_response.py`);
# never carried on the wire.
type RefusalKind = Literal["provider_declined", "model_refusal"]


@dataclass(frozen=True, slots=True)
class EvidenceProducer:
    """The Engine-known producer of one observed grading result."""

    type: str
    id: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "type", _nonempty_text(self.type, "Evidence producer type"))
        object.__setattr__(self, "id", _nonempty_text(self.id, "Evidence producer id"))

    def to_dict(self) -> dict[str, object]:
        return {"type": self.type, "id": self.id}


@dataclass(frozen=True, slots=True, init=False)
class Evidence:
    """One exact observation accepted or rejected by a grading Check."""

    sequence: int
    producer: EvidenceProducer
    valid: bool
    outcome: EvidenceOutcome | None
    explanation: str | None
    raw_output: object
    _metadata: Mapping[str, object] = field(repr=False)

    def __init__(
        self,
        *,
        sequence: int,
        producer: EvidenceProducer,
        valid: bool,
        raw_output: object,
        outcome: EvidenceOutcome | None = None,
        explanation: str | None = None,
        metadata: Mapping[str, object] | None = None,
    ) -> None:
        if isinstance(sequence, bool) or not isinstance(sequence, int) or sequence < 1:
            raise ValueError("Evidence sequence must be a positive integer")
        if not isinstance(producer, EvidenceProducer):
            raise TypeError("Evidence producer must be an sf.EvidenceProducer")
        if not isinstance(valid, bool):
            raise TypeError("Evidence valid must be a boolean")
        if outcome not in {None, "MET", "UNMET", "PASS", "FAIL"}:
            raise ValueError("Evidence outcome must be MET, UNMET, PASS, FAIL, or None")
        if explanation is not None:
            explanation = _string(explanation, "Evidence explanation")
        if not valid and (outcome is not None or explanation is not None):
            raise ValueError("invalid Evidence cannot contain an outcome or explanation")
        values = {
            "sequence": sequence,
            "producer": producer,
            "valid": valid,
            "outcome": freeze_json(outcome, "Evidence outcome"),
            "explanation": explanation,
            "raw_output": freeze_json(raw_output, "Evidence raw_output"),
            "_metadata": freeze_mapping(metadata or {}, "Evidence metadata"),
        }
        for name, value in values.items():
            object.__setattr__(self, name, value)

    @property
    def metadata(self) -> Mapping[str, object]:
        return self._metadata

    def to_dict(self) -> dict[str, object]:
        value: dict[str, object] = {
            "sequence": self.sequence,
            "producer": self.producer.to_dict(),
            "valid": self.valid,
            "raw_output": thaw_json(self.raw_output),
            "metadata": thaw_mapping(self._metadata),
        }
        if self.outcome is not None:
            value["outcome"] = thaw_json(self.outcome)
        if self.explanation is not None:
            value["explanation"] = self.explanation
        return value


@dataclass(frozen=True, slots=True, init=False)
class Check:
    """One ordered Benchmark-owned grading check and all of its Evidence."""

    type: str
    id: str
    label: str
    evidence: tuple[Evidence, ...]
    outcome: CheckOutcome | None
    score: float | None
    _metadata: Mapping[str, object] = field(repr=False)

    def __init__(
        self,
        *,
        type: str,
        id: str,
        label: str,
        evidence: Sequence[Evidence],
        metadata: Mapping[str, object] | None = None,
        outcome: CheckOutcome | None = None,
        score: float | None = None,
    ) -> None:
        selected_evidence = tuple(evidence)
        if any(not isinstance(item, Evidence) for item in selected_evidence):
            raise TypeError("Check evidence must contain sf.Evidence values")
        sequences = [item.sequence for item in selected_evidence]
        if sequences != sorted(sequences) or len(sequences) != len(set(sequences)):
            raise ValueError("Check Evidence sequences must be unique and ordered")
        if outcome not in {None, "MET", "UNMET"}:
            raise ValueError("Check outcome must be MET, UNMET, or None")
        values = {
            "type": _nonempty_text(type, "Check type"),
            "id": _nonempty_text(id, "Check id"),
            "label": _string(label, "Check label"),
            "evidence": selected_evidence,
            "outcome": outcome,
            "score": _optional_check_score(score),
            "_metadata": freeze_mapping(metadata or {}, "Check metadata"),
        }
        for name, value in values.items():
            object.__setattr__(self, name, value)

    @property
    def metadata(self) -> Mapping[str, object]:
        return self._metadata

    def to_dict(self) -> dict[str, object]:
        value: dict[str, object] = {
            "type": self.type,
            "id": self.id,
            "label": self.label,
            "evidence": [item.to_dict() for item in self.evidence],
            "metadata": thaw_mapping(self._metadata),
        }
        if self.outcome is not None:
            value["outcome"] = thaw_json(self.outcome)
        if self.score is not None:
            value["score"] = self.score
        return value


@dataclass(frozen=True, slots=True, init=False)
class CaseGrade:
    """One Benchmark-owned grade for a Case."""

    method: str
    score: float | None
    checks: tuple[Check, ...]
    _metrics: Mapping[str, object] = field(repr=False)

    def __init__(
        self,
        *,
        method: str,
        score: float | None,
        metrics: Mapping[str, object],
        checks: Sequence[Check],
    ) -> None:
        selected_checks = tuple(checks)
        if any(not isinstance(item, Check) for item in selected_checks):
            raise TypeError("Case Grade checks must contain sf.Check values")
        ids = [item.id for item in selected_checks]
        if len(ids) != len(set(ids)):
            raise ValueError("Case Grade Check ids must be unique")
        values = {
            "method": _nonempty_text(method, "Case Grade method"),
            "score": _optional_case_score(score),
            "checks": selected_checks,
            "_metrics": freeze_mapping(metrics, "Case Grade metrics"),
        }
        for name, value in values.items():
            object.__setattr__(self, name, value)

    @property
    def metrics(self) -> Mapping[str, object]:
        return self._metrics

    def to_dict(self) -> dict[str, object]:
        return {
            "method": self.method,
            "score": self.score,
            "metrics": thaw_mapping(self._metrics),
            "checks": [item.to_dict() for item in self.checks],
        }


@dataclass(frozen=True, slots=True)
class CaseOperation:
    """One Candidate operation's captured output for a Case.

    FEATURE: OME-843 member-output capture — the Engine attributes each member and
    synthesis call's terminal output to its stable operation ID so Fusion contribution
    analysis works from a saved Report. `output`/`finish_reason` stay ``None`` when the
    Engine could not attribute unambiguously — absence of evidence, never a guess.
    """

    operation_id: str
    output: str | None
    finish_reason: str | None

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "operation_id", _nonblank_text(self.operation_id, "Case Operation operation_id")
        )
        if self.output is not None and not isinstance(self.output, str):
            raise TypeError("Case Operation output must be text or None")
        if self.finish_reason is not None:
            object.__setattr__(
                self,
                "finish_reason",
                _nonblank_text(self.finish_reason, "Case Operation finish_reason"),
            )

    def to_dict(self) -> dict[str, object]:
        return {
            "operation_id": self.operation_id,
            "output": self.output,
            "finish_reason": self.finish_reason,
        }


@dataclass(frozen=True, slots=True, init=False)
class CaseResult:
    """The complete retained result for one selected Benchmark Case."""

    status: CaseStatus
    case_id: CaseId
    input: str
    output: str | None
    finish_reason: str | None
    refusal: str | None
    stop_reason: StopReason | None
    rounds_executed: int | None
    grade: CaseGrade | None
    failures: tuple[Failure, ...]
    operations: tuple[CaseOperation, ...] | None
    _metadata: Mapping[str, object] = field(repr=False)

    def __init__(
        self,
        *,
        case_id: CaseId,
        input: str,
        output: str | None,
        finish_reason: str | None,
        grade: CaseGrade | None,
        failures: Sequence[Failure],
        metadata: Mapping[str, object],
        status: CaseStatus | None = None,
        refusal: str | None = None,
        stop_reason: StopReason | None = None,
        rounds_executed: int | None = None,
        operations: Sequence[CaseOperation] | None = None,
    ) -> None:
        case_id = _case_id(case_id)
        input = _nonempty_text(input, "Case Result input")
        if output is not None and not isinstance(output, str):
            raise TypeError("Case Result output must be text or None")
        if grade is not None and not isinstance(grade, CaseGrade):
            raise TypeError("Case Result grade must be an sf.CaseGrade or None")
        if finish_reason is not None:
            finish_reason = _nonblank_text(finish_reason, "Case Result finish_reason")
        if refusal is not None:
            refusal = _nonblank_text(refusal, "Case Result refusal")
        stop_reason, rounds_executed = _validate_execution(stop_reason, rounds_executed)
        selected_failures = tuple(failures)
        if any(not isinstance(item, Failure) for item in selected_failures):
            raise TypeError("Case Result failures must contain sf.Failure values")
        selected_operations = None if operations is None else tuple(operations)
        if selected_operations is not None and any(
            not isinstance(item, CaseOperation) for item in selected_operations
        ):
            raise TypeError("Case Result operations must contain CaseOperation values")
        status = _validate_case_outcome(
            status,
            case_id,
            refusal,
            grade,
            output,
            selected_failures,
        )
        values = {
            "status": status,
            "case_id": case_id,
            "input": input,
            "output": output,
            "finish_reason": finish_reason,
            "refusal": refusal,
            "stop_reason": stop_reason,
            "rounds_executed": rounds_executed,
            "grade": grade,
            "failures": selected_failures,
            "operations": selected_operations,
            "_metadata": freeze_mapping(metadata, "Case Result metadata"),
        }
        for name, value in values.items():
            object.__setattr__(self, name, value)

    @property
    def metadata(self) -> Mapping[str, object]:
        return self._metadata

    @property
    def refusal_kind(self) -> RefusalKind | None:
        """Which side refused: the provider declined, or the model answered by refusing.

        The Engine classifies a refused turn from two provider-verbatim signals it
        already publishes on every Case (OME-745, the Engine's
        `runner/model_response.py`): a ``content_filter`` finish reason means the
        provider's filter terminated the call, and a non-null ``refusal`` carries the
        model's own refusal message. This property is the client's ONE reading of
        that split, checked in the Engine classifier's own order — ``content_filter``
        first, so a filtered turn that also carries refusal text still reads as the
        provider declining. ``None`` for any non-refused Case, and for a refused Case
        whose payload carries neither signal (older Engines) — unknown, never a
        guess. Derived, never serialized: ``to_dict`` stays byte-identical.
        """

        if self.status != "refused":
            return None
        if self.finish_reason == "content_filter":
            return "provider_declined"
        return "model_refusal" if self.refusal is not None else None

    @property
    def conversation(self) -> tuple[tuple[str, str], ...] | None:
        """The Case's chat turns, or ``None`` when the input is plain text.

        Engine-owned multi-turn Benchmarks (HealthBench first) wrap structured
        turns in the versioned candidate-input envelope; single-turn Benchmarks
        (DRACO, IFEval) send plain prompt text. This property is the SDK's ONE
        decode point for that wire format: it returns ``(role, content)`` turns
        only when the input is a JSON object explicitly carrying the envelope
        schema, and ``None`` for everything else — decoding never raises, so the
        worst case is seeing the raw string, never a crash. Renderers consume
        ``display_input`` / ``prompt_preview`` below and stay format-blind.
        """

        return _decode_candidate_envelope(self.input)

    @property
    def display_input(self) -> str:
        """The input as readable text: a role-labeled transcript, or the raw value."""

        turns = self.conversation
        if turns is None:
            return self.input if isinstance(self.input, str) else str(self.input)
        return "\n\n".join(f"{role}: {content}" for role, content in turns)

    @property
    def prompt_preview(self) -> str:
        """The Case's question — the first user turn, or the plain input text."""

        turns = self.conversation
        if turns is None:
            return self.input if isinstance(self.input, str) else str(self.input)
        for role, content in turns:
            if role == "user":
                return content
        return turns[0][1]

    def to_dict(self) -> dict[str, object]:
        selected = {
            "status": self.status,
            "case_id": self.case_id,
            "input": thaw_json(self.input),
            "output": thaw_json(self.output),
            "finish_reason": self.finish_reason,
            "refusal": self.refusal,
            "stop_reason": self.stop_reason,
            "rounds_executed": self.rounds_executed,
            "grade": None if self.grade is None else self.grade.to_dict(),
            "failures": [failure.to_dict() for failure in self.failures],
            "metadata": thaw_mapping(self._metadata),
        }
        # INVARIANT: absence stays absence — pre-OME-843 payloads and solo Candidates
        # export byte-identically, so the key appears only when the Engine attributed.
        if self.operations is not None:
            selected["operations"] = [operation.to_dict() for operation in self.operations]
        return selected


def _decode_candidate_envelope(value: object) -> tuple[tuple[str, str], ...] | None:
    """Decode the versioned chat envelope; ``None`` for anything that is not exactly it."""

    try:
        decoded = json.loads(value) if isinstance(value, str) else None
    except ValueError:
        decoded = None
    envelope = (
        decoded
        if isinstance(decoded, Mapping) and decoded.get("schema") == _CANDIDATE_INPUT_SCHEMA
        else None
    )
    messages = envelope.get("messages") if envelope is not None else None
    parsed = [_turn(message) for message in messages] if isinstance(messages, list) else []
    turns = [turn for turn in parsed if turn is not None]
    # All-or-nothing: one malformed message means this is not a trustworthy
    # transcript — fall back to showing the raw string rather than a partial one.
    if not turns or len(turns) != len(parsed):
        return None
    return tuple(turns)


def _turn(message: object) -> tuple[str, str] | None:
    role = message.get("role") if isinstance(message, Mapping) else None
    content = message.get("content") if isinstance(message, Mapping) else None
    return (role, content) if isinstance(role, str) and isinstance(content, str) else None


def _optional_number(value: object, label: str) -> float | None:
    return None if value is None else _required_number(value, label)


def _validate_execution(
    stop_reason: StopReason | None,
    rounds_executed: int | None,
) -> tuple[StopReason | None, int | None]:
    if stop_reason not in {None, "passed", "max_rounds"}:
        raise ValueError("Case Result stop_reason must be passed, max_rounds, or None")
    if rounds_executed is not None and (
        isinstance(rounds_executed, bool)
        or not isinstance(rounds_executed, int)
        or rounds_executed < 1
    ):
        raise ValueError("Case Result rounds_executed must be a positive integer or None")
    if (stop_reason is None) != (rounds_executed is None):
        raise ValueError("Case Result stop_reason and rounds_executed must be present together")
    return stop_reason, rounds_executed


def _optional_check_score(value: object) -> float | None:
    selected = _optional_number(value, "Check score")
    if selected is not None and not 0.0 <= selected <= 1.0:
        raise ValueError("Check score must be between 0 and 1")
    return selected


def _optional_case_score(value: object) -> float | None:
    selected = _optional_number(value, "Case Grade score")
    if selected is not None and selected > 1.0:
        raise ValueError("Case Grade score must be at most 1")
    return selected


def _string(value: object, label: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{label} must be text")
    return value


def _required_number(value: object, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise TypeError(f"{label} must be a finite number")
    selected = float(value)
    if selected in {float("inf"), float("-inf")} or selected != selected:
        raise ValueError(f"{label} must be a finite number")
    return selected


def _validate_case_outcome(
    status: CaseStatus | None,
    case_id: CaseId,
    refusal: str | None,
    grade: CaseGrade | None,
    output: object,
    failures: Sequence[Failure],
) -> CaseStatus:
    """Validate one immutable value against the Engine's closed outcome contract.

    The wire decoder always requires an explicit status. Derivation exists only for
    directly constructed Python values, where it avoids forcing test/data authors to
    repeat a status already unambiguously determined by the complete Case shape.
    """

    selected_status = _case_status(status, refusal, grade)
    if any(failure.case_id != case_id for failure in failures):
        raise ValueError("every Case Result Failure must reference its own case_id")
    if selected_status == "scored":
        _validate_scored_case(refusal, grade, output, failures)
    elif selected_status == "refused":
        _validate_refused_case(refusal, grade, output, failures)
    else:
        _validate_failed_case(refusal, grade, failures)
    return selected_status


def _case_status(
    status: CaseStatus | None,
    refusal: str | None,
    grade: CaseGrade | None,
) -> CaseStatus:
    if status is not None:
        if status not in {"scored", "refused", "failed"}:
            raise ValueError("Case Result status must be 'scored', 'refused', or 'failed'")
        return status
    if refusal is not None:
        return "refused"
    return "scored" if grade is not None and grade.score is not None else "failed"


def _validate_scored_case(
    refusal: str | None,
    grade: CaseGrade | None,
    output: object,
    failures: Sequence[Failure],
) -> None:
    if grade is None or grade.score is None or output is None or refusal is not None or failures:
        raise ValueError(
            "Case Result status 'scored' requires output and a numeric grade and cannot "
            "carry refusal or failures"
        )


def _validate_refused_case(
    refusal: str | None,
    grade: CaseGrade | None,
    output: object,
    failures: Sequence[Failure],
) -> None:
    if output is not None or grade is None:
        raise ValueError("Case Result status 'refused' requires no output and a grade")
    if grade.score is not None and failures:
        raise ValueError("a graded refused Case Result cannot contain failures")
    if grade.score is None and (
        not failures or any(failure.stage != "grading" for failure in failures)
    ):
        raise ValueError("an ungraded refused Case Result requires only grading failures")


def _validate_failed_case(
    refusal: str | None,
    grade: CaseGrade | None,
    failures: Sequence[Failure],
) -> None:
    if (
        not failures
        or refusal is not None
        or any(failure.code == "provider_refusal" for failure in failures)
        or grade is not None
        and grade.score is not None
    ):
        raise ValueError(
            "Case Result status 'failed' requires failures, no refusal, and no numeric grade"
        )


__all__ = ["CaseGrade", "CaseResult", "Check", "Evidence", "EvidenceProducer"]
