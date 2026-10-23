"""Immutable, Benchmark-neutral Case Result values."""

from __future__ import annotations

import base64
import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import TYPE_CHECKING, Literal, NotRequired, TypedDict

from screamingface._case_views import case_answers, case_trace
from screamingface._immutable_json import freeze_json, freeze_mapping, thaw_json, thaw_mapping
from screamingface._report_primitives import (
    CaseId,
    Failure,
    _case_id,
    _nonblank_text,
    _nonempty_text,
    _optional_number,
)
from screamingface.answer import Answer
from screamingface.combine_evidence import CombineEvidence
from screamingface.operation_accounting import OperationAccounting

if TYPE_CHECKING:
    from screamingface.operation import OperationInfo
    from screamingface.report_trace import TraceEntry

# The Engine's versioned wrapper for native multi-turn Candidate input; kept in lock-step
# with url4-cloud's `benchmarks/contract.py` CANDIDATE_INPUT_SCHEMA.
_CANDIDATE_INPUT_SCHEMA = "screamingface.candidate-input.v1"
# FEATURE (OME-1680): v2 lets a user message carry pictures and PDFs as content parts (OME-1678).
_CANDIDATE_INPUT_V2_SCHEMA = "screamingface.candidate-input.v2"
# INVARIANT: equal to the engine's set; pinned by
# tests/unit/test_candidate_input_schema_conformance.py.
_CANDIDATE_INPUT_SCHEMAS = frozenset({_CANDIDATE_INPUT_SCHEMA, _CANDIDATE_INPUT_V2_SCHEMA})
_SCHEMA_FAMILY = "screamingface.candidate-input."
# WHY a shape check before an unknown version is echoed: the schema value is Case data, and a
# hostile or broken one could be long; only a name-like value is shown.
_SHOWN_SCHEMA_RE = re.compile(r"screamingface\.candidate-input\.[A-Za-z0-9_.-]{1,32}")
# The placeholder the engine writes where a picture's `url` or a file's `file_data` was (OME-1679),
# and the one the SDK builds from a `data:` URI itself. WHY a copy: the SDK cannot import engine
# code; a conformance test against the engine's placeholder builder pins these names once it lands.
_PLACEHOLDER_FIELDS = frozenset({"placeholder", "media_type", "size", "sha256"})
_PLACEHOLDER_OPTIONAL_FIELDS = frozenset({"filename"})
# WHY the engine's pattern (`benchmarks/candidate_input.py`): a picture the engine accepted is
# one the SDK can measure.
_DATA_URI_RE = re.compile(
    r"^data:(?P<mime>[\w.+-]+/[\w.+-]+)(?:;[^;,]*)*;base64,(?P<data>.+)$", re.DOTALL
)
_SHA256_RE = re.compile(r"[0-9a-f]{64}")
# WHY 8: enough to tell two pictures of one Case apart at a glance, short enough for one line.
_SHOWN_DIGEST_CHARS = 8
_KIB = 1024

type EvidenceOutcome = Literal["MET", "UNMET", "PASS", "FAIL"]
type CheckOutcome = Literal["MET", "UNMET"]

# The Engine's explicit per-Case outcome; kept in lock-step with url4-cloud's
# `benchmarks/contract.py` CaseStatus. WHY only two values (OME-1037): `refused`
# meant "provider declined" in most benchmarks and "correct answer" in DRACO — a
# graded refusal is now an ordinary scored Case carrying `refusal` text, and an
# ungradeable one a failed Case whose failures include the `provider_refusal` code.
type CaseStatus = Literal["scored", "failed"]
type StopReason = Literal["passed", "max_rounds"]
# Which side refused a Case that represents a refusal — derived from the two
# provider-verbatim signals the Engine's runner classifies a refusal from (OME-745,
# `runner/model_response.py`); never carried on the wire.
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


def _validated_evidence_parts(
    *,
    sequence: int,
    producer: EvidenceProducer,
    valid: bool,
    outcome: EvidenceOutcome | None,
    explanation: str | None,
    accounting: OperationAccounting | None,
) -> str | None:
    """Validate one Evidence's scalar parts; return the normalized explanation.

    Split out of ``Evidence.__init__`` only to keep that constructor readable —
    the rules themselves are unchanged, and the one that carries meaning is the
    last: a REJECTED observation may not also claim an outcome or an
    explanation, because a rejected reply was never interpreted.
    """
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
    if accounting is not None and not isinstance(accounting, OperationAccounting):
        raise TypeError("Evidence accounting must be an sf.OperationAccounting or None")
    return explanation


