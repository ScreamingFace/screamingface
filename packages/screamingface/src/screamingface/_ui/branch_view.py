"""The Branches views of the report (E4c, OME-1291, report PRD): the Case pane and the run summary.

FEATURE: per Case, one section per sf.Gate that ran, in nesting order: the condition in source
form, the value it read, the branch that ran, each branch that made zero calls and why, the
selector labels, and how the branch ended. Per run, a "gates" block with the counts per Gate and
one ladder line per chain of Gates (CARGO: the share resolved at the first branch).
STORY: as a researcher whose result is a saving, I audit every skip from the report alone.

INVARIANT: every text from data goes through html.escape; numbers use the Combine view's helpers
(4 significant digits, the exact value as the title); a missing value is an em dash with a title.
INVARIANT: the views read only the decision records and the Candidate topology; Attempt
operations are not shown or counted (E4b P15).
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from functools import lru_cache
from html import escape
from typing import TYPE_CHECKING

from screamingface._evaluation.gate_decision import _MAX_RAW
from screamingface._ui.combine_view import _label, dash_html, number_html
from screamingface._ui.text import short

if TYPE_CHECKING:
    from screamingface._evaluation.gate_decision import (
        GateBudgetView,
        GateDecision,
        GateNotRun,
        GateSelector,
        GateWhen,
    )
    from screamingface._evaluation.topology import _RecipeTopology
    from screamingface.budget import BudgetUnit
    from screamingface.case_result import CaseOperation, CaseResult
    from screamingface.operation import OperationInfo
    from screamingface.report import CandidateResult

_FAIL_CLOSED = "fail_closed"
_MAX_INDENT = 4  # RP-31: the indent stops growing after level 4
_INDENT_PX = 16
_MAX_LABELS = 8  # RP-30
_KEYWORDS_WINDOW = 65_536
_NO_NUMBER = "no number to compare"
_NO_LABEL = "the selector gave no usable label"
_NO_RECORD = "no decision record for this gate"
_NOT_FINISHED = "the branch did not finish"
_FAILED_SELECTOR = "the selector call failed; its code is in the activity view"
_NOT_RUN_REASONS = {"not_selected": "not selected", "budget_refused": "refused by the budget"}
_SELECTOR_KINDS = {"keywords": "keywords", "label_model": "label model"}
_UNPRICED = "the provider gave no cost; the budget counts these calls as $0"


# --- the Gate tree, from the Candidate topology ---------------------------------------------------


@dataclass(frozen=True, slots=True)
class _GateTree:
    """The Gates of one Candidate: top-level ones in order, the Gates inside each branch (direct
    ``children``; ``below``: at any depth, in nesting order), and the chains where each Gate is the
    ``otherwise`` of the one before (a Cascade, an N-way router)."""

    roots: tuple[str, ...] = ()
    children: Mapping[tuple[str, str], tuple[str, ...]] = field(default_factory=dict)
    chains: tuple[tuple[str, ...], ...] = ()
    below: Mapping[tuple[str, str], tuple[str, ...]] = field(default_factory=dict)


@lru_cache(maxsize=64)
def _gate_tree(url4: str) -> _GateTree:
    """The Gate tree of a Candidate url4; an empty tree when it holds no readable topology."""

    # WHY lazy: the url4 decode imports the compiler, which imports the report views.
    from url4 import build

    from screamingface._evaluation.topology import _topology_from_expression
    from screamingface.url4 import _candidate_expression

    try:
        candidate, _linked = _candidate_expression(build(url4))
        topology = _topology_from_expression(candidate)
    except (ValueError, TypeError):
        return _GateTree()
    return _TreeWalk().tree(topology)


class _TreeWalk:
    def __init__(self) -> None:
        self.children: dict[tuple[str, str], tuple[str, ...]] = {}
        self.next: dict[str, str] = {}

    def tree(self, topology: _RecipeTopology) -> _GateTree:
        roots: list[str] = []
        self.visit(topology, roots)
        targets = set(self.next.values())
        chains = []
        for start in self.next:
            if start in targets:
                continue
            chain = [start]
            while chain[-1] in self.next:
                chain.append(self.next[chain[-1]])
            chains.append(tuple(chain))
        below = {key: tuple(self.below(*key)) for key in self.children}
        return _GateTree(tuple(roots), dict(self.children), tuple(chains), below)

    def below(self, gate: str, branch: str) -> list[str]:
        """Every Gate inside ``branch`` of ``gate``, at any depth, in nesting order."""

        found: list[str] = []
        for child in self.children.get((gate, branch), ()):
            found.append(child)
            for inner in ("then", "otherwise"):
                found.extend(self.below(child, inner))
        return found

    def visit(self, node: _RecipeTopology, sink: list[str]) -> None:
        if node.kind != "gate":
            # WHY lazy: see _gate_tree. A node that is not a Gate has no panel and no branches.
            from screamingface.url4 import _topology_children

            for child in _topology_children(node):
                self.visit(child, sink)
            return
        gate = node.join_binding
        sink.append(gate)
        if node.panel is not None:
            self.visit(node.panel, sink)
        for name, branch in (("then", node.then_branch), ("otherwise", node.otherwise_branch)):
            inside: list[str] = []
            if branch is not None and not isinstance(branch, str):
                self.visit(branch, inside)
                if name == "otherwise" and branch.kind == "gate":
                    self.next[gate] = branch.join_binding
            self.children[(gate, name)] = tuple(inside)


# --- the Case pane --------------------------------------------------------------------------------


def branch_sections_html(candidate: CandidateResult, case: CaseResult) -> str:
    """The Branches block of one Case: one section per Gate that ran, outer first (RP-3)."""

    if case.operations is None:
        return _guard_line(case)
    graph = candidate._operation_graph()
    operations = {operation.operation_id: operation for operation in case.operations}
    gates = [
        operation_id.removeprefix("op_")
        for operation_id, operation in operations.items()
        if operation.decision is not None or _is_gate(graph, operation_id)
    ]
    if not gates:
        return _guard_line(case)
    tree = _gate_tree(candidate.url4)
    pane = _Pane(graph, operations, tree)
    roots = [gate for gate in tree.roots if f"op_{gate}" in operations] or gates
    body = "".join(pane.gate(gate, 0) for gate in roots)
    overspend = "".join(
        _overspend_line(unit, spent, cap) for unit, spent, cap in overspend_of(case)
    )
    return f"<div class='sf-cmb'><div class='sf-detail__k'>Branches</div>{body}{overspend}</div>"


def _guard_line(case: CaseResult) -> str:
    """RP-18: a Case that a guard ended carries no operations (a failed Case keeps none)."""

    if not _fail_closed(case):
        return ""
    return (
        "<div class='sf-cmb'><div class='sf-detail__k'>Branches</div><div class='sf-chips'>"
        "<span class='sf-chip'>a guard ended the Case · fail_closed · no decision record</span>"
        "</div></div>"
    )


def _fail_closed(case: CaseResult) -> bool:
    return any(failure.code == _FAIL_CLOSED for failure in case.failures)


def _is_gate(graph: Mapping[str, OperationInfo], operation_id: str) -> bool:
    node = graph.get(operation_id)
    return node is not None and node.kind == "gate"


@dataclass(frozen=True, slots=True)
class _Pane:
    graph: Mapping[str, OperationInfo]
    operations: Mapping[str, CaseOperation]
    tree: _GateTree

    def gate(self, gate: str, level: int) -> str:
        """One Gate's section, then the sections of the Gates in the branch that ran."""

        operation = self.operations.get(f"op_{gate}")
        if operation is None:
            return ""
        decision = operation.decision
        if decision is None:
            return _box(level, _heading(gate, level, " · decision · " + dash_html(_NO_RECORD)), "")
        inner = ""
        if decision.branch is not None:
            inner = "".join(
                self.gate(child, level + 1)
                for child in self.tree.children.get((gate, decision.branch), ())
            )
        return _box(level, _heading(gate, level, ""), self._chips(gate, decision)) + inner

    def _chips(self, gate: str, decision: GateDecision) -> str:
        return "".join(
            [
                _chips([f"when · {escape(condition_text(decision.when))}", _observed(decision)]),
                _chips(_ran(decision)),
                *(self._not_run(gate, entry) for entry in decision.not_run),
                *(_budget_line(decision, view) for view in decision.budget or ()),
                *(_selector_line(selector) for selector in decision.selectors),
                _chips([_result(decision), *self._panel(decision)]),
            ]
        )

    def _not_run(self, gate: str, entry: GateNotRun) -> str:
        """RP-6 and RP-12: the branch that made zero calls, then the Gates inside it."""

        line = _chips([_not_run_text(entry)])
        reached = "".join(
            _chips([f"gate · {escape(inner)} · not reached"])
            for inner in self.tree.below.get((gate, entry.branch), ())
        )
        return line + reached

    def _panel(self, decision: GateDecision) -> list[str]:
        """RP-14, RP-33: the decision call of a panel gate (its Combine section shows the chip)."""

        panel = decision.panel
        if panel is None:
            return []
        label = _label(self.graph, panel.operation_id)
        operation = self.operations.get(panel.operation_id)
        missing = " · no evidence" if operation is None or operation.combine is None else ""
        return [f"decided by · combine · {escape(label)}{missing}"]


