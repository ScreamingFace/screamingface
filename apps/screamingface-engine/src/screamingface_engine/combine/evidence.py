"""The wire model of what one combine step did (``screamingface.combine-evidence.v1``).

FEATURE: per-operation evidence for a reducer Candidate (OME-1289 E4a, combine-evidence PRD).
STORY: as a reader of a Case result, I see which operators ran, what each member's value was,
how the tally came out, and which member's text won -- without the answer text copies.

INVARIANT: the field order below IS the pinned wire order, every key is always present except
``mean`` (written only for the ``mean`` reducer), and a null is written explicitly. The encoder
keeps no ``sort_keys`` (the envelope never did).
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
    AbstainReason,
    AnswerReason,
    EvidenceKind,
    MemberStatus,
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
    status: MemberStatus
    reason: AnswerReason | None
    signals: dict[str, float | None]
    weight: float | None
    score: float | None

    @model_validator(mode="after")
    def _check(self) -> AnswerRecord:
        if (self.reason is None) != (self.status == "answered"):
            raise ValueError("an answer has a reason exactly when it failed")
        if self.status == "fail" and self.value is not None:
            raise ValueError("a failed answer has no value")
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
        if self.result.status == "abstain" and (self.chosen or self.built):
            raise ValueError("an abstained combine evidence chooses and builds nothing")
        if self.result.member_id is not None and (
            self.built or self.chosen != [self.result.member_id]
        ):
            raise ValueError("a member result must be the one chosen member and not built")
        return self


__all__ = [
    "COMBINE_EVIDENCE_SCHEMA",
    "AnswerRecord",
    "CombineEvidence",
    "FieldReadingRecord",
    "JudgeReadingRecord",
    "ResultRecord",
    "SignalRecord",
    "TallyRowRecord",
]
