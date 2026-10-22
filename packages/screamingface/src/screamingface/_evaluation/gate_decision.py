"""Strict decoder for the Engine's per-Gate decision record (``screamingface.gate-decision.v1``).

FEATURE: E4c (OME-1291, report RP-1, RP-20, contracts C8). The Engine attaches one record to each
Gate's JOIN operation ``op_gate_<n>``: the comparison, the value it read, the branch that ran, the
branches that made zero calls and why. This module decodes it into frozen values whose
``to_dict()`` writes the same JSON back, key for key and value for value.
STORY: as a reader of a saved Report, I see every Gate decision exactly as the Engine wrote it.

INVARIANT: strict, the ``combine_evidence`` policy. An unknown key, a missing key, a wrong schema
id or a broken invariant is an Engine/SDK version mismatch and raises ``ExecutionError`` naming
the field path; a message never echoes a value.
INVARIANT: the field order of each ``to_dict()`` is the Engine's wire order
(``E/combine/decision.py``), and a number keeps the type it had on the wire.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal, cast

from screamingface._evaluation.operation_accounting import _exact_keys, _mapping
from screamingface.answer import ABSTAIN_REASONS, AbstainReason
from screamingface.errors import ExecutionError

GATE_DECISION_SCHEMA = "screamingface.gate-decision.v1"

type GateKind = Literal["input", "panel"]
type BranchName = Literal["then", "otherwise"]
type Observed = bool | int | float | str | tuple[str, ...] | None
type Number = int | float

_DECISION_KEYS = {
    "schema",
    "gate_id",
    "kind",
    "when",
    "observed",
    "passed",
    "wanted",
    "branch",
    "selectors",
    "not_run",
    "budget",
    "result",
    "panel",
}
_WHEN_KEYS = {"observe", "cmp", "value"}
_SELECTOR_KEYS = {
    "id",
    "kind",
    "status",
    "labels",
    "parse",
    "raw",
    "parse_error",
    "input_chars",
    "input_sha256",
}
_NOT_RUN_KEYS = {"branch", "reason", "model_calls"}
_CALLS_KEYS = {"min", "max"}
_BUDGET_KEYS = {"unit", "cap", "spent", "unpriced", "estimate", "refused"}
_RESULT_KEYS = {"status", "reason"}
_PANEL_KEYS = {"operation_id", "branch"}

_KINDS = frozenset({"input", "panel"})
_BRANCHES = frozenset({"then", "otherwise"})
_CMPS = frozenset({">=", ">", "<=", "<", "eq", "ne", "has", "empty"})
_NOT_RUN_REASONS = frozenset({"not_selected", "budget_refused"})
_SELECTOR_KINDS = frozenset({"keywords", "label_model"})
_SELECTOR_STATUSES = frozenset({"computed", "not_run", "failed"})
_PARSES = frozenset({"ok", "no_match", "unrecognized", "unparsed"})
_RESULT_STATUSES = frozenset({"answered", "abstain", "fail_closed"})
_PANEL_BRANCHES = frozenset({"majority", "fallback", "band"})
_UNITS = frozenset({"usd", "tokens"})
_GATE_ID = re.compile(r"gate_[1-9]\d*")
_SELECTOR_ID = re.compile(r"sel_[1-9]\d*")
_LABEL = re.compile(r"[a-z][a-z0-9_]{0,31}")
_SHA256 = re.compile(r"[0-9a-f]{16}")
_PANEL_OBSERVE = re.compile(r"agreement|answered|(?:chosen|mean):.+")
_MAX_RAW = 64


@dataclass(frozen=True, slots=True)
class GateWhen:
    """The one comparison a Gate makes (GATE_SPEC ``when``)."""

    observe: str
    cmp: str
    value: Number | str | bool | None

    def to_dict(self) -> dict[str, object]:
        return {"observe": self.observe, "cmp": self.cmp, "value": self.value}


@dataclass(frozen=True, slots=True)
class GateSelector:
    """What one selector gave on this Case: labels, never the input or the reply text."""

    id: str
    kind: Literal["keywords", "label_model"]
    status: Literal["computed", "not_run", "failed"]
    labels: tuple[str, ...] | None
    parse: Literal["ok", "no_match", "unrecognized", "unparsed"] | None
    raw: str | None
    parse_error: str | None
    input_chars: int
    input_sha256: str

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "kind": self.kind,
            "status": self.status,
            "labels": None if self.labels is None else list(self.labels),
            "parse": self.parse,
            "raw": self.raw,
            "parse_error": self.parse_error,
            "input_chars": self.input_chars,
            "input_sha256": self.input_sha256,
        }


@dataclass(frozen=True, slots=True)
class GateNotRun:
    """One branch that made zero model calls, why, and the calls it avoided (min–max)."""

    branch: BranchName
    reason: Literal["not_selected", "budget_refused"]
    model_calls_min: int
    model_calls_max: int

    def to_dict(self) -> dict[str, object]:
        return {
            "branch": self.branch,
            "reason": self.reason,
            "model_calls": {"min": self.model_calls_min, "max": self.model_calls_max},
        }


@dataclass(frozen=True, slots=True)
class GateBudgetView:
    """The spend one decision saw for one declared unit (E4c budget, PR-3)."""

    unit: Literal["usd", "tokens"]
    cap: Number
    spent: Number
    unpriced: int
    estimate: Number | None
    refused: bool

    def to_dict(self) -> dict[str, object]:
        return {
            "unit": self.unit,
            "cap": self.cap,
            "spent": self.spent,
            "unpriced": self.unpriced,
            "estimate": self.estimate,
            "refused": self.refused,
        }


@dataclass(frozen=True, slots=True)
class GateResult:
    """How the branch that ran ended: answered, abstained (with its reason) or fail_closed."""

    status: Literal["answered", "abstain", "fail_closed"]
    reason: AbstainReason | None

    def to_dict(self) -> dict[str, object]:
        return {"status": self.status, "reason": self.reason}


@dataclass(frozen=True, slots=True)
class GatePanel:
    """A panel gate's decision call and the E4b gate record branch it read."""

    operation_id: str
    branch: Literal["majority", "fallback", "band"] | None

    def to_dict(self) -> dict[str, object]:
        return {"operation_id": self.operation_id, "branch": self.branch}


