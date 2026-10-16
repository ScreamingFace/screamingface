"""The wire model of what one combine step did (``screamingface.combine-evidence.v1``).

FEATURE: per-operation evidence for a reducer Candidate (OME-1289 E4a, combine-evidence PRD).
STORY: as a reader of a Case result, I see which operators ran, what each member's value was,
how the tally came out, and which member's text won -- without the answer text copies.

INVARIANT: the field order below IS the pinned wire order, every key is always present except
``mean`` (written only for the ``mean`` reducer), ``cut`` and the member ``rank`` (written only for
a ``top_k@1`` step), ``declared`` (written only when the spec declares signals), ``gate`` (written
only when the spec has a gate) and ``verifier`` (reserved, never written in E4b part 5), and a null
is written explicitly. The encoder keeps no ``sort_keys`` (the envelope never did).
INVARIANT: this module imports pydantic and ``combine.ports`` and nothing else. ``benchmarks/
contract.py`` imports it (unit 3), so it must never import ``benchmarks.*`` or
``operation_calls``.
WHY no member text: evidence holds extracted values only, never the ``output`` copies; the
envelope already carries every member's full text.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

from screamingface_engine.combine.ports import (
    EXCLUDE_REASONS,
    GATE_OBSERVE,
    AbstainReason,
    AnswerReason,
    EvidenceKind,
    ExcludeReason,
    GateBranch,
    GateCmp,
    GateOtherwise,
    RecordStatus,
    Reducer,
    SignalOrder,
)

COMBINE_EVIDENCE_SCHEMA = "screamingface.combine-evidence.v1"


class _EvidenceModel(BaseModel):
    """Closed producer value: every key is intentional."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True, allow_inf_nan=False)


class AnswerRecord(_EvidenceModel):
    """One spec member, in author order."""

    member_id: str
    raw: str | None
    value: str | None
    # E4b part 2 (ans:Q3): "excluded" = the member answered and a rule of the step left it out.
    # The record keeps its raw, value, signals, weight and score (AR-I3).
    status: RecordStatus
    reason: AnswerReason | ExcludeReason | None
    signals: dict[str, float | None]
    weight: float | None
    score: float | None
    # E4b part 2: the place of the member in a top_k@1 order (1 = first). Optional on the wire,
    # like CombineEvidence.mean: the key is written only when it is set.
    rank: int | None = Field(default=None, exclude_if=lambda value: value is None)

    @model_validator(mode="after")
    def _check(self) -> AnswerRecord:
        if (self.reason is None) != (self.status == "answered"):
            raise ValueError("an answer record has a reason exactly when it did not answer")
        if self.status == "fail" and self.value is not None:
            raise ValueError("a failed answer has no value")
        # AR-I2 / AR-I3: an exclude reason goes with "excluded", and only with it.
        if (self.status == "excluded") != (self.reason in EXCLUDE_REASONS):
            raise ValueError("an excluded answer has an exclude reason, and only it has one")
        # AR-I4, row part. CombineEvidence._check makes the ranks of one evidence 1..n.
        if self.rank is not None and (self.rank < 1 or self.score is None):
            raise ValueError("a rank is a positive integer on a member with a score")
        return self


class ResultRecord(_EvidenceModel):
    """The computed answer of the step: a member's text, a built text, or an abstain."""

    member_id: str | None
    value: str | None
    status: Literal["answered", "abstain"]
    reason: AbstainReason | None

    @model_validator(mode="after")
    def _check(self) -> ResultRecord:
        if (self.reason is None) != (self.status == "answered"):
            raise ValueError("a result has a reason exactly when it abstained")
        if self.status == "abstain" and (self.value is not None or self.member_id is not None):
            raise ValueError("an abstain result has no value and no member")
        return self


class SignalRecord(_EvidenceModel):
    """The one signal the spec reads, and the order a reducer asked for (None: no order)."""

    key: str
    order: SignalOrder | None


class CutRecord(_EvidenceModel):
    """The cut of a ``top_k@1`` step: keep the first ``k`` scored members in ``order``."""

    # The bound of top_k@1 (operators/selection.py _MAX_K). This module cannot import a plugin.
    k: int = Field(ge=1, le=256)
    order: SignalOrder


