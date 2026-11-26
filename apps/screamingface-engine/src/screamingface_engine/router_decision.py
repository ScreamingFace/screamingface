"""The Router decision codec: DECIDE's draft and JOIN's completed record (contracts C5, Unit 5.2).

FEATURE: Router Recipe extension. DECIDE returns the internal draft
``screamingface.router-decision-draft.v1``; JOIN publishes the completed
``screamingface.router-decision.v1``. Only the completed record exists outside the Engine.

WHY a shared leaf and not `world/`: JOIN publishes the completed record on its operation call
(C15), and `operation_calls` is a shared leaf that may not import the world. E4c keeps its Gate
record in `combine/decision.py` beside its `world/branch.py` runtime for the same reason. The
field rules, policy and evidence both contracts read live in `router_vocabulary`; the record's
call, quorum and synthesis parts in `router_record_parts`.

INVARIANT: both readers are closed. A repeated or unknown key, a wrong type, a non-finite value
or an inconsistent combination is refused, never coerced. The draft and the record differ in
`schema`, so no reader of the completed record accepts a draft.
INVARIANT: a record holds labels, numbers, IDs and bounded codes only; a refusal names a field
and a rule, never a value.
"""

from __future__ import annotations

from typing import Any, Literal, get_args

from pydantic import BaseModel, Field, ValidationError, model_validator

from screamingface_engine.router_record_parts import (
    Branch,
    ClassifierCall,
    ModelSynthesis,
    Phase,
    Quorum,
    RecordFailure,
    Selected,
    Synthesis,
    VoteSynthesis,
    runs_as,
)
from screamingface_engine.router_vocabulary import (
    Code,
    Evidence,
    Index,
    Reason,
    Revision,
    RouterBinding,
    RouterPolicy,
    ScoringRecord,
    SelectorRecord,
    StrictModel,
    UnknownLabel,
    best_reason,
    exact_reason,
    field_rule,
    strict_json,
)

DRAFT_SCHEMA = "screamingface.router-decision-draft.v1"
DECISION_SCHEMA = "screamingface.router-decision.v1"
REVISION_SCHEME = "router-definition-v1"

Outcome = Literal["selected", "default", "no_selection", "failed"]
DraftPhase = Literal["input", "admit", "classify", "decide"]

_SELECTED_REASONS = frozenset({"unique_max", "exact"})
_UNDEFINED_PHASES = frozenset({"input", "admit"})
_DECISION_PHASES = frozenset(get_args(DraftPhase))
"""C5 `outcome="failed"`: the phases with no policy result; a later failure keeps its decision."""


class RouterDecisionError(ValueError):
    """A draft or record that is not exactly one consistent C5 document."""


# --- the decision both documents carry ------------------------------------------------------------


