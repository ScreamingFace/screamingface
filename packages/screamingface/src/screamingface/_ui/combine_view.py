"""The Combine views of the report (E4b part 4): the Case pane section and the run summary.

INVARIANT: every text from data goes through html.escape; a float shows 4 significant digits and
its exact stored value as the title (ans:Q3); a missing value is an em dash with its reason.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass, field
from fractions import Fraction
from html import escape
from typing import TYPE_CHECKING

from screamingface._case_views import judge_link
from screamingface._ui.text import short

if TYPE_CHECKING:
    from screamingface.case_result import CaseResult
    from screamingface.combine_evidence import (
        CombineAnswerRow,
        CombineEvidence,
        CombineResult,
        CombineSignal,
    )
    from screamingface.operation import OperationInfo
    from screamingface.report import CandidateResult

_DASH = "—"
_TEXT_CELL = 80  # characters of a member value shown in one cell (P7)
_NUMBER_COLUMNS = ("weight", "score", "rank")  # C4-C6: shown when any row has the value (P11)
_NO_EVIDENCE = "no combine evidence recorded for this step"
_NO_JUDGE_MODEL = "no model recorded for the judge call"

# WHY one "<style>…</style>" constant: the house precedent (accounting_view.STYLE, joined into
# report_view._STYLE). WHY text-align on th AND td, and the tbody tr background: JupyterLab's
# rendered-HTML rules right-align table cells and paint zebra rows; the zebra rule has a higher
# specificity, so it needs !important (house precedent: report_browser.py:44). Same intent as
# .sf-eval__table (evaluation_view.py:41,47).
STYLE = """<style>
.sf-cmb{margin-top:6px;overflow-x:auto}
.sf-cmb__t{width:100%;border-collapse:collapse;margin-top:6px;font-size:12px;
  font-variant-numeric:tabular-nums}
.sf-cmb__t th{font-family:"IBM Plex Mono",ui-monospace,monospace;font-size:11px;font-weight:600;
  text-align:left;color:var(--sf-ink-2);padding:4px 8px;border-bottom:1px solid var(--sf-line-2)}
.sf-cmb__t td{padding:4px 8px;text-align:left;border-bottom:1px solid var(--sf-line);
  color:var(--sf-ink);overflow-wrap:anywhere}
