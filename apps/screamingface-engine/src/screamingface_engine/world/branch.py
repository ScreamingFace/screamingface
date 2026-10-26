"""The branch runtime of sf.Gate: AFTER, DECIDE, OPEN and JOIN (E4c, OME-1291, branch-core).

FEATURE: a branch that is not selected makes zero model calls, and the report says it was not
selected and why. The SDK compiles every Gate to one named inner expression ``gate_N_block``:

    gate_N_after     = /ensemble/branch/v1/after(r1:0.0:$a, ...)!'after'
    gate_N_decide    = /ensemble/branch/v1/decide({after, keywords?, selectors?})?gate=gate_N
    gate_N_open_then = /ensemble/branch/v1/open($gate_N_decide)!'then'
    gate_N_then      = $gate_N_open_then*(<then body>)!'$<then terminal>';iteration.on_error=fail
    gate_N_open_else = /ensemble/branch/v1/open($gate_N_decide)!'otherwise'
    gate_N_else      = $gate_N_open_else*(<otherwise body>)!...
    gate_N           = /ensemble/branch/v1/join({decision, then?, otherwise?})?binding=gate_N

The gate spec (``gate-spec.v1``) is the intent of DECIDE and JOIN, as a combine spec is the intent
of a combine call, so the url4 decode reads it like any call's intent.

STORY: OPEN returns a one-item collection only for the branch DECIDE chose, so url4 runs no
element of the other branch's iterate (url4 Spec B §5.3.9). JOIN returns the taken branch's text
and copies how that branch ended into the decision record.

WHY an adapter here, not in ``combine/``: this module imports url4; ``combine/`` never imports
``world/`` (contracts C12). It reads the pure ``combine.decision`` and ``combine.ports``.
INVARIANT: every endpoint is pure given its context and the recorded calls of the Case scope; no
model call, no clock, nothing kept in request scope (branch-core D11).
INVARIANT: a record holds labels, numbers and ids only (GD-I5); an error message names the field,
never a value from the context.
WHY a struct context with absent keys: a url4 struct has no null value, so an input a Gate does
not read is a missing key, and the decision call's binding sits in the spec (``panel``).
"""

from __future__ import annotations

import functools
import hashlib
import json
import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal, localcontext
from typing import Any, Literal, cast

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from screamingface_engine.benchmarks.failure_classes import (
    benchmark_contract_error as _contract_error,
)
from screamingface_engine.benchmarks.failure_classes import fail_closed
from screamingface_engine.budget import (
    Budget,
    BudgetUnit,
    charge,
    current_case_budgets,
    first_unpriced_warning,
    fold,
)
from screamingface_engine.combine.decision import (
    GATE_DECISION_SCHEMA,
    LABEL,
    SELECTOR_ID,
    BranchName,
    BudgetView,
    GateCondition,
    GateDecision,
    GateKind,
    GateResult,
    ModelCalls,
    NotRunEntry,
    PanelLink,
    SelectorRecord,
    parse_gate_decision,
)
from screamingface_engine.combine.evidence import GateRecord
from screamingface_engine.combine.gate import passes
from screamingface_engine.combine.operators.extract import compile_regex, re2_head
from screamingface_engine.combine.ports import (
    DECIMAL_CONTEXT,
    CombineError,
    GateCmp,
    parse_selector_reply,
)
from screamingface_engine.operation_accounting import SignalAccounting
from screamingface_engine.operation_calls import (
    OperationCall,
    current_operation_calls,
    latest_operation_call,
    provider_calls_by_fingerprint,
    record_gate_call,
)
from url4.peer.server import Request, Url4Node

logger = logging.getLogger(__name__)

BRANCH_PREFIX = "/ensemble/branch/v1"
AFTER_ROUTE = f"{BRANCH_PREFIX}/after"
DECIDE_ROUTE = f"{BRANCH_PREFIX}/decide"
OPEN_ROUTE = f"{BRANCH_PREFIX}/open"
JOIN_ROUTE = f"{BRANCH_PREFIX}/join"
GATE_SPEC_SCHEMA = "screamingface.gate-spec.v1"
KEYWORDS_ROUTE = "/ensemble/select/v1/keywords"
# SL-23: Keywords scan the first 65,536 characters of the Case input.
KEYWORDS_WINDOW = 65_536
MAX_KEYWORD_RULES = 32
# BC-22: the inputs are labels, numbers and ids; answers sit behind AFTER, never in DECIDE.
MAX_BRANCH_CONTEXT_BYTES = 1024 * 1024