class GateRecord(_EvidenceModel):
    """What the gate compared and which branch the step took (E4b part 5, ans:Q1).

    ``passed`` and ``branch`` are null when the gate did not run (the vote found no answer); then
    ``observed`` is null too (GR-I1). ``observed`` is also null when the gate ran and had no number.
    E4b part 6 (ans:Q2): ``branch`` "band" = the number was inside the closed ``abstain_band``, so
    the step abstained with ``in_band`` and made no comparison (``passed`` null, P10).
    """

    observe: str
    observed: float | None
    cmp: GateCmp
    threshold: float
    passed: bool | None
    branch: GateBranch | None
    otherwise: GateOtherwise
    # E4b part 6 (P11): the spec band. Optional on the wire, like CombineEvidence.mean: the key is
    # written only when it is set, so every part 5 gate record keeps its bytes.
    abstain_band: list[float] | None = Field(
        default=None, min_length=2, max_length=2, exclude_if=lambda value: value is None
    )

    @model_validator(mode="after")
    def _check(self) -> GateRecord:
        if GATE_OBSERVE.fullmatch(self.observe) is None:
            raise ValueError("a gate record observes agreement, chosen:<name> or mean:<name>")
        _check_band_record(self)
        if self.branch == "band":
            return self  # GR-I1': the band branch has no comparison result (P10)
        # GR-I1
        if (self.passed is None) != (self.branch is None):
            raise ValueError("a gate record has a branch exactly when it has a comparison result")
        if self.passed is None and self.observed is not None:
            raise ValueError("a gate that did not run observed no number")
        # GR-I2
        if self.passed is not None and self.passed != (self.branch == "majority"):
            raise ValueError("a gate that passed keeps the majority, and only it does")
        return self


def _check_band_record(record: GateRecord) -> None:
    """GB-I1, GB-I2 and GB-I3 (E4b part 6, erd §4): a reader can replay the band decision.

    WHY a helper: the gate record checks are at the lint complexity limit (part 5 erratum E3).
    """
    band = record.abstain_band
    observed = record.observed
    # GB-I1
    if band is not None and band[0] > band[1]:
        raise ValueError("a gate band is two numbers lo <= hi")
    inside = band is not None and observed is not None and band[0] <= observed <= band[1]
    if record.branch == "band":
        # GR-I1' and GB-I2: inside the band no comparison is made.
        if record.passed is not None:
            raise ValueError("a gate in its band made no comparison")
        if not inside:
            raise ValueError("a gate band branch observed a number inside its band")
    elif record.branch is not None and inside:
        # GB-I3: a gate that compared had its number outside the band.
        raise ValueError("a gate that compared observed a number outside its band")


class TallyRowRecord(_EvidenceModel):
    """One distinct value, its score and its holders in author order."""

    value: str
    score: float
    holders: list[str]


class JudgeReadingRecord(_EvidenceModel):
    """What the strict judge parse found: a label (``member_2``) or per-member scores."""

    raw: str
    returns: Literal["label", "scores"]
    parsed: str | dict[str, float]


class FieldReadingRecord(_EvidenceModel):
    """One field-level rule applied by a pick or merge reducer."""

    field: str
    rule: str
    values: dict[str, JsonValue]
    result: JsonValue


_GATE_REASON = "gate_not_met goes with a gate that took the abstain fallback, and only with it"


def _gate_reason_holds(gate: GateRecord | None, result: ResultRecord) -> bool:
    """GR-I3: reason "gate_not_met" <=> gate.branch == "fallback" and otherwise abstain."""
    abstained = gate is not None and gate.branch == "fallback" and gate.otherwise == "abstain"
    return (result.reason == "gate_not_met") == abstained


_BAND_REASON = "in_band goes with a gate that abstained inside its band, and only with it"


def _band_reason_holds(gate: GateRecord | None, result: ResultRecord) -> bool:
    """GB-I4: reason "in_band" <=> gate.branch == "band" (E4b part 6, P12)."""
    return (result.reason == "in_band") == (gate is not None and gate.branch == "band")


def _check_gate_reasons(gate: GateRecord | None, result: ResultRecord) -> None:
    """GB-I4, then GR-I3: each gate abstain word goes with its branch, and only with it.

    WHY GB-I4 first: a band gate with the reason gate_not_met breaks both rules; the in_band
    message names the band (AB-E3). WHY a helper: ``_check_gate`` is at the lint branch limit
    (part 5 erratum E3).
    """
    if not _band_reason_holds(gate, result):
        raise ValueError(_BAND_REASON)
    if not _gate_reason_holds(gate, result):
        raise ValueError(_GATE_REASON)