def _box(level: int, heading: str, body: str) -> str:
    indent = min(level, _MAX_INDENT) * _INDENT_PX
    return f"<div class='sf-cmb' style='margin-left:{indent}px'>{heading}{body}</div>"


def _heading(gate: str, level: int, tail: str) -> str:
    depth = f" · level {level + 1}" if level else ""
    return (
        f"<div class='sf-detail__k' title='{escape('op_' + gate)}'>"
        f"gate · {escape(gate)}{depth}{tail}</div>"
    )


def _chips(texts: list[str]) -> str:
    """One chip line; each text is HTML the caller built (data in it is already escaped)."""

    chips = "".join(f"<span class='sf-chip'>{text}</span>" for text in texts if text)
    return f"<div class='sf-chips'>{chips}</div>" if chips else ""


# --- the parts of a section ---------------------------------------------------------------------


def _label_condition(name: str, when: GateWhen) -> str:
    symbol = "==" if when.cmp == "eq" else "!="
    return f"sf.label({name}) {symbol} {when.value!r}"


def _labels_condition(name: str, when: GateWhen) -> str:
    if when.cmp == "empty":
        return f"sf.labels({name}).empty()"
    return f"sf.labels({name}).has({when.value!r})"


def _number_condition(reader: str) -> Callable[[str, GateWhen], str]:
    return lambda name, when: f"{reader.format(name=name)} {when.cmp} {when.value!r}"