.sf-cmb__t tbody tr{background:transparent!important}
.sf-cmb__out td{color:var(--sf-ink-3)}
.sf-cmb__na,.sf-cmb__nn{color:var(--sf-ink-3)}
.sf-cmb__na,.sf-cmb__n{cursor:help}
.sf-cmb__h{font-size:13px;font-weight:600;margin-top:10px}
.sf-cmb__nn{font-size:11px}
</style>"""


def number_html(value: float | None, reason: str) -> str:
    """A float at 4 significant digits, the exact stored value as its title; None: a dash."""
    if value is None:
        return dash_html(reason)
    return (
        f"<span class='sf-cmb__n' title='{escape(repr(value))}'>"
        f"{escape(format(value, '.4g'))}</span>"
    )


def dash_html(reason: str) -> str:
    """The missing-value mark: an em dash whose title is the reason (ans:Q3)."""
    return f"<span class='sf-cmb__na' title='{escape(reason)}'>{_DASH}</span>"


def text_html(value: str | None, reason: str) -> str:
    """A member value: escaped, at most 80 characters then an ellipsis; None: a dash."""
    if value is None:
        return dash_html(reason)
    return escape(short(value, _TEXT_CELL))


def missing_reason(row: CombineAnswerRow, label: str) -> str:
    """Why a cell of this member row is empty (MR-1..MR-3, P6)."""
    if row.status == "fail":
        return f"member failed: {row.reason}"
    if row.status == "excluded":
        return f"left out by the rule: {row.reason}"
    return f"no {label} recorded"


# --- the Case pane: one Combine section per combine step (E4b part 4 unit 3) --------------------


def combine_sections_html(candidate: CandidateResult, case: CaseResult) -> str:
    """One Combine section per combine step of the Case, in operation order (ans:Q2, P19)."""
    if case.operations is None:
        return ""
    graph = {info.id: info for info in candidate.operations}
    steps = [
        op
        for op in case.operations
        if op.combine is not None or _is_combine(graph, op.operation_id)
    ]
    if not steps:
        return ""
    # WHY judge_link and not case_trace: the chip reads only the judge id and model of each step,
    # so the full trace (every extract and model call entry) is not built (Review P4 #4).
    links = {
        op.operation_id: judge_link(op.operation_id, op.combine, graph, case.operations)
        for op in case.operations
        if op.combine is not None
    }
    return "".join(
        _section(op.operation_id, op.combine, links[op.operation_id], graph)
        if op.combine is not None
        else _no_evidence_section(op.operation_id, graph)
        for op in steps
    )


def _is_combine(graph: Mapping[str, OperationInfo], operation_id: str) -> bool:
    """The graph node of this operation is a combine step (a step may have no evidence, P19)."""
    node = graph.get(operation_id)
    return node is not None and node.kind == "combine"


def _label(graph: Mapping[str, OperationInfo], operation_id: str) -> str:
    """The operation label in the Candidate graph, else the id. Not escaped: the caller escapes."""
    node = graph.get(operation_id)
    return operation_id if node is None else node.label


def _table(head: str, rows: str) -> str:
    """One Combine table. ``head`` is the header cells, ``rows`` the ``<tr>`` rows (both HTML)."""
    return f"<table class='sf-cmb__t'><thead><tr>{head}</tr></thead><tbody>{rows}</tbody></table>"


def _heading(graph: Mapping[str, OperationInfo], operation_id: str) -> str:
    """The section heading: ``combine · {label}``, the operation id as its title."""
    return (
        f"<div class='sf-detail__k' title='{escape(operation_id)}'>"
        f"combine · {escape(_label(graph, operation_id))}</div>"
    )


def _no_evidence_section(operation_id: str, graph: Mapping[str, OperationInfo]) -> str:
    """A combine step with no evidence: the heading and one ``evidence · —`` chip (P19)."""
    return (
        f"<div class='sf-cmb'>{_heading(graph, operation_id)}<div class='sf-chips'>"
        f"<span class='sf-chip'>evidence · {dash_html(_NO_EVIDENCE)}</span></div></div>"
    )


def _section(
    operation_id: str,
    evidence: CombineEvidence,
    link: Mapping[str, str | None],
    graph: Mapping[str, OperationInfo],
) -> str:
    """One Combine section: the heading, the step chips, the member table, the tally table."""
    columns = tuple(
        name
        for name in _NUMBER_COLUMNS
        if any(getattr(row, name) is not None for row in evidence.members)
    )
    keys = tuple(dict.fromkeys(key for row in evidence.members for key in row.signals))
    head = (
        "".join(f"<th scope='col'>{name}</th>" for name in ("member", "status", "value", *columns))
        + "".join(_signal_head(evidence, key) for key in keys)
        + "<th scope='col'>chosen</th>"
    )
    rows = "".join(_member_row(row, evidence, columns, keys) for row in evidence.members)
    return (
        f"<div class='sf-cmb'>{_heading(graph, operation_id)}"
        f"<div class='sf-chips'>{_chips(evidence, link)}</div>"
        f"{_table(head, rows)}{_tally_html(evidence)}</div>"
    )


def _chips(evidence: CombineEvidence, link: Mapping[str, str | None]) -> str:
    """The step facts F1-F10 (erd §4), in order; each chip text is escaped."""
    chips = [
        escape(f"reducer · {evidence.reducer}"),
        escape("rule · " + " → ".join(evidence.operators)),
        _result_chip(evidence.result),
        ""
        if evidence.cut is None
        else escape(f"cut · top {evidence.cut.k} · {evidence.cut.order}"),
        "" if evidence.signal is None else _reads_chip(evidence.signal),
        _judge_chip(link),
        "" if evidence.agreement is None else "agreement · " + number_html(evidence.agreement, ""),
        "tie · yes" if evidence.tie else "tie · no",
        f"dropped · {evidence.dropped}",
        "" if evidence.median is None else "median · " + text_html(evidence.median, ""),
        "" if evidence.mean is None else "mean · " + text_html(evidence.mean, ""),
    ]
    return "".join(f"<span class='sf-chip'>{chip}</span>" for chip in chips if chip)


def _result_chip(result: CombineResult) -> str:
    """F3: the member the step answered with, ``built``, or the abstain reason."""
    if result.status == "abstain":
        return escape(f"abstain · {result.reason}")
    return escape(f"answered · {'built' if result.member_id is None else result.member_id}")


def _reads_chip(signal: CombineSignal) -> str:
    """F5: the signal the rule reads, and its order when it has one."""
    order = "" if signal.order is None else f" · {signal.order}"
    return escape(f"reads · {signal.key}{order}")


def _judge_chip(link: Mapping[str, str | None]) -> str:
    """F6: the judge model of the step's judge link, as the trace shows it (P12); none: no chip."""
    if link["judge_operation_id"] is None:
        return ""
    model = link["judge_model"]
    if model is None:
        return "judge · " + dash_html(_NO_JUDGE_MODEL)
    return escape(f"judge · {model}")


