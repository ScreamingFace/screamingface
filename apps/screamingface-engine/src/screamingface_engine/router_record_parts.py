"""The parts of a completed Router record: its calls, quorum and synthesis (contract C5, Unit 5.2).

FEATURE: Router Recipe extension. JOIN's `screamingface.router-decision.v1` names the classifier
call, every branch call that ran, the subset quorum and the synthesis. `router_decision` reads the
whole record and checks how these parts fit its outcome; each part here checks its own shape.

WHY a shared leaf beside `router_decision`: the same reason as the codec (see its WHY), and so the
codec keeps one responsibility, the decision, instead of growing past its size bound.
INVARIANT: closed records. A repeated or unknown key, a wrong type or an impossible combination is
refused, never coerced; a refusal names a field and a rule, never a value.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field, model_validator

from screamingface_engine.combine.ports import AbstainReason
from screamingface_engine.router_vocabulary import (
    CallBinding,
    Code,
    Count,
    Index,
    Label,
    ModelId,
    StrictModel,
)

Phase = Literal["input", "admit", "classify", "decide", "generate", "default", "synthesize"]
SynthesisStatus = Literal["answered", "abstained", "failed"]
EngineAttempts = Annotated[int, Field(ge=1)]
"""C8: every Engine request of one logical call; a call with no attempt has no `Attempts`."""


def _check_billed(upstream: int | None, billed: bool) -> None:
    """C8: a known upstream count decides `possibly_billed`; only unknown leaves it open."""
    if upstream is not None and billed != (upstream > 0):
        raise ValueError("a known upstream count decides possibly_billed")


def _check_outcome(status: SynthesisStatus, reason: object, code: object) -> None:
    """C5: an answer has neither, an abstention its reason, a failure its code."""
    if (reason is not None) != (status == "abstained") or (code is not None) != (
        status == "failed"
    ):
        raise ValueError("reason is present exactly when abstained and code when failed")


class ClassifierCall(StrictModel):
    binding: CallBinding
    cost: Annotated[float, Field(ge=0)] | None
    engine_attempts: EngineAttempts
    upstream_attempts: Count | None
    possibly_billed: bool

    @model_validator(mode="after")
    def _billed(self) -> ClassifierCall:
        _check_billed(self.upstream_attempts, self.possibly_billed)
        return self


class Branch(StrictModel):
    role: Literal["candidate", "default"]
    index: Index | None
    label: Label | None
    model: ModelId
    status: Literal["answered", "failed"]
    code: Code | None
    engine_attempts: EngineAttempts
    upstream_attempts: Count | None
    possibly_billed: bool

    @model_validator(mode="after")
    def _shape(self) -> Branch:
        if (self.role == "default") != (self.index is None) or (self.index is None) != (
            self.label is None
        ):
            raise ValueError("a candidate names its index and label, the default neither")
        # INVARIANT (C5): a failed branch names its bounded code; an answer has none.
        if (self.code is None) != (self.status == "answered"):
            raise ValueError("a branch has a code exactly when it failed")
        _check_billed(self.upstream_attempts, self.possibly_billed)
        return self


class Quorum(StrictModel):
    # WHY >= 1: C2 `quorum` is "all" or 1..len(candidates), and the floor is min(q, selected).
    floor: Annotated[int, Field(ge=1)]
    selected: Annotated[int, Field(ge=1)]
    answered: Count

    @model_validator(mode="after")
    def _bounded(self) -> Quorum:
        if self.floor > self.selected or self.answered > self.selected:
            raise ValueError("floor and answered are at most the selected count")
        return self


class ModelSynthesis(StrictModel):
    kind: Literal["model"]
    status: SynthesisStatus
    reason: AbstainReason | None
    code: Code | None
    engine_attempts: EngineAttempts
    upstream_attempts: Count | None
    possibly_billed: bool

    @model_validator(mode="after")
    def _shape(self) -> ModelSynthesis:
        _check_outcome(self.status, self.reason, self.code)
        _check_billed(self.upstream_attempts, self.possibly_billed)
        return self


class VoteSynthesis(StrictModel):
    kind: Literal["vote"]
    status: SynthesisStatus
    reason: AbstainReason | None
    code: Code | None

    @model_validator(mode="after")
    def _shape(self) -> VoteSynthesis:
        _check_outcome(self.status, self.reason, self.code)
        return self


Synthesis = Annotated[ModelSynthesis | VoteSynthesis, Field(discriminator="kind")]


class Selected(StrictModel):
    index: Index
    label: Label
    model: ModelId


class RecordFailure(StrictModel):
    phase: Phase
    code: Code


def runs_as(branch: Branch, entry: Selected) -> bool:
    """Whether ``branch`` is the call of the selected candidate ``entry`` (index, label, Model)."""
    return (branch.index, branch.label, branch.model) == (entry.index, entry.label, entry.model)


__all__ = [
    "Branch",
    "ClassifierCall",
    "EngineAttempts",
    "ModelSynthesis",
    "Phase",
    "Quorum",
    "RecordFailure",
    "Selected",
    "Synthesis",
    "SynthesisStatus",
    "VoteSynthesis",
    "runs_as",
]