@dataclass(frozen=True, slots=True)
class GateDecision:
    """One Gate on one Case (``screamingface.gate-decision.v1``, erd §3)."""

    gate_id: str
    kind: GateKind
    when: GateWhen
    observed: Observed
    passed: bool | None
    wanted: BranchName | None
    branch: BranchName | None
    selectors: tuple[GateSelector, ...]
    not_run: tuple[GateNotRun, ...]
    budget: tuple[GateBudgetView, ...] | None
    result: GateResult | None
    panel: GatePanel | None

    def to_dict(self) -> dict[str, object]:
        return {
            "schema": GATE_DECISION_SCHEMA,
            "gate_id": self.gate_id,
            "kind": self.kind,
            "when": self.when.to_dict(),
            "observed": list(self.observed) if isinstance(self.observed, tuple) else self.observed,
            "passed": self.passed,
            "wanted": self.wanted,
            "branch": self.branch,
            "selectors": [selector.to_dict() for selector in self.selectors],
            "not_run": [entry.to_dict() for entry in self.not_run],
            "budget": None if self.budget is None else [view.to_dict() for view in self.budget],
            "result": None if self.result is None else self.result.to_dict(),
            "panel": None if self.panel is None else self.panel.to_dict(),
        }


def decode_gate_decision(value: object, label: str) -> GateDecision | None:
    """Decode one decision record, or preserve its absence; anything off-contract refuses."""

    if value is None:
        return None
    raw = _mapping(value, label)
    _exact_keys(raw, _DECISION_KEYS, label)
    if raw["schema"] != GATE_DECISION_SCHEMA:
        raise ExecutionError(f"{label} schema must be {GATE_DECISION_SCHEMA!r}")
    gate_id = _pattern(raw["gate_id"], _GATE_ID, f"{label} gate_id")
    kind = cast(GateKind, _word(raw["kind"], _KINDS, f"{label} kind"))
    when = _when(raw["when"], f"{label} when")
    decision = GateDecision(
        gate_id=gate_id,
        kind=kind,
        when=when,
        observed=_observed(raw["observed"], f"{label} observed"),
        passed=_optional_boolean(raw["passed"], f"{label} passed"),
        wanted=cast(BranchName | None, _optional_word(raw["wanted"], _BRANCHES, f"{label} wanted")),
        branch=cast(BranchName | None, _optional_word(raw["branch"], _BRANCHES, f"{label} branch")),
        selectors=tuple(
            _selector(item, f"{label} selectors[{index}]")
            for index, item in enumerate(_list(raw["selectors"], f"{label} selectors"))
        ),
        not_run=tuple(
            _not_run(item, f"{label} not_run[{index}]")
            for index, item in enumerate(_list(raw["not_run"], f"{label} not_run"))
        ),
        budget=_budget(raw["budget"], f"{label} budget"),
        result=_result(raw["result"], f"{label} result"),
        panel=_panel(raw["panel"], f"{label} panel"),
    )
    _check_kind(decision, label)
    _check_branches(decision, label)
    return decision


# --- invariants -----------------------------------------------------------------------------------