_DECIDE_KEYS = frozenset({"after", "keywords", "selectors"})
_JOIN_KEYS = frozenset({"decision", "then", "otherwise"})
_BRANCHES: tuple[BranchName, BranchName] = ("then", "otherwise")
BodyKind = Literal["recipe", "step", "abstain", "fail_closed", "skip"]


# --- the spec (screamingface.gate-spec.v1, erd §1) ---------------------------------------------


class _SpecModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True, allow_inf_nan=False)


class _KeywordRule(_SpecModel):
    label: str
    pattern: str = Field(min_length=1, max_length=256)
    ignore_case: bool = False


class SelectorSpec(_SpecModel):
    """What DECIDE needs to record one selector: its kind, labels and the LabelModel binding.

    ``rules`` repeats a Keywords selector's rules, so the url4 decode can rebuild the selector from
    the gate spec alone (the KEYWORDS source evaluates them; DECIDE does not read them).
    """

    kind: Literal["keywords", "label_model"]
    multi: bool
    labels: list[str] = Field(min_length=1, max_length=32)
    binding: str | None
    rules: list[_KeywordRule] | None = None

    @model_validator(mode="after")
    def _check(self) -> SelectorSpec:
        if (self.kind == "label_model") != (self.binding is not None):
            raise ValueError("a LabelModel selector names its call binding, a Keywords one none")
        if (self.kind == "keywords") != (self.rules is not None):
            raise ValueError("a Keywords selector repeats its rules, a LabelModel one none")
        if any(LABEL.fullmatch(label) is None for label in self.labels):
            raise ValueError("selector labels are well-formed labels")
        return self


class BranchCalls(_SpecModel):
    then: ModelCalls
    otherwise: ModelCalls


class BranchReads(_SpecModel):
    then: list[str]
    otherwise: list[str]


class BranchTerminal(_SpecModel):
    then: str | None
    otherwise: str | None


class Estimate(_SpecModel):
    usd: int | float | None = Field(default=None, ge=0)
    tokens: int | None = Field(default=None, ge=0)


class BranchEstimate(_SpecModel):
    then: Estimate | None
    otherwise: Estimate | None


class PanelSpec(_SpecModel):
    binding: str


class GateSpec(_SpecModel):
    """The comparison a Gate makes and what DECIDE and JOIN need to record it."""

    schema_id: Literal["screamingface.gate-spec.v1"] = Field(alias="schema")
    kind: GateKind
    when: GateCondition
    then: Literal["recipe", "step", "abstain", "fail_closed"]
    otherwise: BodyKind
    panel: PanelSpec | None
    calls: BranchCalls
    selectors: dict[str, SelectorSpec]
    reads: BranchReads
    estimate: BranchEstimate
    ancestors: list[tuple[str, list[tuple[str, str]]]]
    terminal: BranchTerminal

    @model_validator(mode="after")
    def _check(self) -> GateSpec:
        if (self.kind == "panel") != (self.panel is not None):
            raise ValueError("a panel gate names its decision call, an input gate none")
        named = {*self.reads.then, *self.reads.otherwise, *_condition_selector(self.when)}
        if not named <= self.selectors.keys() or not all(
            SELECTOR_ID.fullmatch(key) for key in self.selectors
        ):
            raise ValueError("a gate spec declares every selector it reads")
        for branch in _BRANCHES:
            if self.body(branch) in ("abstain", "fail_closed", "skip") and (
                self.terminal_of(branch) is not None or getattr(self.calls, branch).max != 0
            ):
                raise ValueError("a word body has no terminal and makes no call")
        return self

    def body(self, branch: BranchName) -> BodyKind:
        return self.then if branch == "then" else self.otherwise

    def terminal_of(self, branch: BranchName) -> str | None:
        return getattr(self.terminal, branch)