class _Decision(StrictModel):
    router: RouterBinding
    revision: Revision | None
    revision_scheme: Literal["router-definition-v1"] | None
    policy: RouterPolicy | None
    evidence: Evidence | None
    outcome: Outcome
    reason: Reason | None
    unknown_labels: tuple[UnknownLabel, ...]

    def _indices(self) -> tuple[int, ...]:
        raise NotImplementedError

    def _check_decision(self, phase: str | None) -> None:
        """C5: the definition, evidence, outcome, reason and selection agree."""
        if self.outcome == "failed":
            self._check_failed(phase)
            return
        if phase is not None and phase in _DECISION_PHASES:
            raise ValueError("only a failed outcome fails before a branch")
        policy, evidence = self.policy, self.evidence
        if policy is None or evidence is None or None in (self.revision, self.revision_scheme):
            raise ValueError("a decision carries its definition and evidence")
        self._check_reason(policy, evidence)

    def _check_failed(self, phase: str | None) -> None:
        if phase is None:
            raise ValueError("a failed outcome names its phase")
        if phase not in _DECISION_PHASES:
            # INVARIANT (C5): a failure at generate, default or synthesize keeps the decision it
            # was executing; it is never a failed outcome.
            raise ValueError("a failed outcome fails before any branch")
        if (self.evidence, self.reason, self._indices(), self.unknown_labels) != (
            None,
            None,
            (),
            (),
        ):
            raise ValueError("a failure keeps no evidence, reason or labels")
        nulls = [value is None for value in (self.revision, self.revision_scheme, self.policy)]
        if (all(nulls) if phase in _UNDEFINED_PHASES else any(nulls)) is (
            phase not in _UNDEFINED_PHASES
        ):
            raise ValueError("definition fields are null exactly at input and admit")

    def _check_reason(self, policy: RouterPolicy, evidence: ScoringRecord | SelectorRecord) -> None:
        if (policy.match == "best") != isinstance(evidence, ScoringRecord):
            raise ValueError("best reads scores and exact a selector")
        # INVARIANT (C6): the reason is the one C6 gives this evidence, never a choice;
        # `routing_policy` decides from the same table.
        expected = (
            best_reason([(row.label, row.score) for row in evidence.scores], self.unknown_labels)
            if isinstance(evidence, ScoringRecord)
            else exact_reason(policy.select, evidence.parse, len(evidence.labels))
        )
        if self.reason != expected or (expected in _SELECTED_REASONS) != (
            self.outcome == "selected"
        ):
            raise ValueError("reason is the one C6 gives the evidence, and fits the outcome")
        self._check_selection(policy, evidence, self._indices())

    def _check_selection(
        self,
        policy: RouterPolicy,
        evidence: ScoringRecord | SelectorRecord,
        selected: tuple[int, ...],
    ) -> None:
        if bool(selected) != (self.outcome == "selected") or len(set(selected)) != len(selected):
            raise ValueError("selected names distinct candidates exactly when one was selected")
        if policy.select == "one" and self.outcome == "selected" and len(selected) != 1:
            raise ValueError("select one selects one")
        if isinstance(evidence, SelectorRecord):
            if self.outcome == "selected" and len(selected) != len(evidence.labels):
                raise ValueError("a selector selects every recognized label")
            if self.unknown_labels != evidence.unknown:
                raise ValueError("unknown_labels are the selector's unknown tokens")
        elif not _subsequence(self.unknown_labels, [row.label for row in evidence.scores]):
            raise ValueError("unknown_labels are returned labels in returned order")


def _subsequence(items: tuple[str, ...], within: list[str]) -> bool:
    remaining = iter(within)
    return all(item in remaining for item in items)


def _leader(evidence: ScoringRecord) -> str:
    return max(evidence.scores, key=lambda row: row.score).label


# --- the draft ------------------------------------------------------------------------------------


class DraftFailure(StrictModel):
    phase: DraftPhase
    code: Code
    permanent: bool


class RouterDraft(_Decision):
    """DECIDE's internal draft; JOIN reads it, nothing outside the Engine does."""

    schema_id: Literal["screamingface.router-decision-draft.v1"] = Field(alias="schema")
    selected: tuple[Index, ...]
    failure: DraftFailure | None = None

    @model_validator(mode="after")
    def _check(self) -> RouterDraft:
        if (self.failure is None) == (self.outcome == "failed"):
            raise ValueError("failure is present exactly when the outcome failed")
        self._check_decision(None if self.failure is None else self.failure.phase)
        return self

    def _indices(self) -> tuple[int, ...]:
        return self.selected

    def document(self) -> dict[str, Any]:
        keys = _DRAFT_KEYS if self.failure is not None else _DRAFT_KEYS[:-1]
        return _document(self, keys)


# --- the completed record -------------------------------------------------------------------------