_CONDITIONS: Mapping[str, Callable[[str, GateWhen], str]] = {
    "label": _label_condition,
    "labels": _labels_condition,
    "agreement": _number_condition("sf.agreement()"),
    "answered": lambda _name, _when: "sf.answered()",
    "chosen": _number_condition("sf.signal({name!r}).chosen()"),
    "mean": _number_condition("sf.signal({name!r}).mean()"),
    "budget.remaining": _number_condition("sf.budget.remaining({name!r})"),
}


def condition_text(when: GateWhen) -> str:
    """The condition in the source form the author wrote (RP-4); not escaped."""

    form, _, name = when.observe.partition(":")
    render = _CONDITIONS.get(form)
    return when.observe if render is None else render(name, when)


def _observed(decision: GateDecision) -> str:
    """RP-5: the value the condition read, and whether the comparison passed."""

    value = decision.observed
    if value is None:
        shown = dash_html(_NO_LABEL if decision.when.observe.startswith("label") else _NO_NUMBER)
    elif isinstance(value, bool):
        shown = "yes" if value else "no"
    elif isinstance(value, int | float):
        shown = number_html(float(value), _NO_NUMBER)
    elif isinstance(value, tuple):
        shown = escape(", ".join(value)) if value else "none"
    else:
        shown = escape(value)
    verdict = {True: " · passed", False: " · failed", None: ""}[decision.passed]
    return f"observed · {shown}{verdict}"


def _ran(decision: GateDecision) -> list[str]:
    """RP-6, RP-8: the branch that ran; a word that fired a guard says so."""

    if decision.branch is None:
        return ["ran · no branch"]
    texts = [f"ran · {decision.branch}"]
    if decision.result is not None and decision.result.status == _FAIL_CLOSED:
        texts.append("guard fired · fail_closed")
    return texts


def _range_text(low: int, high: int) -> str:
    return f"{low}" if low == high else f"{low}–{high}"


def _not_run_text(entry: GateNotRun) -> str:
    low, high = entry.model_calls_min, entry.model_calls_max
    calls = _range_text(low, high)
    noun = "model call" if high == 1 else "model calls"
    reason = _NOT_RUN_REASONS[entry.reason]
    return f"not run · {entry.branch} · {reason} · avoided {calls} {noun}"