def _condition_selector(when: GateCondition) -> tuple[str, ...]:
    kind, _, selector = when.observe.partition(":")
    return (selector,) if kind in ("label", "labels") else ()


# --- installation ------------------------------------------------------------------------------


def install_branch_runtime(node: Url4Node) -> None:
    """Register the Gate endpoints once per URL4 world (the corrective-runtime pattern)."""

    routes = frozenset(node.processor_routes())
    endpoints = (
        (AFTER_ROUTE, _after),
        (DECIDE_ROUTE, _decide),
        (OPEN_ROUTE, _open),
        (JOIN_ROUTE, _join),
        (KEYWORDS_ROUTE, _keywords),
    )
    for route, handler in endpoints:
        if route not in routes:
            node.endpoint(route)(handler)


# --- KEYWORDS ----------------------------------------------------------------------------------


class KeywordsSpec(_SpecModel):
    """One ``screamingface.keywords.v1`` selector (erd §2)."""

    schema_id: Literal["screamingface.keywords.v1"] = Field(alias="schema")
    multi: bool
    rules: list[_KeywordRule] = Field(min_length=1, max_length=MAX_KEYWORD_RULES)

    @model_validator(mode="after")
    def _check(self) -> KeywordsSpec:
        labels = [rule.label for rule in self.rules]
        if any(LABEL.fullmatch(label) is None for label in labels) or len(set(labels)) != len(
            labels
        ):
            raise ValueError("keywords labels are distinct well-formed labels")
        return self


def _keywords(request: Request) -> str:
    """Every Keywords selector of a Gate tree on the Case input, plus the input summary (D6).

    FEATURE: SL-1 - SL-4, SL-17, SL-23, SL-27. Pure: RE2, the first 65,536 characters, first
    match in declared order (or every match for ``multi``). The summary (length and the first 16
    hex digits of the SHA-256) lets every selector record describe the input without its text.
    """

    if not isinstance(request.intent, str):
        raise _contract_error("keywords intent is JSON text")
    selectors = _parsed_keywords(request.intent)
    text = request.context or ""
    head = re2_head(text, KEYWORDS_WINDOW)
    digest = hashlib.sha256(text.encode("utf-8", "surrogatepass")).hexdigest()[:16]
    result: dict[str, object] = {"summary": {"chars": len(text), "sha256": digest}}
    for selector, (multi, rules) in selectors.items():
        matched = [label for label, compiled in rules if compiled.search(head) is not None]
        result[selector] = {"labels": matched if multi else matched[:1], "matched": matched}
    return json.dumps(result, ensure_ascii=False, separators=(",", ":"))


type _CompiledRules = tuple[tuple[str, Any], ...]


# WHY cached: every Case of a run sends the same KEYWORDS intent; each rule compiles once.
@functools.lru_cache(maxsize=64)
def _parsed_keywords(intent: str) -> dict[str, tuple[bool, _CompiledRules]]:
    """selector id -> (multi, (label, RE2 object) per rule in declared order)."""

    selectors: dict[str, tuple[bool, _CompiledRules]] = {}
    for selector, value in _json_object(intent, "keywords intent").items():
        if SELECTOR_ID.fullmatch(selector) is None:
            raise _contract_error("keywords intent maps selector ids to keywords specs")
        try:
            spec = KeywordsSpec.model_validate(value)
        except ValidationError as exc:
            raise _contract_error(f"keywords spec {selector} is invalid at {_field(exc)}") from exc
        selectors[selector] = (
            spec.multi,
            tuple((rule.label, _compiled(rule, selector)) for rule in spec.rules),
        )
    return selectors


def _compiled(rule: _KeywordRule, selector: str) -> Any:
    try:
        return compile_regex({"pattern": rule.pattern, "ignore_case": rule.ignore_case})
    except CombineError as exc:
        raise _contract_error(f"keywords spec {selector} has a pattern RE2 cannot run") from exc


# --- AFTER -------------------------------------------------------------------------------------


def _after(_request: Request) -> str:
    """Order DECIDE after what it reads (branch-core D10).

    WHY it exists: url4 orders work only through dependency edges. AFTER's slots are instrumental
    (weight 0.0): they keep the edge and pack no answer bytes, so its context is empty and it never
    reads it.
    """
    return ""