class RouterDecision(_Decision):
    """The completed record JOIN publishes (C5)."""

    schema_id: Literal["screamingface.router-decision.v1"] = Field(alias="schema")
    selected: tuple[Selected, ...]
    classifier_call: ClassifierCall | None
    branches: tuple[Branch, ...]
    quorum: Quorum | None
    synthesis: Synthesis | None
    status: Literal["answered", "abstained", "failed"]
    failure: RecordFailure | None

    @model_validator(mode="after")
    def _check(self) -> RouterDecision:
        if (self.failure is None) == (self.status == "failed"):
            raise ValueError("failure is present exactly when the status failed")
        phase = None if self.failure is None else self.failure.phase
        self._check_decision(phase if self.outcome == "failed" else None)
        self._check_status(phase)
        self._check_classifier_call()
        self._check_selected_labels()
        self._check_branches()
        return self

    def _subset(self) -> bool:
        return self.policy is not None and self.policy.select == "all"

    def _check_status(self, phase: str | None) -> None:
        subset = self._subset()
        expected = {
            "generate": self.outcome == "selected" and not subset,
            "default": self.outcome == "default",
            "synthesize": self.outcome == "selected" and subset,
        }
        if self.outcome == "failed" and self.status != "failed":
            raise ValueError("a failed outcome fails the record")
        if self.status == "failed" and self.outcome != "failed" and not expected.get(phase or ""):
            raise ValueError("the failing phase is the step the decision was executing")
        if self.status == "answered" and self.outcome not in ("selected", "default"):
            raise ValueError("an answer comes from a selection or the default")
        if self.status == "abstained" and not (
            self.outcome == "no_selection" or (subset and self.outcome == "selected")
        ):
            raise ValueError("an abstention is no_selection or an abstained synthesis")
        if self.outcome == "no_selection" and self.status != "abstained":
            raise ValueError("no_selection abstains")
        if (self.quorum is not None or self.synthesis is not None) != (
            subset and self.outcome == "selected" and self.quorum is not None
        ):
            raise ValueError("quorum and synthesis belong to a selected subset")

    def _check_classifier_call(self) -> None:
        """C5/C8: scores and an llm selector exist only because their call ran, and a call is
        always the occurrence's own classifier call, with or without evidence."""
        call, evidence = self.classifier_call, self.evidence
        if isinstance(evidence, SelectorRecord) and evidence.source == "regex":
            if call is not None:
                raise ValueError("a regex classifier makes no call")
            return
        if self.outcome == "failed" and self.failure is not None:
            if self.failure.phase in _UNDEFINED_PHASES and (call or self.branches):
                raise ValueError("nothing ran before ADMIT accepted")
        if call is None:
            # WHY null is legal without evidence (C4, C5): the classifier may not have run, as
            # for `not_run` beside an accepted ADMIT, a `decide` failure.
            if evidence is not None:
                raise ValueError("classifier_call is the evidence's call under its binding")
            return
        # WHY these bindings: a scoring classify call is keyed by `router` itself, an llm
        # selector by its `selector_N` (C2 `Calls`, C8); without evidence, the policy says which
        # classifier ran (C6: `best` reads scores, `exact` a selector).
        scoring = (
            isinstance(evidence, ScoringRecord)
            if evidence is not None
            else self.policy is not None and self.policy.match == "best"
        )
        if call.binding != self.router if scoring else not call.binding.startswith("selector_"):
            raise ValueError("classifier_call is the classifier's call under its binding")

    def _check_selected_labels(self) -> None:
        evidence, labels = self.evidence, [entry.label for entry in self.selected]
        if self.outcome != "selected" or evidence is None:
            return
        expected = (
            [_leader(evidence)] if isinstance(evidence, ScoringRecord) else list(evidence.labels)
        )
        if labels != expected:
            raise ValueError("selected names the labels the evidence selected, in its order")

    def _check_branches(self) -> None:
        """C5: the branches are the calls the outcome ran, and the status theirs."""
        role = {"selected": "candidate", "default": "default"}.get(self.outcome)
        if any(branch.role != role for branch in self.branches):
            raise ValueError("only a selection runs a candidate and only a default the default")
        if self._subset() and self.outcome == "selected":
            self._check_members()
            self._check_synthesis()
            return
        branch = self.branches[0] if len(self.branches) == 1 else None
        if len(self.branches) > 1 or (
            branch is not None
            and self.outcome == "selected"
            and not runs_as(branch, self.selected[0])
        ):
            raise ValueError("one branch runs, and it is the selected candidate's")
        if self.status == "answered" and (branch is None or branch.status != "answered"):
            raise ValueError("an answer comes from its answered branch")
        if self.status == "failed" and branch is not None:
            if (
                branch.status != "failed"
                or self.failure is None
                or branch.code != self.failure.code
            ):
                raise ValueError("a failed branch carries the record's failure code")

    def _check_members(self) -> None:
        entries = {entry.index: entry for entry in self.selected}
        indices = [branch.index for branch in self.branches]
        if len(set(indices)) != len(indices) or not all(
            branch.index in entries and runs_as(branch, entries[branch.index])
            for branch in self.branches
            if branch.index is not None
        ):
            raise ValueError("each branch is a distinct selected member")
        quorum = self.quorum
        answered = sum(branch.status == "answered" for branch in self.branches)
        if quorum is None or (quorum.selected, quorum.answered) != (len(self.selected), answered):
            raise ValueError("quorum counts the selected members and their answers")

    def _check_synthesis(self) -> None:
        quorum, synthesis, failure = self.quorum, self.synthesis, self.failure
        if synthesis is None:
            if self.status != "failed":
                raise ValueError("a subset with no synthesis failed")
            return
        if quorum is None or quorum.answered < quorum.floor:
            raise ValueError("synthesis runs only once the quorum was met")
        if synthesis.status != self.status or (
            failure is not None and failure.code != synthesis.code
        ):
            raise ValueError("the record's status and code are the synthesis's")

    def _indices(self) -> tuple[int, ...]:
        return tuple(entry.index for entry in self.selected)

    def document(self) -> dict[str, Any]:
        return _document(self, _RECORD_KEYS)