def _budget_line(decision: GateDecision, view: GateBudgetView) -> str:
    """RP-10, RP-11: the spend this decision saw against the cap, per unit (BU-3)."""

    texts = [
        f"budget · {view.unit} · spent {number_html(float(view.spent), _NO_NUMBER)} of "
        f"{number_html(float(view.cap), _NO_NUMBER)}"
    ]
    if view.estimate is not None:
        texts.append(f"estimate {number_html(float(view.estimate), _NO_NUMBER)}")
    if view.refused:
        texts.append(f"refused · {escape(str(decision.wanted))}")
    if view.unpriced:
        noun = "call" if view.unpriced == 1 else "calls"
        texts.append(
            f"<span title='{escape(_UNPRICED)}'>"
            f"{view.unpriced} {noun} with unknown cost counted as $0</span>"
        )
    return _chips(texts)


def overspend_of(case: CaseResult) -> list[tuple[str, float, float]]:
    """RP-34 (BU-19, ans:Q20): ``(unit, spent, cap)`` per unit whose Case spend passed the cap.

    The cap is the one the Case's decisions saw. The spend is the sum of the ``charges`` the
    Engine wrote on each operation: the Budget's own numbers, so a cache hit adds its original
    cost and a replay shows the live run's overspend (ans:Q32). An unpriced call adds nothing,
    as in the Engine fold.
    """

    operations = case.operations or ()
    caps: dict[BudgetUnit, float] = {}
    for decision in (operation.decision for operation in operations):
        for view in () if decision is None else decision.budget or ():
            caps.setdefault(view.unit, float(view.cap))
    charges = [charge for operation in operations for charge in operation.charges or ()]
    spent = {
        unit: sum(amount for charge in charges if (amount := charge.amount(unit)) is not None)
        for unit in caps
    }
    return [(unit, spent[unit], cap) for unit, cap in caps.items() if spent[unit] > cap]


def _overspend_line(unit: str, spent: float, cap: float) -> str:
    return _chips(
        [
            f"budget · overspend · {escape(unit)} · spent {number_html(spent, _NO_NUMBER)} of "
            f"{number_html(cap, _NO_NUMBER)}"
        ]
    )


def _result(decision: GateDecision) -> str:
    """RP-9, RP-19: how the branch ended; a record whose branch did not finish shows a dash."""

    result = decision.result
    if result is None:
        return f"result · {dash_html(_NOT_FINISHED)}"
    if result.status == "abstain":
        return f"result · abstained · {escape(str(result.reason))}"
    return f"result · {escape(result.status)}"


def _selector_line(selector: GateSelector) -> str:
    """RP-7, RP-23, RP-30: kind, id, the input summary and the labels; never the input text."""

    window = (
        f" (first {_KEYWORDS_WINDOW:,} read)"
        if selector.kind == "keywords" and selector.input_chars > _KEYWORDS_WINDOW
        else ""
    )
    head = (
        f"{_SELECTOR_KINDS[selector.kind]} · {escape(selector.id)} · "
        f"input · {selector.input_chars:,} characters{window}"
    )
    return _chips([head, _selector_labels(selector)])


def _selector_labels(selector: GateSelector) -> str:
    if selector.status != "computed":
        return _UNCOMPUTED[selector.status]
    labels = selector.labels or ()
    if selector.parse == "unrecognized":
        raw = escape(short(selector.raw or "", _MAX_RAW))  # RP-23
        kept = f" · {_label_list(labels)}" if labels else ""
        return f'unrecognized · "{raw}"{kept}'
    return _PARSE_WORDS.get(selector.parse or "", "") or _label_list(labels)


_UNCOMPUTED = {
    "not_run": "not run",
    "failed": f"<span title='{escape(_FAILED_SELECTOR)}'>failed · the default branch ran</span>",
}
_PARSE_WORDS = {"no_match": "no match", "unparsed": "unparsed"}


def _label_list(labels: tuple[str, ...]) -> str:
    if len(labels) == 1:
        return f"label · {escape(labels[0])}"
    shown = ", ".join(labels[:_MAX_LABELS])
    if len(labels) <= _MAX_LABELS:
        return f"labels · {escape(shown)}"
    more = len(labels) - _MAX_LABELS
    return f"<span title='{escape(', '.join(labels))}'>labels · {escape(shown)} +{more} more</span>"


# --- the run summary ------------------------------------------------------------------------------