# --- DECIDE ------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _Choice:
    observed: bool | float | str | list[str] | None
    passed: bool | None
    wanted: BranchName | None
    panel: PanelLink | None = None


def _decide(request: Request) -> str:
    gate_id = _one_param(request.params, "gate", "decide takes exactly one param, gate=gate_N")
    context = _context(request.context, _DECIDE_KEYS, ("after",), "decide")
    spec = _spec(request.intent)
    inputs = _SelectorInputs.read(context, spec)
    ledger = _BudgetLedger.read(spec)
    choice = _panel_choice(spec) if spec.panel is not None else _input_choice(spec, inputs, ledger)
    views, refused = ledger.views(spec, choice.wanted)
    branch = _branch_after_budget(spec, choice.wanted, refused)
    not_run = [
        NotRunEntry(
            branch=name,
            reason="budget_refused" if refused and name == choice.wanted else "not_selected",
            model_calls=getattr(spec.calls, name),
        )
        for name in _BRANCHES
        if name != branch
    ]
    listed = [*_condition_selector(spec.when)]
    for entry in not_run:
        listed.extend(getattr(spec.reads, entry.branch))
    record = GateDecision.model_validate(
        {
            "schema": GATE_DECISION_SCHEMA,
            "gate_id": gate_id,
            "kind": spec.kind,
            "when": spec.when,
            "observed": choice.observed,
            "passed": choice.passed,
            "wanted": choice.wanted,
            "branch": branch,
            "selectors": [inputs.record(selector) for selector in dict.fromkeys(listed)],
            "not_run": not_run,
            "budget": views,
            "result": None,
            "panel": choice.panel,
        }
    )
    # D3: DECIDE publishes under the JOIN fingerprint; JOIN's record replaces it when JOIN runs.
    record_gate_call(JOIN_ROUTE, {"binding": gate_id}, "", record)
    _log_budget(gate_id, views or ())
    return record.model_dump_json(by_alias=True)


def _log_budget(gate_id: str, views: Sequence[BudgetView]) -> None:
    """Budget §4: one line per unit; an unpriced count logs once per Case (numbers only)."""

    for view in views:
        logger.info(
            "gate=%s budget=%s unit=%s spent=%s cap=%s",
            gate_id,
            "refused" if view.refused else "ok",
            view.unit,
            view.spent,
            view.cap,
        )
        if view.unpriced and first_unpriced_warning(view.unit):
            logger.warning(
                "gate=%s budget unit=%s: %d ancestor call(s) had no known cost and count as 0",
                gate_id,
                view.unit,
                view.unpriced,
            )


@dataclass(frozen=True, slots=True)
class _SelectorInputs:
    """The selector results DECIDE received: the tree's KEYWORDS response and LabelModel replies."""

    spec: GateSpec
    keywords: Mapping[str, object] | None
    replies: Mapping[str, str]

    @classmethod
    def read(cls, context: Mapping[str, object], spec: GateSpec) -> _SelectorInputs:
        keywords = None
        if "keywords" in context:
            keywords = _json_object(context["keywords"], "decide context keywords")
        replies = context.get("selectors", {})
        if not isinstance(replies, dict) or not all(
            isinstance(key, str) and key in spec.selectors and isinstance(value, str)
            for key, value in replies.items()
        ):
            raise _contract_error("decide context selectors maps declared selector ids to text")
        return cls(spec, keywords, replies)

    def record(self, selector: str) -> SelectorRecord:
        declared = self.spec.selectors[selector]
        chars, sha256 = self._summary()
        fields: dict[str, object] = {
            "id": selector,
            "kind": declared.kind,
            "status": "not_run",
            "labels": None,
            "parse": None,
            "raw": None,
            "parse_error": None,
            "input_chars": chars,
            "input_sha256": sha256,
        }
        if declared.kind == "keywords":
            labels = self._keywords_labels(selector, declared)
            fields |= {"status": "computed", "labels": labels}
            fields["parse"] = "ok" if labels else "no_match"
        elif selector in self.replies:
            fields |= _label_model_fields(self.replies[selector], declared)
        try:
            return SelectorRecord.model_validate(fields)
        except ValidationError as exc:
            raise _contract_error(f"selector {selector} gave an invalid record") from exc

    def _summary(self) -> tuple[int, str]:
        summary = None if self.keywords is None else self.keywords.get("summary")
        if not isinstance(summary, dict):
            raise _contract_error("decide context keywords holds the input summary")
        chars, sha256 = summary.get("chars"), summary.get("sha256")
        if not isinstance(chars, int) or isinstance(chars, bool) or not isinstance(sha256, str):
            raise _contract_error("decide context keywords summary is chars and sha256")
        return chars, sha256

    def _keywords_labels(self, selector: str, declared: SelectorSpec) -> list[str]:
        result = None if self.keywords is None else self.keywords.get(selector)
        labels = result.get("labels") if isinstance(result, dict) else None
        if (
            not isinstance(labels, list)
            or not all(isinstance(label, str) and label in declared.labels for label in labels)
            or (not declared.multi and len(labels) > 1)
        ):
            raise _contract_error(f"decide context keywords has no result for {selector}")
        return labels


