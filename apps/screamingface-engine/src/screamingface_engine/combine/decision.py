"""The wire model of what one sf.Gate decided on one Case (``screamingface.gate-decision.v1``).

FEATURE: E4c (OME-1291) — a branch that is not selected makes zero model calls, and the report
says it was not selected and why. DECIDE writes this record, JOIN completes it, and the Engine
attaches it to the Gate's JOIN operation ``op_gate_<n>`` (erd §3).
STORY: as a reader of a Case result, I see the condition a Gate compared, the value it read, the
branch that ran, the branches that made zero calls and why, and how the taken branch ended.

INVARIANT: the field order below IS the wire order; every key is always present and a null is
written explicitly (the combine-evidence rule).
INVARIANT: this module imports pydantic and ``combine.ports`` and nothing else, because
``benchmarks/contract.py`` and ``operation_calls.py`` import it (the ``combine.evidence`` rule).
WHY no text: the record holds labels, numbers and ids, never prompt, input or answer text
(GD-I5). The one exception is a selector record's ``raw``: the first token of an unrecognized
reply, cut at 64 characters.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from screamingface_engine.combine.ports import MAX_SELECTOR_RAW_CHARS, AbstainReason, SelectorParse

GATE_DECISION_SCHEMA = "screamingface.gate-decision.v1"

GateKind = Literal["input", "panel"]
BranchName = Literal["then", "otherwise"]
ConditionCmp = Literal[">=", ">", "<=", "<", "eq", "ne", "has", "empty"]
NotRunReason = Literal["not_selected", "budget_refused"]
SelectorKind = Literal["keywords", "label_model"]
SelectorStatus = Literal["computed", "not_run", "failed"]
GateResultStatus = Literal["answered", "abstain", "fail_closed"]
PanelBranch = Literal["majority", "fallback", "band"]
BudgetUnit = Literal["usd", "tokens"]

GATE_ID = re.compile(r"gate_[1-9]\d*")
SELECTOR_ID = re.compile(r"sel_[1-9]\d*")
LABEL = re.compile(r"[a-z][a-z0-9_]{0,31}")
# A condition observes a selector label or label set, the remaining budget, or a panel number.
CONDITION_OBSERVE = re.compile(
    r"label:sel_[1-9]\d*|labels:sel_[1-9]\d*|budget\.remaining:(?:usd|tokens)"
    r"|agreement|answered|(?:chosen|mean):[A-Za-z_][A-Za-z0-9_.]*"
)
_PANEL_OBSERVE = re.compile(r"agreement|answered|(?:chosen|mean):.+")
_SHA256_PREFIX = re.compile(r"[0-9a-f]{16}")


class _DecisionModel(BaseModel):
    """Closed producer value: every key is intentional."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True, allow_inf_nan=False)


class GateCondition(_DecisionModel):
    """The one comparison a Gate makes (GATE_SPEC ``when``, GS-I1)."""

    observe: str
    cmp: ConditionCmp
    value: float | str | bool | None

    @model_validator(mode="after")
    def _check(self) -> GateCondition:
        if CONDITION_OBSERVE.fullmatch(self.observe) is None:
            raise ValueError("a gate condition observes a label, a label set, a budget or a panel")
        _check_pairing(self.observe, self.cmp, self.value)
        return self


def _is_label(value: object) -> bool:
    return isinstance(value, str) and LABEL.fullmatch(value) is not None


def _is_number(value: object) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool)


# The observe/cmp/value pairing of erd §1, by the observe form before its first ":".
_PAIRINGS: dict[str, Callable[[str, object], bool]] = {
    "label": lambda cmp, value: cmp in ("eq", "ne") and _is_label(value),
    "labels": lambda cmp, value: (
        (cmp == "has" and _is_label(value)) or (cmp == "empty" and value is None)
    ),
    "answered": lambda cmp, value: cmp == "eq" and value is True,
}


def _numeric_pairing(cmp: str, value: object) -> bool:
    return cmp in (">=", ">", "<=", "<") and _is_number(value)


def _check_pairing(observe: str, cmp: str, value: object) -> None:
    if not _PAIRINGS.get(observe.split(":", 1)[0], _numeric_pairing)(cmp, value):
        raise ValueError(
            "a gate condition pairs eq/ne with a label, has/empty with a label set, eq true with "
            "answered, and >=, >, <= or < with a number"
        )