class CombineEvidence(_EvidenceModel):
    """Everything one combine step decided, minus the answer text."""

    schema_id: Literal["screamingface.combine-evidence.v1"] = Field(
        default=COMBINE_EVIDENCE_SCHEMA, alias="schema"
    )
    kind: EvidenceKind
    reducer: Reducer
    operators: list[str]
    members: list[AnswerRecord]
    tally: list[TallyRowRecord] | None
    judge: JudgeReadingRecord | None
    fields: list[FieldReadingRecord] | None
    chosen: list[str]
    built: bool
    agreement: float | None
    tie: bool
    median: str | None
    # E4b P8: the mean of the `mean` reducer, as canonical decimal text. Optional on the wire: the
    # key is written only when it is set, so every other evidence keeps its v1 bytes.
    mean: str | None = Field(default=None, exclude_if=lambda value: value is None)
    presentation_order: Literal["author"] | None
    separator_collision: bool | None
    signal: SignalRecord | None
    # E4b part 2: the k and the order of a top_k@1 step. Optional on the wire, like ``mean``.
    cut: CutRecord | None = Field(default=None, exclude_if=lambda value: value is None)
    # E4b part 3 (P11): the spec's `signals` map as the spec wrote it. Optional on the wire: the key
    # is written only when the spec declares a source, so every other evidence keeps its v1 bytes.
    declared: dict[str, dict[str, JsonValue]] | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    # E4b part 5 (P9): what the gate compared and the branch the step took. Optional on the wire:
    # the key is written only when the spec has a gate, so every other evidence keeps its v1 bytes.
    gate: GateRecord | None = Field(default=None, exclude_if=lambda value: value is None)
    # E4b part 5 (P15, ans:Q4): reserved for a later verifier. Typed null and never written now.
    verifier: None = Field(default=None, exclude_if=lambda value: value is None)
    result: ResultRecord
    dropped: int
    finish_reason: Literal["stop"]

    @model_validator(mode="after")
    def _check(self) -> CombineEvidence:
        member_ids = [row.member_id for row in self.members]
        if len(set(member_ids)) != len(member_ids):
            raise ValueError("combine evidence member ids must be unique")
        if len(set(self.chosen)) != len(self.chosen) or not set(self.chosen) <= set(member_ids):
            raise ValueError("combine evidence chosen must be unique members")
        if self.dropped != sum(row.status == "fail" for row in self.members):
            raise ValueError("combine evidence dropped must count the failed members")
        # AR-I4: when one member has a rank, the ranks are 1..n over the members with a score.
        ranks = sorted(row.rank for row in self.members if row.rank is not None)
        scored = sum(row.score is not None for row in self.members)
        if ranks and ranks != list(range(1, scored + 1)):
            raise ValueError("combine evidence ranks must be 1..n over the members with a score")
        # CE-I3 (E4b part 2): a member that a rule left out is never chosen, so never the result.
        excluded = {row.member_id for row in self.members if row.status == "excluded"}
        if not excluded.isdisjoint(self.chosen):
            raise ValueError("combine evidence never chooses an excluded member")
        if self.result.status == "abstain" and (self.chosen or self.built):
            raise ValueError("an abstained combine evidence chooses and builds nothing")
        if self.result.member_id is not None and (
            self.built or self.chosen != [self.result.member_id]
        ):
            raise ValueError("a member result must be the one chosen member and not built")
        _check_gate(self)
        return self


def _check_gate(evidence: CombineEvidence) -> None:
    """GB-I4, GR-I3, GR-I1 (evidence part), GR-I4' and GR-I5 (E4b parts 5 and 6, erd §4)."""
    # WHY first: an in_band or gate_not_met result with no gate fails on its word first.
    _check_gate_reasons(evidence.gate, evidence.result)
    gate = evidence.gate
    if gate is None:
        return
    if gate.passed is None and evidence.result.status != "abstain":
        raise ValueError("a gate that did not run goes with an abstained result")
    if (
        gate.observe == "agreement"
        and gate.branch is not None
        and gate.observed != evidence.agreement
    ):
        raise ValueError("an agreement gate observes the evidence agreement")
    if gate.branch != "fallback":
        return
    if gate.otherwise == "writer" and not (
        evidence.built and not evidence.chosen and evidence.result.member_id is None
    ):
        raise ValueError("a writer fallback builds the answer and chooses no member")
    if gate.otherwise == "judge" and (
        evidence.judge is None
        or evidence.judge.returns != "label"
        or evidence.result.member_id is None
        or evidence.chosen != [evidence.result.member_id]
    ):
        raise ValueError("a judge fallback records its label reading and chooses that one member")


__all__ = [
    "COMBINE_EVIDENCE_SCHEMA",
    "AnswerRecord",
    "CombineEvidence",
    "CutRecord",
    "FieldReadingRecord",
    "GateRecord",
    "JudgeReadingRecord",
    "ResultRecord",
    "SignalRecord",
    "TallyRowRecord",
]