def _label_model_fields(reply: str, declared: SelectorSpec) -> dict[str, object]:
    # SL-12: a failed ;optional call leaves its $name unbound, so url4 hands over the literal text.
    if reply == f"${declared.binding}":
        return {"status": "failed"}
    labels, parse, raw = parse_selector_reply(reply, declared.labels, multi=declared.multi)
    return {"status": "computed", "labels": labels, "parse": parse, "raw": raw}


def _input_choice(spec: GateSpec, inputs: _SelectorInputs, ledger: _BudgetLedger) -> _Choice:
    when = spec.when
    kind, _, selector = when.observe.partition(":")
    if kind == "budget.remaining":
        # BU-6: the decision sees what is left after its ancestors' charges.
        remaining = ledger.left[cast("BudgetUnit", selector)]
        passed = passes(remaining, cast("GateCmp", when.cmp), cast("float", when.value))
        return _Choice(remaining, passed, "then" if passed else "otherwise")
    labels = inputs.record(selector).labels  # None: the selector call failed (SL-12)
    observed: str | list[str] | None
    if kind == "label":
        observed = labels[0] if labels else None
        passed = (observed == when.value) if when.cmp == "eq" else (observed != when.value)
    else:
        observed = labels
        passed = labels is not None and (when.value in labels if when.cmp == "has" else not labels)
    return _Choice(observed, passed, "then" if passed else "otherwise")


def _branch_after_budget(
    spec: GateSpec, wanted: BranchName | None, refused: bool
) -> BranchName | None:
    """P11 (BU-4, BU-5): a refused branch falls back to the other branch only when that one is a
    step that makes no model call (the current answer); else no branch runs and the Gate abstains
    ``budget_refused``. A word is no current answer: a refusal never takes ``fail_closed``
    (BU-10) or the ``gate_not_met`` abstain."""

    if wanted is None or not refused:
        return wanted
    other: BranchName = "otherwise" if wanted == "then" else "then"
    current = spec.body(other) == "step" and getattr(spec.calls, other).max == 0
    return other if current else None