def _signal_head(evidence: CombineEvidence, key: str) -> str:
    """C7: one signal header cell; the title names the declared source and the rule read."""
    notes: list[str] = []
    if evidence.declared is not None and key in evidence.declared:
        notes.append(f"source: {evidence.declared[key]['source']}")
    if evidence.signal is not None and evidence.signal.key == key:
        notes.append("read by the rule")
    title = "; ".join(notes)
    title_attr = f" title='{escape(title)}'" if title else ""
    return f"<th scope='col'{title_attr}>{escape(key)}</th>"


def _member_row(
    row: CombineAnswerRow,
    evidence: CombineEvidence,
    columns: tuple[str, ...],
    keys: tuple[str, ...],
) -> str:
    """C1-C8: one member row; a failed or excluded member gets the ``sf-cmb__out`` class."""
    opening = "<tr>" if row.status == "answered" else "<tr class='sf-cmb__out'>"
    status = "answered" if row.status == "answered" else f"{row.status} · {row.reason}"
    numbers = "".join(f"<td>{_number_cell(row, column)}</td>" for column in columns)
    signals = "".join(
        f"<td>{number_html(row.signals.get(key), missing_reason(row, key))}</td>" for key in keys
    )
    chosen = "&check;" if row.member_id in evidence.chosen else ""
    return (
        f"{opening}<td>{escape(row.member_id)}</td><td>{escape(status)}</td>"
        f"<td>{text_html(row.value, missing_reason(row, 'value'))}</td>"
        f"{numbers}{signals}<td>{chosen}</td></tr>"
    )


def _number_cell(row: CombineAnswerRow, column: str) -> str:
    """C4-C6: the weight or score (4 digits), or the rank (an integer, no title)."""
    if column == "rank":
        return dash_html(missing_reason(row, "rank")) if row.rank is None else str(row.rank)
    value = row.weight if column == "weight" else row.score
    return number_html(value, missing_reason(row, column))


def _tally_html(evidence: CombineEvidence) -> str:
    """The tally table of a vote; absent when the step has no tally."""
    if evidence.tally is None:
        return ""
    head = "<th scope='col'>tally value</th><th scope='col'>score</th><th scope='col'>holders</th>"
    rows = "".join(
        f"<tr><td>{text_html(row.value, '')}</td><td>{number_html(row.score, '')}</td>"
        f"<td>{escape(', '.join(row.holders))}</td></tr>"
        for row in evidence.tally
    )
    return _table(head, rows)


def combine_summary_html(candidate: CandidateResult) -> str:
    """Per reducer step: chosen and excluded counts, and declared-signal means (ans:Q1, P13).

    Its own pass over the Cases. The Candidate card does not call it: the card feeds a
    ``CombineSummary`` from the one pass that also counts the abstained Cases (Review P4 #2).
    """
    summary = CombineSummary()
    for case in candidate.cases:
        summary.add(case)
    return summary.html(candidate)


