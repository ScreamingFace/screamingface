"""The wire model of what one combine step did (``screamingface.combine-evidence.v1``).

FEATURE: per-operation evidence for a reducer Candidate (OME-1289 E4a, combine-evidence PRD).
STORY: as a reader of a Case result, I see which operators ran, what each member's value was,
how the tally came out, and which member's text won -- without the answer text copies.

INVARIANT: the field order below IS the pinned wire order, every key is always present, and a
null is written explicitly. The encoder keeps no ``sort_keys`` (the envelope never did).
INVARIANT: this module imports pydantic and ``combine.ports`` and nothing else. ``benchmarks/
contract.py`` imports it (unit 3), so it must never import ``benchmarks.*`` or
``operation_calls``.
WHY no member text: evidence holds extracted values only, never the ``output`` copies; the
envelope already carries every member's full text.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

from screamingface_engine.combine.ports import EvidenceKind, ReadingStatus, Reducer

COMBINE_EVIDENCE_SCHEMA = "screamingface.combine-evidence.v1"


class _EvidenceModel(BaseModel):
    """Closed producer value: every key is intentional."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True, allow_inf_nan=False)


class MemberReadingRecord(_EvidenceModel):
    """One spec member, in author order."""

    member: str
    raw: str | None
    value: str | None
    status: ReadingStatus
    weight: float | None
    score: float | None


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
    members: list[MemberReadingRecord]
    tally: list[TallyRowRecord] | None
    judge: JudgeReadingRecord | None
    fields: list[FieldReadingRecord] | None
    chosen: list[str]
    built: bool
    agreement: float | None
    tie: bool
    median: str | None
    presentation_order: Literal["author"] | None
    separator_collision: bool | None
    finish_reason: Literal["stop"]

    @model_validator(mode="after")
    def _check(self) -> CombineEvidence:
        member_ids = [row.member for row in self.members]
        if len(set(member_ids)) != len(member_ids):
            raise ValueError("combine evidence member ids must be unique")
        if len(set(self.chosen)) != len(self.chosen) or not set(self.chosen) <= set(member_ids):
            raise ValueError("combine evidence chosen must be unique members")
        return self


__all__ = [
    "COMBINE_EVIDENCE_SCHEMA",
    "CombineEvidence",
    "FieldReadingRecord",
    "JudgeReadingRecord",
    "MemberReadingRecord",
    "TallyRowRecord",
]