@dataclass(frozen=True, slots=True)
class _BudgetLedger:
    """The spend of one decision's ancestors, per declared unit (erd §5, branch-core D7)."""

    budgets: tuple[Budget, ...]
    spent: Mapping[str, float]
    left: Mapping[str, float]
    unpriced: Mapping[str, int]

    @classmethod
    def read(cls, spec: GateSpec) -> _BudgetLedger:
        budgets = current_case_budgets()
        if spec.when.observe.startswith("budget.remaining:") and not any(
            budget.unit == spec.when.observe.partition(":")[2] for budget in budgets
        ):
            raise _contract_error("decide spec reads a budget, but the candidate has no Budget")
        spent: dict[str, float] = {}
        left: dict[str, float] = {}
        unpriced: dict[str, int] = {}
        if budgets:
            index = provider_calls_by_fingerprint(current_operation_calls() or ())
            # BU-20: an ancestor with no record charges nothing; each recorded call charges once.
            calls = [
                call for key in dict.fromkeys(map(_fingerprint, spec.ancestors))
                for call in index.get(key, ())
            ]  # fmt: skip
            for budget in budgets:
                amounts = [
                    charge(call.signal_accounting or SignalAccounting(), budget.unit, cached=False)[
                        0
                    ]
                    for call in calls
                ]
                spent[budget.unit], left[budget.unit], unpriced[budget.unit] = fold(
                    budget.cap, amounts
                )
        return cls(budgets, spent, left, unpriced)

    def views(
        self, spec: GateSpec, wanted: BranchName | None
    ) -> tuple[list[BudgetView] | None, bool]:
        """One view per declared unit, and whether either unit refuses ``wanted`` (BU-2)."""

        if not self.budgets:
            return None, False
        calls = None if wanted is None else getattr(spec.calls, wanted)
        estimate = None if wanted is None else getattr(spec.estimate, wanted)
        views: list[BudgetView] = []
        for budget in self.budgets:
            amount = None if estimate is None else getattr(estimate, budget.unit)
            spent, cap = Decimal(repr(self.spent[budget.unit])), Decimal(repr(budget.cap))
            with localcontext(DECIMAL_CONTEXT):
                # BU-16, BU-17: refuse on spent + estimate > cap; with no estimate, on spent >= cap.
                over = spent + Decimal(repr(amount)) > cap if amount is not None else spent >= cap
            refused = calls is not None and calls.max > 0 and over
            views.append(
                BudgetView(
                    unit=budget.unit,
                    cap=_number(budget.cap, budget.unit),
                    spent=_number(self.spent[budget.unit], budget.unit),
                    unpriced=self.unpriced[budget.unit],
                    estimate=amount,
                    refused=refused,
                )
            )
        return views, any(view.refused for view in views)


def _number(value: float, unit: BudgetUnit) -> int | float:
    return int(value) if unit == "tokens" and value.is_integer() else value


def _fingerprint(
    ancestor: tuple[str, list[tuple[str, str]]],
) -> tuple[str, tuple[tuple[str, str], ...]]:
    path, params = ancestor
    return path, tuple(sorted((key, value) for key, value in params))


def _panel_choice(spec: GateSpec) -> _Choice:
    """The panel branch rule (branch-core D4): read the decision call's record, map its branch."""

    assert spec.panel is not None  # the caller checked
    binding = spec.panel.binding
    call = _recorded(binding)
    if call is None:
        raise _contract_error(f"the decision call {binding} left no record")
    link_branch, observed, passed, majority = _panel_reading(spec, call)
    if majority is None:
        # band (no comparison) or no voters: a recipe otherwise escalates, anything else abstains
        wanted: BranchName | None = (
            "otherwise" if link_branch != "band" and spec.otherwise == "recipe" else None
        )
    else:
        wanted = "then" if majority else "otherwise"
    link = PanelLink(operation_id=f"op_{binding}", branch=link_branch)
    return _Choice(observed, passed, wanted, link)


def _panel_reading(
    spec: GateSpec, call: OperationCall
) -> tuple[
    Literal["majority", "fallback", "band"] | None, float | bool | None, bool | None, bool | None
]:
    """(gate record branch, observed, passed, majority-or-None) of the decision call."""

    if spec.when.observe == "answered":
        if call.combine is None:
            raise _contract_error("an answered gate reads a complete decision call")
        answered = call.combine.result.status == "answered"
        return None, answered, answered, True if answered else None
    gate = call.gate_record if call.pending else (call.combine and call.combine.gate)
    if gate is None:
        raise _contract_error("the decision call wrote no gate record")
    _check_agrees(spec.when, gate)
    majority = None if gate.branch in (None, "band") else gate.branch == "majority"
    return gate.branch, gate.observed, gate.passed, majority


def _check_agrees(when: GateCondition, gate: GateRecord) -> None:
    if (when.observe, when.cmp, when.value) != (gate.observe, gate.cmp, gate.threshold):
        raise _contract_error("the gate spec and its decision call compare different values")


# --- OPEN --------------------------------------------------------------------------------------


