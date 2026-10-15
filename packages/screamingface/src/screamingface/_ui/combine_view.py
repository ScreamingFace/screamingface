"""The Combine views of the report (E4b part 4): the Case pane section and the run summary.

INVARIANT: every text from data goes through html.escape; a float shows 4 significant digits and
its exact stored value as the title (ans:Q3); a missing value is an em dash with its reason.
"""

from __future__ import annotations

from collections.abc import Mapping
from html import escape
from typing import TYPE_CHECKING

from screamingface._case_views import case_trace

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
    # WHY not report_view._short: report_view imports this module (an import cycle).
    shown = value if len(value) <= _TEXT_CELL else value[:_TEXT_CELL] + "…"
    return escape(shown)


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
    reduces = {
        entry.data["operation_id"]: entry.data
        for entry in case_trace(case, graph)
        if entry.kind == "reduce"
    }
    return "".join(
        _section(op.operation_id, op.combine, reduces.get(op.operation_id), graph)
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
    reduce: Mapping[str, object] | None,
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
        f"<div class='sf-chips'>{_chips(evidence, reduce)}</div>"
        f"{_table(head, rows)}{_tally_html(evidence)}</div>"
    )


def _chips(evidence: CombineEvidence, reduce: Mapping[str, object] | None) -> str:
    """The step facts F1-F10 (erd §4), in order; each chip text is escaped."""
    chips = [
        escape(f"reducer · {evidence.reducer}"),
        escape("rule · " + " → ".join(evidence.operators)),
        _result_chip(evidence.result),
        ""
        if evidence.cut is None
        else escape(f"cut · top {evidence.cut.k} · {evidence.cut.order}"),
        "" if evidence.signal is None else _reads_chip(evidence.signal),
        _judge_chip(reduce),
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


def _judge_chip(reduce: Mapping[str, object] | None) -> str:
    """F6: the judge model from the trace reduce entry (P12); no judge link gives no chip."""
    if reduce is None or reduce["judge_operation_id"] is None:
        return ""
    model = reduce["judge_model"]
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


__all__: list[str] = []