@dataclass(slots=True)
class _GateRow:
    """One Gate over the Cases of one Candidate (RP-15, RP-25)."""

    decided: int = 0
    then: int = 0
    otherwise: int = 0
    none: int = 0
    not_run: int = 0
    avoided_min: int = 0
    avoided_max: int = 0
    refusals: int = 0
    fail_closed: int = 0
    abstain: int = 0
    unrecognized: int = 0
    unparsed: int = 0
    unpriced: int = 0

    def add(self, decision: GateDecision) -> None:
        self.decided += 1
        self.unpriced += any(view.unpriced for view in decision.budget or ())
        if decision.branch == "then":
            self.then += 1
        elif decision.branch == "otherwise":
            self.otherwise += 1
        else:
            self.none += 1
        for entry in decision.not_run:
            self.not_run += 1
            self.avoided_min += entry.model_calls_min
            self.avoided_max += entry.model_calls_max
            self.refusals += entry.reason == "budget_refused"
        status = None if decision.result is None else decision.result.status
        self.fail_closed += status == _FAIL_CLOSED
        self.abstain += status == "abstain"
        self.unrecognized += sum(item.parse == "unrecognized" for item in decision.selectors)
        self.unparsed += sum(item.parse == "unparsed" for item in decision.selectors)


@dataclass(slots=True)
class GateSummary:
    """The Gate summary of one Candidate, fed one Case at a time in the card's one pass (RP-24)."""

    gates: dict[str, _GateRow] = field(default_factory=dict)
    fail_closed: int = 0
    overspend: int = 0
    branches: list[dict[str, str | None]] = field(default_factory=list)

    def add(self, case: CaseResult) -> None:
        """Count each Gate decision of this Case; a fail_closed Case counts from its code."""

        self.fail_closed += _fail_closed(case)
        self.overspend += bool(overspend_of(case))
        taken: dict[str, str | None] = {}
        for operation in case.operations or ():
            decision = operation.decision
            if decision is not None:
                row = self.gates.setdefault(decision.gate_id, _GateRow())
                row.add(decision)
                taken[decision.gate_id] = decision.branch
        if taken:
            self.branches.append(taken)

    def html(self, candidate: CandidateResult) -> str:
        """The gates block: one line per Gate, then one ladder line per chain; empty with none."""

        if not self.gates:
            return ""
        rows = "".join(_row_html(gate, row) for gate, row in self.gates.items())
        ladders = "".join(self._ladder(chain) for chain in _gate_tree(str(candidate.url4)).chains)
        noun = "case" if self.overspend == 1 else "cases"
        over = _chips([f"budget · overspend · {self.overspend} {noun}"]) if self.overspend else ""
        return (
            f"<div class='sf-detail__k'>gates</div><div class='sf-cmb'>{rows}{ladders}{over}</div>"
        )

    def _ladder(self, chain: tuple[str, ...]) -> str:
        """RP-16, RP-26, RP-27: the share of the chain's Cases that each Gate's then resolved."""

        started = [taken for taken in self.branches if taken.get(chain[0]) is not None]
        if len(chain) < 2 or not started:
            return ""
        ended = dict.fromkeys(chain, 0)
        last_otherwise = 0
        for taken in started:
            for gate in chain:
                branch = taken.get(gate)
                if branch == "then":
                    ended[gate] += 1
                if branch != "otherwise":
                    break
            else:
                last_otherwise += 1
        total = len(started)
        parts = [
            _share("resolved at the first branch" if index == 0 else escape(gate), count, total)
            for index, (gate, count) in enumerate(ended.items())
        ]
        parts.append(_share("last otherwise", last_otherwise, total))
        return _chips([f"ladder · {' · '.join(parts)}"])


def _share(name: str, count: int, total: int) -> str:
    noun = "case" if total == 1 else "cases"
    return f"<span title='{count} of {total} {noun}'>{name} {100 * count / total:.1f}%</span>"


def _row_html(gate: str, row: _GateRow) -> str:
    noun = "case" if row.decided == 1 else "cases"
    avoided = _range_text(row.avoided_min, row.avoided_max)
    texts = [
        f"gate · {escape(gate)} · {row.decided} {noun}",
        f"then {row.then} · otherwise {row.otherwise} · none {row.none}",
        f"bodies not run {row.not_run} · avoided {avoided} model calls",
        f"abstained {row.abstain} · fail_closed {row.fail_closed}",
    ]
    extras = {
        "refused by the budget": row.refusals,
        "unrecognized": row.unrecognized,
        "unparsed": row.unparsed,
        "unknown cost": row.unpriced,
    }
    texts.extend(f"{name} {count}" for name, count in extras.items() if count)
    return _chips(texts)


__all__ = ["GateSummary", "branch_sections_html", "condition_text", "overspend_of"]