# --- readers --------------------------------------------------------------------------------------


_COMMON_KEYS = (
    "schema",
    "router",
    "revision",
    "revision_scheme",
    "policy",
    "evidence",
    "outcome",
    "reason",
    "selected",
    "unknown_labels",
)
_DRAFT_KEYS = (*_COMMON_KEYS, "failure")
_RECORD_KEYS = (
    *_COMMON_KEYS,
    "classifier_call",
    "branches",
    "quorum",
    "synthesis",
    "status",
    "failure",
)


def _document(model: BaseModel, keys: tuple[str, ...]) -> dict[str, Any]:
    """The document in its C5 key order (inherited fields would otherwise come first)."""
    dumped = model.model_dump(mode="json", by_alias=True)
    return {key: dumped[key] for key in keys}


def parse_router_draft(text: str) -> RouterDraft:
    """Read DECIDE's draft strictly.

    Raises:
        RouterDecisionError: the text is not one consistent draft.
    """
    draft = _read(RouterDraft, text, "router decision draft")
    if draft.failure is None and "failure" in _decoded(text, "router decision draft"):
        # WHY here: `failure: null` and no `failure` key validate alike; the draft has the key
        # only when its outcome failed (C5).
        raise RouterDecisionError(
            "router decision draft is invalid at failure (present only when failed)"
        )
    return draft


def parse_router_decision(text: str) -> RouterDecision:
    """Read a completed decision record strictly; a draft is refused.

    Raises:
        RouterDecisionError: the text is not one consistent completed record.
    """
    return _read(RouterDecision, text, "router decision")


def _decoded(text: str, owner: str) -> dict[str, object]:
    try:
        decoded = strict_json(text)
    except ValueError as exc:
        raise RouterDecisionError(f"{owner} is not strict JSON") from exc
    if not isinstance(decoded, dict):
        raise RouterDecisionError(f"{owner} is a JSON object")
    return decoded


def _read[T: BaseModel](kind: type[T], text: str, owner: str) -> T:
    _decoded(text, owner)
    try:
        return kind.model_validate_json(text)
    except ValidationError as exc:
        raise RouterDecisionError(f"{owner} is invalid at {field_rule(exc)}") from None


__all__ = [
    "DECISION_SCHEMA",
    "DRAFT_SCHEMA",
    "Branch",
    "ClassifierCall",
    "DraftFailure",
    "DraftPhase",
    "ModelSynthesis",
    "Outcome",
    "Phase",
    "Quorum",
    "Reason",
    "RecordFailure",
    "RouterDecision",
    "RouterDecisionError",
    "RouterDraft",
    "Selected",
    "Synthesis",
    "VoteSynthesis",
    "field_rule",
    "parse_router_decision",
    "parse_router_draft",
]