@dataclass(frozen=True, slots=True, init=False)
class Evidence:
    """One exact observation accepted or rejected by a grading Check."""

    sequence: int
    producer: EvidenceProducer
    valid: bool
    outcome: EvidenceOutcome | None
    explanation: str | None
    raw_output: object
    accounting: OperationAccounting | None
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
        accounting: OperationAccounting | None = None,
    ) -> None:
        explanation = _validated_evidence_parts(
            sequence=sequence,
            producer=producer,
            valid=valid,
            outcome=outcome,
            explanation=explanation,
            accounting=accounting,
        )
        values = {
            "sequence": sequence,
            "producer": producer,
            "valid": valid,
            "outcome": freeze_json(outcome, "Evidence outcome"),
            "explanation": explanation,
            "raw_output": freeze_json(raw_output, "Evidence raw_output"),
            "accounting": accounting,
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
            "accounting": None if self.accounting is None else self.accounting.to_dict(),
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
    """One Benchmark-owned grade for a Case.

    FEATURE (OME-1268): `scores` carries the Benchmark's Named Scores for this Case, keyed by
    the scorer's name (SQuAD: `f1`, `exact`), the Headline Score first. `score` IS the
    headline. A single-scorer Benchmark has none, and every existing caller builds a grade
    without the keyword.
    """

    method: str
    score: float | None
    checks: tuple[Check, ...]
    _metrics: Mapping[str, object] = field(repr=False)
    _scores: Mapping[str, float | None] = field(repr=False)

    def __init__(
        self,
        *,
        method: str,
        score: float | None,
        metrics: Mapping[str, object],
        checks: Sequence[Check],
        scores: Mapping[str, float | None] | None = None,
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
            "_scores": named_scores(scores, "Case Grade"),
        }
        for name, value in values.items():
            object.__setattr__(self, name, value)

    @property
    def metrics(self) -> Mapping[str, object]:
        return self._metrics

    @property
    def scores(self) -> Mapping[str, float | None]:
        """The Named Scores for this Case, headline first; empty on a single-scorer Benchmark."""
        return self._scores

    def to_dict(self) -> dict[str, object]:
        value: dict[str, object] = {
            "method": self.method,
            "score": self.score,
            "metrics": thaw_mapping(self._metrics),
            "checks": [item.to_dict() for item in self.checks],
        }
        # WHY only when set: a Case Grade's dict mirrors the Engine's wire one-to-one (the
        # exact-contract round-trip tests pin it), and the wire omits the key on a
        # single-scorer Benchmark. The Candidate Result carries the stable `scores` key
        # (`{}` when absent), so a reader of report.json never has to guess.
        if self._scores:
            value["scores"] = dict(self._scores)
        return value


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
    accounting: OperationAccounting | None = None
    combine: CombineEvidence | None = None

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
        if self.accounting is not None and not isinstance(self.accounting, OperationAccounting):
            raise TypeError("Case Operation accounting must be an sf.OperationAccounting or None")
        if self.combine is not None and not isinstance(self.combine, CombineEvidence):
            raise TypeError("Case Operation combine must be an sf.report.CombineEvidence or None")

    def to_dict(self) -> dict[str, object]:
        selected: dict[str, object] = {
            "operation_id": self.operation_id,
            "output": self.output,
            "finish_reason": self.finish_reason,
            # Required-nullable, mirroring the Engine: the key is always present so
            # a reader can tell "no accounting retained" from "older payload".
            "accounting": None if self.accounting is None else self.accounting.to_dict(),
        }
        # INVARIANT: absence stays absence — the Engine leaves `combine` out for every
        # operation that is not a deterministic combine, so the export does too.
        if self.combine is not None:
            selected["combine"] = self.combine.to_dict()
        return selected


@dataclass(frozen=True, slots=True)
class CaseAttempt:
    """One Attempt at a Case: the answer the Candidate gave that time, and its own grade.

    FEATURE (OME-1458): a Benchmark that declares N Attempts asks each Case N times and
    marks a Check met if any Attempt met it. The Case Result's own ``output`` and ``grade``
    are the folded view (the shown answer and the per-Check fold); this value keeps what
    each Attempt actually said and scored, so a reader can see which Attempt earned a point.

    ``operations`` are this Attempt's own cost records. Under Attempts the Case carries none
    of its own, so every model call is billed exactly once, on the Attempt that made it.
    The Attempt's outcome rules are the Case Result's (scored needs a numeric grade, failed
    needs failures); the owning `CaseResult` checks them, because it knows the Case id.
    """

    attempt: int
    status: CaseStatus
    output: str | None
    finish_reason: str | None
    refusal: str | None
    grade: CaseGrade | None
    failures: tuple[Failure, ...]
    operations: tuple[CaseOperation, ...] | None = None

    def __post_init__(self) -> None:
        if isinstance(self.attempt, bool) or not isinstance(self.attempt, int) or self.attempt < 1:
            raise ValueError("Case Attempt attempt must be a positive integer")
        if self.status not in {"scored", "failed"}:
            raise ValueError("Case Attempt status must be 'scored' or 'failed'")
        if self.output is not None and not isinstance(self.output, str):
            raise TypeError("Case Attempt output must be text or None")
        for name in ("finish_reason", "refusal"):
            value: object = getattr(self, name)
            if value is not None:
                object.__setattr__(self, name, _nonblank_text(value, f"Case Attempt {name}"))
        if self.grade is not None and not isinstance(self.grade, CaseGrade):
            raise TypeError("Case Attempt grade must be an sf.CaseGrade or None")
        object.__setattr__(
            self, "failures", _typed_values(self.failures, Failure, "Case Attempt failures")
        )
        if self.operations is not None:
            object.__setattr__(
                self,
                "operations",
                _typed_values(self.operations, CaseOperation, "Case Attempt operations"),
            )

    def to_dict(self) -> dict[str, object]:
        selected: dict[str, object] = {
            "attempt": self.attempt,
            "status": self.status,
            "output": self.output,
            "finish_reason": self.finish_reason,
            "refusal": self.refusal,
            "grade": None if self.grade is None else self.grade.to_dict(),
            "failures": [failure.to_dict() for failure in self.failures],
        }
        # INVARIANT: absence stays absence, as on the Case Result (OME-843).
        if self.operations is not None:
            selected["operations"] = [operation.to_dict() for operation in self.operations]
        return selected


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
    attempts: tuple[CaseAttempt, ...] | None
    _metadata: Mapping[str, object] = field(repr=False)
    abstained: bool
    # AIDEV-NOTE: write-once, set by CandidateResult for the Candidate that holds this Case; a
    # Case shared by two Candidates keeps its first graph. Never serialized, never compared.
    _operation_graph: Mapping[str, OperationInfo] | None = field(
        default=None, repr=False, compare=False
    )

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
        attempts: Sequence[CaseAttempt] | None = None,
        abstained: bool = False,
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
        selected_attempts = _validated_attempts(attempts, case_id, selected_operations)
        status = _validate_case_outcome(
            status,
            case_id,
            refusal,
            grade,
            output,
            selected_failures,
        )
        abstained = _validated_abstained(abstained, status, grade, output, refusal)
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
            "attempts": selected_attempts,
            "_metadata": freeze_mapping(metadata, "Case Result metadata"),
            "_operation_graph": None,
            "abstained": abstained,
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
        provider declining. Since OME-1037 there is no ``refused`` status: a Case
        represents a refusal when it is scored-with-refusal (the benchmark graded
        the decline) or failed with a ``provider_refusal`` failure (it could not).
        ``None`` for every other Case, and for a refusal payload carrying neither
        signal — unknown, never a guess. Derived, never serialized: ``to_dict``
        stays byte-identical.
        """

        represents_refusal = self.refusal is not None or any(
            failure.code == "provider_refusal" for failure in self.failures
        )
        if not represents_refusal:
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

        A v2 message's parts become lines of its content: text as written, and each
        picture or file as one placeholder line, never its base64 (OME-1680), e.g.
        ``chart.png · image/png · 300 KB · sha256 9f86d081…``.
        """

        return _decode_candidate_envelope(self.input)

    @property
    def display_input(self) -> str:
        """The input as readable text: a role-labeled transcript, or the raw value."""

        turns = self.conversation
        if turns is None:
            return _undecoded_input_text(self.input)
        return "\n\n".join(f"{role}: {content}" for role, content in turns)

    @property
    def prompt_preview(self) -> str:
        """The Case's question — the first user turn, or the plain input text."""

        turns = self.conversation
        if turns is None:
            return _undecoded_input_text(self.input)
        for role, content in turns:
            if role == "user":
                return content
        return turns[0][1]

    def answers(self, operation_id: str | None = None) -> tuple[Answer, ...]:
        """What each member, then each combine step, answered, in author order.

        Empty when the Case has no operations or no combine step. ``operation_id`` limits it to one
        combine operation; an id that is not an operation of this Case raises ValueError.
        """

        return case_answers(self, operation_id)

    def trace(self) -> tuple[TraceEntry, ...]:
        """What every block did for this Case, in order (model calls, extracts, reduce).

        Empty when the Case has no operations. Derived; never part of ``to_dict``.
        """

        return case_trace(self, self._operation_graph)

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
        # INVARIANT (OME-1458): a Benchmark without Attempts exports byte-identically.
        if self.attempts is not None:
            selected["attempts"] = [attempt.to_dict() for attempt in self.attempts]
        # INVARIANT: the mark appears only when true, so every other Case exports unchanged.
        if self.abstained:
            selected["abstained"] = True
        return selected


def _typed_values[T](values: Sequence[T], kind: type[T], label: str) -> tuple[T, ...]:
    """Freeze a sequence into a tuple, refusing any item that is not a ``kind``."""

    selected: tuple[T, ...] = tuple(values)
    if any(not isinstance(item, kind) for item in selected):
        raise TypeError(f"{label} must contain {kind.__name__} values")
    return selected


def _validated_attempts(
    attempts: Sequence[CaseAttempt] | None,
    case_id: CaseId,
    operations: tuple[CaseOperation, ...] | None,
) -> tuple[CaseAttempt, ...] | None:
    """Check a Case's Attempts are numbered 1..N, N ≥ 2, each a valid outcome of this Case.

    WHY N ≥ 2: one Attempt is spelled by absence, so a report has one shape per meaning.
    WHY no Case-level operations beside Attempts: each Attempt carries its own cost records,
    and a second copy at Case level would bill the same model call twice.
    """

    if attempts is None:
        return None
    selected: tuple[CaseAttempt, ...] = tuple(attempts)
    if any(not isinstance(item, CaseAttempt) for item in selected):
        raise TypeError("Case Result attempts must contain CaseAttempt values")
    numbers: list[int] = [item.attempt for item in selected]
    if len(selected) < 2 or numbers != list(range(1, len(selected) + 1)):
        raise ValueError("Case Result attempts must be numbered 1..N with N of at least 2")
    if operations is not None:
        raise ValueError("Case Result operations live on each Attempt when the Case has Attempts")
    for item in selected:
        _validate_case_outcome(
            item.status, case_id, item.refusal, item.grade, item.output, item.failures
        )
    return selected


def _bind_operation_graph(case: CaseResult, operations: Sequence[OperationInfo]) -> None:
    """Give a Case the operation graph of its Candidate, once, in place (never a copy)."""

    if case._operation_graph is None:
        graph = MappingProxyType({operation.id: operation for operation in operations})
        object.__setattr__(case, "_operation_graph", graph)


def _decode_candidate_envelope(value: object) -> tuple[tuple[str, str], ...] | None:
    """Open the versioned chat envelope into display turns; ``None`` for anything else.

    Think of it as reading a sealed letter aloud: text is read as written, and each enclosed
    picture is described by its label instead of being read out byte by byte.

    Stage 1 — is it a known envelope? A JSON object whose ``schema`` is v1 or v2; any other text,
        or an unknown version, is ``None`` and the caller shows the raw string.
    Stage 2 — every message becomes ``(role, content)``. A string content is kept as written; a
        part list (v2 only) becomes one line per part: text as written, a picture or file as its
        placeholder line (see ``_media_placeholder``).
    Stage 3 — all or nothing: one message that cannot be read means ``None``.

    e.g. ``{"schema":"…v2","messages":[{"role":"user","content":[{"type":"text","text":"What is
    the height?"},{"type":"image_url","image_url":{"url":"data:image/png;base64,…"}}]}]}`` →
    ``(("user", "What is the height?\nimage/png · 300 KB · sha256 fc2447cd…"),)``.
    """

    # Stage 1 — is it a known envelope?
    try:
        decoded = json.loads(value) if isinstance(value, str) else None
    except ValueError:
        decoded = None
    schema: object = decoded.get("schema") if isinstance(decoded, Mapping) else None
    envelope = (
        decoded
        if isinstance(decoded, Mapping)
        # WHY the str check first: a dict or list schema is unhashable, and the engine reads such
        # an input as a plain prompt, so its result must render, not raise.
        and isinstance(schema, str)
        and schema in _CANDIDATE_INPUT_SCHEMAS
        else None
    )
    allows_parts: bool = schema == _CANDIDATE_INPUT_V2_SCHEMA
    # Stage 2 — every message.
    messages = envelope.get("messages") if envelope is not None else None
    parsed = (
        [_turn(message, allows_parts=allows_parts) for message in messages]
        if isinstance(messages, list)
        else []
    )
    turns = [turn for turn in parsed if turn is not None]
    # Stage 3 — all-or-nothing: one malformed message means this is not a trustworthy
    # transcript — fall back to showing the raw string rather than a partial one.
    if not turns or len(turns) != len(parsed):
        return None
    return tuple(turns)


def _undecoded_input_text(value: object) -> str:
    """What the views show for an input the conversation cannot read: the raw text as written,
    or one line when it names a candidate-input version this SDK does not know.

    WHY the line (OME-1680): an engine newer than this SDK may send a newer envelope, and its raw
    text can be megabytes of base64; the line asks for an upgrade instead and never raises.
    e.g. ``{"schema": "screamingface.candidate-input.v3", …}`` → ``unsupported candidate-input
    schema screamingface.candidate-input.v3 — upgrade screamingface to view this input``.
    """

    text: str = value if isinstance(value, str) else str(value)
    try:
        decoded: object = json.loads(text) if text.lstrip().startswith("{") else None
    except (ValueError, RecursionError):
        decoded = None
    schema: object = decoded.get("schema") if isinstance(decoded, Mapping) else None
    if (
        not isinstance(schema, str)
        or not schema.startswith(_SCHEMA_FAMILY)
        or schema in _CANDIDATE_INPUT_SCHEMAS
    ):
        return text
    shown: str = schema if _SHOWN_SCHEMA_RE.fullmatch(schema) else f"{_SCHEMA_FAMILY}*"
    return f"unsupported candidate-input schema {shown} — upgrade screamingface to view this input"


def _turn(message: object, *, allows_parts: bool) -> tuple[str, str] | None:
    """One message as ``(role, content)``; a v2 part list becomes one line per part."""

    role = message.get("role") if isinstance(message, Mapping) else None
    content = message.get("content") if isinstance(message, Mapping) else None
    if not isinstance(role, str):
        return None
    if isinstance(content, str):
        return (role, content)
    lines: list[str] | None = _part_lines(content) if allows_parts else None
    return None if lines is None else (role, "\n".join(lines))


def _part_lines(content: object) -> list[str] | None:
    """A v2 part list as display lines, in order; ``None`` if any part cannot be read."""

    parts: list[object] = list(content) if isinstance(content, list) else []
    parsed: list[str | None] = [_part_line(part) for part in parts]
    lines: list[str] = [line for line in parsed if line is not None]
    return lines if lines and len(lines) == len(parsed) else None


def _part_line(part: object) -> str | None:
    """One v2 part as display text: text as written, a picture or file as its placeholder."""

    body: Mapping[object, object] = part if isinstance(part, Mapping) else {}
    if body.get("type") == "text":
        text: object = body.get("text")
        return text if isinstance(text, str) else None
    placeholder: _Placeholder | None = _part_placeholder(body)
    return None if placeholder is None else _placeholder_line(placeholder)


def _part_placeholder(part: Mapping[object, object]) -> _Placeholder | None:
    """The placeholder of a picture (``image_url.url``) or file (``file.file_data``) part."""

    kind: object = part.get("type")
    if kind == "image_url":
        picture: object = part.get("image_url")
        url: object = picture.get("url") if isinstance(picture, Mapping) else None
        return _media_placeholder("image", url, filename=None)
    file: object = part.get("file") if kind == "file" else None
    filename: object = file.get("filename") if isinstance(file, Mapping) else None
    if not isinstance(file, Mapping) or not isinstance(filename, str | None):
        return None
    return _media_placeholder("file", file.get("file_data"), filename=filename)


class _Placeholder(TypedDict):
    """What a Case Result shows instead of a picture's or file's bytes (OME-1679's shape)."""

    placeholder: Literal["image", "file"]
    media_type: str
    size: int
    sha256: str
    filename: NotRequired[str]


def _media_placeholder(
    kind: Literal["image", "file"], source: object, *, filename: str | None
) -> _Placeholder | None:
    """The placeholder for one picture or file, from either form it can arrive in.

    A ``data:`` URI is decoded here, so its size and sha256 are those of the real bytes (not of
    the base64). A placeholder object the engine already wrote is checked field by field and
    used as is. Either way the part's own filename, when it has one, names it. Anything else
    (an ``https://`` URL, broken base64, a malformed object) is ``None``, so the caller falls
    back rather than guessing.

    e.g. ``("image", "data:image/png;base64,…300 KB…", filename=None)`` →
    ``{"placeholder": "image", "media_type": "image/png", "size": 307200, "sha256": "fc24…"}``.
    """

    placeholder: _Placeholder | None = (
        _placeholder_object(kind, source)
        if isinstance(source, Mapping)
        else _decoded_placeholder(kind, source)
    )
    # WHY the part's filename wins: it sits beside file_data on the part, so it survives the
    # engine replacing file_data with a placeholder object.
    if placeholder is not None and filename:
        placeholder["filename"] = filename
    return placeholder


def _decoded_placeholder(kind: Literal["image", "file"], source: object) -> _Placeholder | None:
    """The placeholder of an inline ``data:`` URI, measured from its decoded bytes."""

    decoded: tuple[str, bytes] | None = _data_uri_bytes(source)
    if decoded is None:
        return None
    media_type, data = decoded
    return {
        "placeholder": kind,
        "media_type": media_type,
        "size": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
    }


def _data_uri_bytes(source: object) -> tuple[str, bytes] | None:
    """The lower-cased media type and decoded bytes of an inline ``data:`` URI; else ``None``."""

    match: re.Match[str] | None = _DATA_URI_RE.match(source) if isinstance(source, str) else None
    if match is None:
        return None
    # WHY strip and re-pad, as the engine's placeholder builder does (`candidate_input.py`,
    # OME-1679): line breaks and dropped `=` padding spell the same bytes, so the sha256 shown here
    # is the engine's for the same picture; strict decoding of what remains refuses anything else.
    compact: str = "".join(match["data"].split())
    compact += "=" * (-len(compact) % 4)
    try:
        return match["mime"].lower(), base64.b64decode(compact, validate=True)
    # WHY ValueError: binascii.Error, raised on broken base64, is one.
    except ValueError:
        return None


def _placeholder_object(
    kind: Literal["image", "file"], value: Mapping[object, object]
) -> _Placeholder | None:
    """The engine's placeholder object for a ``kind`` part, checked field by field, or ``None``."""

    keys: set[object] = set(value)
    media_type: object = value.get("media_type")
    size: object = value.get("size")
    sha256: object = value.get("sha256")
    filename: object = value.get("filename")
    if (
        not _PLACEHOLDER_FIELDS <= keys <= _PLACEHOLDER_FIELDS | _PLACEHOLDER_OPTIONAL_FIELDS
        or value.get("placeholder") != kind
        or not isinstance(media_type, str)
        or not media_type
        or not isinstance(size, int)
        or isinstance(size, bool)
        or size < 0
        or not isinstance(sha256, str)
        or _SHA256_RE.fullmatch(sha256) is None
        or ("filename" in keys and (not isinstance(filename, str) or not filename))
    ):
        return None
    placeholder: _Placeholder = {
        "placeholder": kind,
        "media_type": media_type,
        "size": size,
        "sha256": sha256,
    }
    if isinstance(filename, str):
        placeholder["filename"] = filename
    return placeholder


def _placeholder_line(placeholder: _Placeholder) -> str:
    """The placeholder as one line, e.g. ``chart.png · image/png · 300 KB · sha256 9f86d081…``."""

    fields: list[str] = [
        placeholder["media_type"],
        _size_text(placeholder["size"]),
        f"sha256 {placeholder['sha256'][:_SHOWN_DIGEST_CHARS]}…",
    ]
    if "filename" in placeholder:
        fields.insert(0, placeholder["filename"])
    return " · ".join(fields)


def _size_text(count: int) -> str:
    """A byte count as people read it: ``512 B``, ``300 KB``, ``2.4 MB`` (the Report's rule)."""

    if count < _KIB:
        return f"{count} B"
    if count < _KIB * _KIB:
        return f"{count / _KIB:.0f} KB"
    return f"{count / (_KIB * _KIB):.1f} MB"


def _validated_abstained(
    abstained: object,
    status: CaseStatus,
    grade: CaseGrade | None,
    output: str | None,
    refusal: str | None,
) -> bool:
    if not isinstance(abstained, bool):
        raise TypeError("Case Result abstained must be a bool")
    if abstained:
        _require_abstained(status, grade, output, refusal)
    return abstained


def _require_abstained(
    status: CaseStatus, grade: CaseGrade | None, output: str | None, refusal: str | None
) -> None:
    """An abstained Case is a scored empty answer with score 0.0 (the Engine's mirror rule)."""

    if (
        status != "scored"
        or grade is None
        or grade.score != 0.0
        or output != ""
        or refusal is not None
    ):
        raise ValueError("an abstained Case is a scored empty answer with score 0.0")


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


def named_scores(values: object, label: str) -> Mapping[str, float | None]:
    """Freeze a Benchmark's Named Scores: non-blank names, each value finite or None.

    None means that scorer could not grade this Case (or Candidate); it is not a zero.
    Shared by the Case Grade and the Candidate Result so both validate one way.
    """

    if values is None:
        return MappingProxyType({})
    if not isinstance(values, Mapping):
        raise TypeError(f"{label} scores must be a mapping")
    selected: dict[str, float | None] = {}
    for name, value in values.items():
        normalized_name = _nonempty_text(name, f"{label} score name")
        selected[normalized_name] = _optional_number(value, f"{label} score {normalized_name!r}")
    # WHY a proxy, not freeze_mapping: every value is already a validated scalar, and the
    # proxy keeps the typed `Mapping[str, float | None]` the properties promise.
    return MappingProxyType(selected)


def _optional_case_score(value: object) -> float | None:
    selected = _optional_number(value, "Case Grade score")
    if selected is not None and selected > 1.0:
        raise ValueError("Case Grade score must be at most 1")
    return selected


def _string(value: object, label: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{label} must be text")
    return value


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

    selected_status = _case_status(status, grade)
    if any(failure.case_id != case_id for failure in failures):
        raise ValueError("every Case Result Failure must reference its own case_id")
    if selected_status == "scored":
        _validate_scored_case(refusal, grade, output, failures)
    else:
        _validate_failed_case(refusal, grade, failures)
    return selected_status


def _case_status(
    status: CaseStatus | None,
    grade: CaseGrade | None,
) -> CaseStatus:
    if status is not None:
        if status not in {"scored", "failed"}:
            raise ValueError("Case Result status must be 'scored' or 'failed'")
        return status
    return "scored" if grade is not None and grade.score is not None else "failed"


def _validate_scored_case(
    refusal: str | None,
    grade: CaseGrade | None,
    output: object,
    failures: Sequence[Failure],
) -> None:
    # INVARIANT (OME-1037): a scored Case is either an answer that was graded or a
    # refusal that was graded — exactly one of output/refusal, never both/neither.
    if grade is None or grade.score is None or (output is None) == (refusal is None) or failures:
        raise ValueError(
            "Case Result status 'scored' requires a numeric grade and exactly one of "
            "output and refusal, and cannot carry failures"
        )


def _validate_failed_case(
    refusal: str | None,
    grade: CaseGrade | None,
    failures: Sequence[Failure],
) -> None:
    if not failures or grade is not None and grade.score is not None:
        raise ValueError("Case Result status 'failed' requires failures and no numeric grade")
    # INVARIANT (OME-1037): refusal text on a failed Case is evidence for its
    # provider_refusal failure; every other failed Case stays refusal-free.
    if refusal is not None and all(failure.code != "provider_refusal" for failure in failures):
        raise ValueError(
            "Case Result status 'failed' carries refusal text only with a provider_refusal failure"
        )


__all__ = ["CaseGrade", "CaseResult", "Check", "Evidence", "EvidenceProducer"]