def _check_kind(decision: GateDecision, label: str) -> None:
    """GS-I2, GD-I4: a panel gate observes a panel number and links its decision call."""

    panel_observe = _PANEL_OBSERVE.fullmatch(decision.when.observe) is not None
    if (decision.kind == "panel") != panel_observe:
        raise ExecutionError(f"{label} kind does not match its when observe")
    if (decision.panel is not None) != (decision.kind == "panel"):
        raise ExecutionError(f"{label} panel is set exactly for a panel gate")


def _check_branches(decision: GateDecision, label: str) -> None:
    """GD-I1 and GD-I2: the not-run list agrees with the branch that ran and the one wanted."""

    named = [entry.branch for entry in decision.not_run]
    expected = {"then", "otherwise"} - ({decision.branch} if decision.branch else set())
    if len(set(named)) != len(named) or set(named) != expected:
        raise ExecutionError(f"{label} not_run must list exactly the branches that did not run")
    refused = {entry.branch for entry in decision.not_run if entry.reason == "budget_refused"}
    if decision.wanted is None:
        # D4's null row with the word fail_closed (cascade CA-30) fails the Case closed.
        answered = decision.result is not None and decision.result.status == "answered"
        if decision.branch is not None or refused or answered:
            raise ExecutionError(
                f"{label} wanted is null, so no branch ran and the gate did not answer"
            )
    elif (decision.branch != decision.wanted) != bool(refused):
        raise ExecutionError(f"{label} branch differs from wanted only on a budget refusal")


# --- fields ---------------------------------------------------------------------------------------


def _when(value: object, label: str) -> GateWhen:
    raw = _mapping(value, label)
    _exact_keys(raw, _WHEN_KEYS, label)
    item = raw["value"]
    if not (item is None or isinstance(item, bool | int | float | str)):
        raise ExecutionError(f"{label} value must be a number, a label, true or null")
    return GateWhen(
        observe=_text(raw["observe"], f"{label} observe"),
        cmp=_word(raw["cmp"], _CMPS, f"{label} cmp"),
        value=item,
    )


def _observed(value: object, label: str) -> Observed:
    if value is None or isinstance(value, bool | int | float | str):
        return value
    if isinstance(value, list):
        return tuple(_text(item, label) for item in value)
    raise ExecutionError(f"{label} must be a number, a label, a label list or null")


def _selector(value: object, label: str) -> GateSelector:
    raw = _mapping(value, label)
    _exact_keys(raw, _SELECTOR_KEYS, label)
    labels = raw["labels"]
    selector = GateSelector(
        id=_pattern(raw["id"], _SELECTOR_ID, f"{label} id"),
        kind=cast(
            Literal["keywords", "label_model"], _word(raw["kind"], _SELECTOR_KINDS, f"{label} kind")
        ),
        status=cast(
            Literal["computed", "not_run", "failed"],
            _word(raw["status"], _SELECTOR_STATUSES, f"{label} status"),
        ),
        labels=None if labels is None else _labels(labels, f"{label} labels"),
        parse=cast(
            Literal["ok", "no_match", "unrecognized", "unparsed"] | None,
            _optional_word(raw["parse"], _PARSES, f"{label} parse"),
        ),
        raw=_optional_text(raw["raw"], f"{label} raw"),
        parse_error=_optional_text(raw["parse_error"], f"{label} parse_error"),
        input_chars=_count(raw["input_chars"], f"{label} input_chars"),
        input_sha256=_pattern(raw["input_sha256"], _SHA256, f"{label} input_sha256"),
    )
    _check_selector(selector, label)
    return selector


def _check_selector(selector: GateSelector, label: str) -> None:
    """SR-I1 and the shape half of SR-I3: a record has labels exactly when it computed."""

    computed = selector.status == "computed"
    if computed != (selector.labels is not None and selector.parse is not None):
        raise ExecutionError(f"{label} has labels and a parse state exactly when it computed")
    if not computed and selector.raw is not None:
        raise ExecutionError(f"{label} raw is set only for a computed selector")
    if selector.parse_error is not None and selector.status != "failed":
        raise ExecutionError(f"{label} parse_error is set only for a failed selector")
    if selector.raw is not None and len(selector.raw) > _MAX_RAW:
        raise ExecutionError(f"{label} raw is at most {_MAX_RAW} characters")


def _labels(value: object, label: str) -> tuple[str, ...]:
    labels = tuple(
        _pattern(item, _LABEL, f"{label}[{index}]")
        for index, item in enumerate(_list(value, label))
    )
    if len(set(labels)) != len(labels):
        raise ExecutionError(f"{label} must be distinct")
    return labels