class SelectorRecord(_DecisionModel):
    """What one selector gave on this Case (erd §2, SELECTOR_RECORD)."""

    id: str
    kind: SelectorKind
    status: SelectorStatus
    labels: list[str] | None
    parse: SelectorParse | None
    raw: str | None = Field(max_length=MAX_SELECTOR_RAW_CHARS)
    parse_error: str | None
    input_chars: int = Field(ge=0)
    input_sha256: str

    @model_validator(mode="after")
    def _check(self) -> SelectorRecord:
        if SELECTOR_ID.fullmatch(self.id) is None:
            raise ValueError("a selector id is sel_<n>")
        if _SHA256_PREFIX.fullmatch(self.input_sha256) is None:
            raise ValueError("a selector input hash is 16 lowercase hex digits")
        # SR-I1
        if self.status != "computed":
            if self.labels is not None or self.parse is not None or self.raw is not None:
                raise ValueError("a selector that did not compute has no labels, parse or raw")
        elif self.labels is None or self.parse is None:
            raise ValueError("a computed selector has labels and a parse state")
        if self.parse_error is not None and self.status != "failed":
            raise ValueError("only a failed selector has a parse error")
        # SR-I3 (shape half): every label is a well-formed label, once.
        labels = self.labels or []
        if any(LABEL.fullmatch(label) is None for label in labels) or len(set(labels)) != len(
            labels
        ):
            raise ValueError("selector labels are distinct declared labels")
        return self


class ModelCalls(_DecisionModel):
    """The model-call leaves on the shortest and the longest path through a body (ans:Q22)."""

    min: int = Field(ge=0)
    max: int = Field(ge=0)

    @model_validator(mode="after")
    def _check(self) -> ModelCalls:
        # GD-I7
        if self.min > self.max:
            raise ValueError("model_calls min is at most max")
        return self


class NotRunEntry(_DecisionModel):
    """One branch that made zero calls on this Case, and why."""

    branch: BranchName
    reason: NotRunReason
    model_calls: ModelCalls


class BudgetView(_DecisionModel):
    """The spend a decision saw for one declared unit (erd §5, BUDGET_VIEW)."""

    unit: BudgetUnit
    cap: int | float = Field(gt=0)
    spent: int | float = Field(ge=0)
    unpriced: int = Field(ge=0)
    estimate: int | float | None = Field(ge=0)
    refused: bool


class GateResult(_DecisionModel):
    """How the taken branch ended, copied by JOIN (branch-core D12)."""

    status: GateResultStatus
    reason: AbstainReason | None

    @model_validator(mode="after")
    def _check(self) -> GateResult:
        if (self.status == "abstain") != (self.reason is not None):
            raise ValueError("a gate result has an abstain reason exactly when it abstained")
        return self


class PanelLink(_DecisionModel):
    """A panel gate's decision call and the E4b gate record branch it read."""

    operation_id: str = Field(min_length=1)
    branch: PanelBranch | None


class GateDecision(_DecisionModel):
    """One Gate on one Case: the comparison, the branch that ran and the branches that did not."""

    schema_id: Literal["screamingface.gate-decision.v1"] = Field(
        default=GATE_DECISION_SCHEMA, alias="schema"
    )
    gate_id: str
    kind: GateKind
    when: GateCondition
    observed: bool | float | str | list[str] | None
    passed: bool | None
    wanted: BranchName | None
    branch: BranchName | None
    selectors: list[SelectorRecord]
    not_run: list[NotRunEntry]
    budget: list[BudgetView] | None
    result: GateResult | None
    panel: PanelLink | None

    @model_validator(mode="after")
    def _check(self) -> GateDecision:
        if GATE_ID.fullmatch(self.gate_id) is None:
            raise ValueError("a gate id is gate_<n>")
        # GS-I2 / GD-I4
        if (self.kind == "panel") != (_PANEL_OBSERVE.fullmatch(self.when.observe) is not None):
            raise ValueError("a panel gate observes a panel number, an input gate an input value")
        if (self.panel is not None) != (self.kind == "panel"):
            raise ValueError("a gate links its decision call exactly when it is a panel gate")
        _check_branches(self)
        if self.budget is not None and len({view.unit for view in self.budget}) != len(self.budget):
            raise ValueError("a budget view lists each unit once")
        return self


def _check_branches(record: GateDecision) -> None:
    """GD-I1 and GD-I2: the not-run list agrees with the branch that ran."""

    named = [entry.branch for entry in record.not_run]
    if len(set(named)) != len(named):
        raise ValueError("a gate lists each branch that did not run once")
    # GD-I1
    expected = {"then", "otherwise"} - ({record.branch} if record.branch is not None else set())
    if set(named) != expected:
        raise ValueError("a gate lists exactly the branches that did not run")
    refused = {entry.branch for entry in record.not_run if entry.reason == "budget_refused"}
    if record.wanted is None:
        # GD-I2: no wanted branch means no branch and no refusal. D4's null row with the word
        # fail_closed (cascade CA-30) fails the Case, so that result is allowed too.
        if record.branch is not None or refused:
            raise ValueError("a gate that wanted no branch ran none and refused none")
        if record.result is not None and record.result.status == "answered":
            raise ValueError("a gate that wanted no branch abstained or failed closed")
        return
    if record.branch != record.wanted and refused != {record.wanted}:
        raise ValueError("a gate runs another branch than the one it wanted only on a refusal")
    if record.branch == record.wanted and refused:
        raise ValueError("a gate that ran the branch it wanted refused nothing")


__all__ = [
    "GATE_DECISION_SCHEMA",
    "BudgetView",
    "GateCondition",
    "GateDecision",
    "GateResult",
    "ModelCalls",
    "NotRunEntry",
    "PanelLink",
    "SelectorRecord",
]