@dataclass(slots=True)
class CombineSummary:
    """The run summary of one Candidate, fed one Case at a time. Dicts keep first-seen order.

    WHY fed and not a pass of its own: a saved Candidate decodes a Case on each read (DiskCases),
    so the card reads the Cases once for this summary and the abstained count (Review P4 #2).
    """

    steps: dict[str, _StepSummary] = field(default_factory=dict)

    def add(self, case: CaseResult) -> None:
        """Count each combine step of this Case that has evidence.

        A step is in the summary only when a Case has its evidence, so a combine step with no
        evidence (P19) and the steps of an Attempt (P15) are not counted.
        """
        for operation in case.operations or ():
            if operation.combine is not None:
                self.steps.setdefault(
                    operation.operation_id, _StepSummary(operation.combine.reducer)
                ).add(operation.combine)

    def html(self, candidate: CandidateResult) -> str:
        """The summary block, one table per step; empty when no Case has combine evidence."""
        if not self.steps:
            return ""
        graph = {info.id: info for info in candidate.operations}
        blocks = "".join(
            _summary_html(operation_id, step, graph) for operation_id, step in self.steps.items()
        )
        return f"<div class='sf-detail__k'>combine</div><div class='sf-cmb'>{blocks}</div>"


@dataclass(slots=True)
class _StepSummary:
    """One combine step over the Cases of one Candidate (erd §5). Dicts keep first-seen order."""

    reducer: str
    cases: int = 0
    chosen: dict[str, int] = field(default_factory=dict)
    excluded: dict[str, int] = field(default_factory=dict)
    declared: dict[str, str] = field(default_factory=dict)
    values: dict[tuple[str, str], list[float]] = field(default_factory=dict)

    def add(self, evidence: CombineEvidence) -> None:
        """Count one Case of this step: chosen, excluded, the declared names and their values."""
        self.cases += 1
        for name, entry in (evidence.declared or {}).items():
            self.declared.setdefault(name, str(entry["source"]))
        for row in evidence.members:
            self.chosen.setdefault(row.member_id, 0)
            self.excluded.setdefault(row.member_id, 0)
            if row.member_id in evidence.chosen:
                self.chosen[row.member_id] += 1
            if row.status == "excluded":
                self.excluded[row.member_id] += 1
            # WHY only the names this Case declares (E6): the summary shows a mean for a declared
            # name alone, and a Case also holds accounting keys, score:judge and field:* values. A
            # value counts when its own Case declares the name, so the Case order does not matter.
            for name in evidence.declared or ():
                value = row.signals.get(name)
                if value is not None:
                    self.values.setdefault((row.member_id, name), []).append(value)


def _summary_html(operation_id: str, step: _StepSummary, graph: Mapping[str, OperationInfo]) -> str:
    """One step of the run summary: the heading, then one row per member (P13)."""
    total = step.cases
    noun = "case" if total == 1 else "cases"
    heading = (
        f"<div class='sf-cmb__h' title='{escape(operation_id)}'>"
        f"{escape(_label(graph, operation_id))} · {escape(step.reducer)} · {total} {noun}</div>"
    )
    head = "<th scope='col'>member</th><th scope='col'>chosen</th><th scope='col'>excluded</th>"
    head += "".join(
        f"<th scope='col' title='{escape('source: ' + source)}'>{escape(name)} mean</th>"
        for name, source in step.declared.items()
    )
    rows = "".join(_summary_row(member_id, step) for member_id in step.chosen)
    return heading + _table(head, rows)


def _summary_row(member_id: str, step: _StepSummary) -> str:
    """One member row: chosen and excluded as `{count} of {N}`, then one mean cell per name."""
    total = step.cases
    means = "".join(_mean_cell(step.values.get((member_id, name), [])) for name in step.declared)
    return (
        f"<tr><td>{escape(member_id)}</td><td>{step.chosen[member_id]} of {total}</td>"
        f"<td>{step.excluded[member_id]} of {total}</td>{means}</tr>"
    )


def _mean_cell(values: list[float]) -> str:
    """The mean of one member's values of one declared name, and their count n (P13, ans:Q3)."""
    return (
        f"<td>{number_html(_mean(values), 'no Case gave a value')}"
        f" <span class='sf-cmb__nn'>n={len(values)}</span></td>"
    )


def _mean(values: list[float]) -> float | None:
    """``math.fsum`` of ``values`` over their count; None when there are none (P13)."""
    if not values:
        return None
    try:
        return math.fsum(values) / len(values)
    except OverflowError:
        # WHY Fraction: the sum of finite values can leave the float range, but their mean cannot;
        # the exact rational mean rounds to a finite float (the engine gate _mean, E4b part 5).
        return float(sum(map(Fraction, values), Fraction(0)) / len(values))


__all__: list[str] = []