def _not_run(value: object, label: str) -> GateNotRun:
    raw = _mapping(value, label)
    _exact_keys(raw, _NOT_RUN_KEYS, label)
    calls = _mapping(raw["model_calls"], f"{label} model_calls")
    _exact_keys(calls, _CALLS_KEYS, f"{label} model_calls")
    low = _count(calls["min"], f"{label} model_calls min")
    high = _count(calls["max"], f"{label} model_calls max")
    if low > high:  # GD-I7
        raise ExecutionError(f"{label} model_calls min is at most max")
    return GateNotRun(
        branch=cast(BranchName, _word(raw["branch"], _BRANCHES, f"{label} branch")),
        reason=cast(
            Literal["not_selected", "budget_refused"],
            _word(raw["reason"], _NOT_RUN_REASONS, f"{label} reason"),
        ),
        model_calls_min=low,
        model_calls_max=high,
    )


def _budget(value: object, label: str) -> tuple[GateBudgetView, ...] | None:
    if value is None:
        return None
    views = tuple(
        _budget_view(item, f"{label}[{index}]") for index, item in enumerate(_list(value, label))
    )
    if len({view.unit for view in views}) != len(views):
        raise ExecutionError(f"{label} lists each unit once")
    return views


def _budget_view(value: object, label: str) -> GateBudgetView:
    raw = _mapping(value, label)
    _exact_keys(raw, _BUDGET_KEYS, label)
    estimate = raw["estimate"]
    return GateBudgetView(
        unit=cast(Literal["usd", "tokens"], _word(raw["unit"], _UNITS, f"{label} unit")),
        cap=_number(raw["cap"], f"{label} cap"),
        spent=_number(raw["spent"], f"{label} spent"),
        unpriced=_count(raw["unpriced"], f"{label} unpriced"),
        estimate=None if estimate is None else _number(estimate, f"{label} estimate"),
        refused=_boolean(raw["refused"], f"{label} refused"),
    )


def _result(value: object, label: str) -> GateResult | None:
    if value is None:
        return None
    raw = _mapping(value, label)
    _exact_keys(raw, _RESULT_KEYS, label)
    status = _word(raw["status"], _RESULT_STATUSES, f"{label} status")
    reason = _optional_word(raw["reason"], ABSTAIN_REASONS, f"{label} reason")
    if (status == "abstain") != (reason is not None):
        raise ExecutionError(f"{label} has a reason exactly when it abstained")
    return GateResult(
        status=cast(Literal["answered", "abstain", "fail_closed"], status),
        reason=cast(AbstainReason | None, reason),
    )


def _panel(value: object, label: str) -> GatePanel | None:
    if value is None:
        return None
    raw = _mapping(value, label)
    _exact_keys(raw, _PANEL_KEYS, label)
    return GatePanel(
        operation_id=_text(raw["operation_id"], f"{label} operation_id"),
        branch=cast(
            Literal["majority", "fallback", "band"] | None,
            _optional_word(raw["branch"], _PANEL_BRANCHES, f"{label} branch"),
        ),
    )


# --- scalars --------------------------------------------------------------------------------------


def _list(value: object, label: str) -> Sequence[object]:
    if not isinstance(value, list):
        raise ExecutionError(f"{label} must be a list")
    return value


def _text(value: object, label: str) -> str:
    if not isinstance(value, str):
        raise ExecutionError(f"{label} must be text")
    return value


def _optional_text(value: object, label: str) -> str | None:
    return None if value is None else _text(value, label)


def _pattern(value: object, pattern: re.Pattern[str], label: str) -> str:
    text = _text(value, label)
    if pattern.fullmatch(text) is None:
        raise ExecutionError(f"{label} has the wrong form")
    return text


def _word(value: object, allowed: frozenset[str], label: str) -> str:
    text = _text(value, label)
    if text not in allowed:
        raise ExecutionError(f"{label} must be one of {', '.join(sorted(allowed))}")
    return text


def _optional_word(value: object, allowed: frozenset[str], label: str) -> str | None:
    return None if value is None else _word(value, allowed, label)


def _boolean(value: object, label: str) -> bool:
    if not isinstance(value, bool):
        raise ExecutionError(f"{label} must be a boolean")
    return value


def _optional_boolean(value: object, label: str) -> bool | None:
    return None if value is None else _boolean(value, label)


def _count(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ExecutionError(f"{label} must be a non-negative integer")
    return value


def _number(value: object, label: str) -> Number:
    if isinstance(value, bool) or not isinstance(value, int | float) or value < 0:
        raise ExecutionError(f"{label} must be a non-negative number")
    return value


__all__ = ["GATE_DECISION_SCHEMA", "GateDecision", "decode_gate_decision"]