def _open(request: Request) -> str:
    """``[{}]`` iff DECIDE chose the intent's branch, else ``[]`` (the corrective gate shape)."""

    if request.intent not in _BRANCHES:
        raise _contract_error("open intent is then or otherwise")
    record = _decision(request.context or "", "open context")
    return "[{}]" if record.branch == request.intent else "[]"


# --- JOIN --------------------------------------------------------------------------------------


def _join(request: Request) -> str:
    gate_id = _one_param(request.params, "binding", "join takes exactly one param, binding=gate_N")
    context = _context(request.context, _JOIN_KEYS, ("decision",), "join")
    spec = _spec(request.intent)
    record = _decision(context["decision"], "join context decision")
    if record.gate_id != gate_id:
        raise _contract_error("join binding and decision name different gates")
    slots: dict[BranchName, list[str]] = {
        branch: _slot(context[branch], branch) for branch in _BRANCHES if branch in context
    }
    ran = [branch for branch, rows in slots.items() if rows]
    if len(ran) > 1:
        raise _contract_error("a gate ran both branches")  # GD-I1
    if ran and ran[0] != record.branch:
        raise _contract_error("a gate ran a branch it did not choose")
    text, result = _joined(spec, record, slots)
    # WHY validate and not model_copy: the published record must hold every GD invariant.
    completed = GateDecision.model_validate(
        {
            **record.model_dump(by_alias=True),
            "result": None if result is None else result.model_dump(),
        }
    )
    record_gate_call(JOIN_ROUTE, {"binding": gate_id}, text, completed)
    logger.info(
        "gate=%s branch=%s result=%s",
        gate_id,
        record.branch or "none",
        "none" if result is None else result.status,
    )
    if result is not None and result.status == "fail_closed":
        raise fail_closed(gate_id)
    return text


def _joined(
    spec: GateSpec, record: GateDecision, slots: Mapping[BranchName, list[str]]
) -> tuple[str, GateResult | None]:
    """The taken branch's text and how it ended (branch-core D12)."""

    branch = record.branch
    if branch is None:
        return _no_branch(spec, record)
    body = spec.body(branch)
    if body in ("abstain", "fail_closed", "skip"):
        return "", _word_result(body)
    terminal = spec.terminal_of(branch)
    if terminal is None:
        raise _contract_error("a recipe or step branch names its terminal binding")
    rows = slots.get(branch)
    if rows is not None and len(rows) != 1:
        raise _contract_error("the taken branch gave no answer")
    return _terminal_answer(_recorded(terminal), rows)


def _terminal_answer(call: OperationCall | None, rows: list[str] | None) -> tuple[str, GateResult]:
    """The taken branch's text and result from its terminal call and its iterate rows."""

    if call is not None and call.pending:
        # BU-18: the Budget refused the fallback, so the step slot answers with the majority
        # answer the pending decision call kept.
        if call.kept_output is None:
            return "", GateResult(status="abstain", reason="budget_refused")
        return call.kept_output, GateResult(status="answered", reason=None)
    # A step slot that is the decision call's own reducer has no iterate: its text is the call's.
    text = rows[0] if rows is not None else ("" if call is None else call.output)
    return text, _call_result(call)


def _no_branch(spec: GateSpec, record: GateDecision) -> tuple[str, GateResult | None]:
    """No branch ran: a band hit or no voters copy the decision call's abstain (D4, ans:Q25)."""

    if record.wanted is not None:
        # BU-5: the Budget refused the wanted branch and the other branch also makes a call.
        return "", GateResult(status="abstain", reason="budget_refused")
    if spec.panel is None:
        raise _contract_error("a gate ran no branch without a panel abstain")
    if record.panel is not None and record.panel.branch is None and spec.otherwise == "fail_closed":
        return "", GateResult(status="fail_closed", reason=None)
    call = _recorded(spec.panel.binding)
    return ("" if call is None else call.output), _call_result(call)


def _word_result(body: BodyKind) -> GateResult | None:
    if body == "abstain":
        return GateResult(status="abstain", reason="gate_not_met")
    if body == "fail_closed":
        return GateResult(status="fail_closed", reason=None)
    return None  # skip: an unselected skip-Gate member returns "" with no result (D8)


def _call_result(call: OperationCall | None) -> GateResult:
    """The result of a terminal call: an inner Gate's, a combine step's, or a model's answer."""

    if call is not None and call.decision is not None and call.decision.result is not None:
        return call.decision.result
    if call is not None and call.combine is not None:
        result = call.combine.result
        return GateResult(status=result.status, reason=result.reason)
    return GateResult(status="answered", reason=None)


def _slot(value: object, branch: str) -> list[str]:
    """An iterate result: ``[]`` (not run) or ``["<body text>"]`` (url4 JSON array text)."""

    rows = _json(value, f"join context {branch}")
    if not isinstance(rows, list) or not all(isinstance(row, str) for row in rows):
        raise _contract_error(f"join context {branch} is an iterate result")
    return rows


# --- shared ------------------------------------------------------------------------------------


def _recorded(binding: str) -> OperationCall | None:
    """The last recorded call that carries ``binding=<binding>`` in this Case's scope (D11).

    WHY by the binding param: every call inside a gated body, and every combine, judge, writer
    and Gate call, carries its binding, and a binding name is unique in a candidate.
    """

    wanted = ("binding", binding)
    return latest_operation_call(lambda call: wanted in call.params)


def _context(
    text: str | None, keys: frozenset[str], required: tuple[str, ...], owner: str
) -> dict[str, object]:
    if (
        text is None
        or len(text) > MAX_BRANCH_CONTEXT_BYTES
        or (len(text.encode("utf-8")) > MAX_BRANCH_CONTEXT_BYTES)
    ):
        raise _contract_error(f"{owner} context is missing or larger than 1 MiB")
    context = _json_object(text, f"{owner} context")
    unknown = sorted(context.keys() - keys)
    if unknown:
        raise _contract_error(f"{owner} context has an unknown key {unknown[0]!r}")
    missing = [key for key in required if key not in context]
    if missing:
        raise _contract_error(f"{owner} context has no {missing[0]!r}")
    return context


# WHY cached: DECIDE and JOIN of one Gate parse the same intent text on every Case.
@functools.lru_cache(maxsize=64)
def _parsed_spec(intent: str) -> GateSpec:
    return GateSpec.model_validate_json(intent)


def _spec(value: object) -> GateSpec:
    if not isinstance(value, str):
        raise _contract_error("gate spec is JSON text")
    try:
        return _parsed_spec(value)
    except ValidationError as exc:
        raise _contract_error(f"gate spec is invalid at {_field(exc)}") from exc


def _decision(value: object, owner: str) -> GateDecision:
    if not isinstance(value, str):
        raise _contract_error(f"{owner} is a gate decision record")
    try:
        return parse_gate_decision(value)
    except ValidationError as exc:
        raise _contract_error(f"{owner} is invalid at {_field(exc)}") from exc


def _field(exc: ValidationError) -> str:
    """The first failing field path, never the input value (BC-11)."""
    errors = exc.errors(include_input=False, include_url=False)
    return ".".join(str(part) for part in errors[0]["loc"]) or "the root" if errors else "the root"


def _json(value: object, owner: str) -> object:
    if not isinstance(value, str):
        raise _contract_error(f"{owner} is JSON text")
    try:
        return json.loads(value)
    except ValueError as exc:
        raise _contract_error(f"{owner} is not valid JSON") from exc


def _json_object(value: object, owner: str) -> dict[str, object]:
    decoded = _json(value, owner)
    if not isinstance(decoded, dict):
        raise _contract_error(f"{owner} is a JSON object")
    return decoded


def _one_param(params: Mapping[str, str], key: str, message: str) -> str:
    """The value of the one param a Gate endpoint takes; any other set is a contract error."""

    value = params.get(key)
    if set(params) != {key} or value is None:
        raise _contract_error(message)
    return value


__all__ = [
    "AFTER_ROUTE",
    "BRANCH_PREFIX",
    "DECIDE_ROUTE",
    "GATE_SPEC_SCHEMA",
    "JOIN_ROUTE",
    "KEYWORDS_ROUTE",
    "OPEN_ROUTE",
    "GateSpec",
    "install_branch_runtime",
]
