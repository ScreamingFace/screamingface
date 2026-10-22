"""The bundle page's Telemetry section as HTML (unit 6 plan, Task 5).

Four views over ``telemetry.Telemetry``: a span waterfall (inline SVG bars, grouped by service),
usage and cost by model and by stage, a log list with a severity filter, and the cases table.

INVARIANT: every dynamic value goes through ``_e`` (``html.escape``); ``None`` renders as
"unknown", never 0. No script: the severity filter is CSS ``:has`` over radio inputs, and where
``:has`` is unsupported every row simply shows. No external asset (CSP ``default-src 'none'``).

Readable at 1 000+ spans (Review Focus 5): same-named siblings fold (``telemetry.waterfall``)
and the rows are paginated server side (``WATERFALL_PAGE`` per page, plain links). The log and
case tables show at most ``TABLE_CAP`` rows and say how many more the files hold.
"""

from __future__ import annotations

import html
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Final
from urllib.parse import quote, urlencode

from workbench.ui import telemetry as tm

WATERFALL_PAGE: Final = 200
TABLE_CAP: Final = 2_000
_AXIS: Final = 1000  # SVG viewBox width of a bar's track
_MAX_INDENT: Final = 24

# Hide every severity below the chosen one; an unknown severity always shows (fail open).
_FILTERS: Final = (("all", None), ("info", 1), ("warn", 2), ("error", 3))
STYLE: Final = (
    ".wf td{padding:2px 8px;white-space:nowrap}.wf td.name{white-space:normal;"
    "word-break:break-all;min-width:16em}.wf tr.wf-svc th{padding-top:10px;font-size:13px;"
    "color:var(--fg)}.wf td.track{width:30%;min-width:160px}"
    ".wf svg{display:block;width:100%;height:10px}.bar{fill:var(--link)}"
    ".bar.err{fill:var(--fail)}.bar.fold{fill:var(--muted)}.num{text-align:right}"
    "nav.pages a,nav.pages span{margin-right:12px}"
    + "".join(
        f'#tlogs:has(#sev-{name}:checked) tr[data-sev="{sev}"]{{display:none}}'
        for name, level in _FILTERS
        if level is not None
        for sev in tm.SEVERITIES[:level]
    )
)


@dataclass(frozen=True)
class TelemetryView:
    """What the bundle page's query asks of the waterfall."""

    spans_page: int = 1
    unfold: bool = False


def _e(value: object) -> str:
    return html.escape(str(value), quote=True)


def _v(value: object) -> str:
    """A scalar cell: escaped, or "unknown" for ``None`` (never 0, never "None")."""
    return "unknown" if value is None else _e(value)


def _usd(amount: Decimal | None) -> str:
    return "unknown" if amount is None else _e(f"${amount}")


def _duration(ns: int | None) -> str:
    if ns is None:
        return "unknown"
    ms = ns / 1e6
    return f"{ms / 1000:.2f} s" if ms >= 1000 else f"{ms:.1f} ms"


def _table(head: Sequence[str], rows: Sequence[str], cls: str = "") -> str:
    th = "".join(f"<th>{h}</th>" for h in head)
    css = f' class="{cls}"' if cls else ""
    return f"<table{css}><thead><tr>{th}</tr></thead><tbody>{''.join(rows)}</tbody></table>"


# --- summary --------------------------------------------------------------------------------


def _counts(t: tm.Telemetry) -> str:
    d = t.dropped
    facts = [f"{len(t.events)} events", f"{len(t.spans)} spans"]
    pairs = (
        (d.events, "events dropped by the recorder's cap"),
        (d.events_failed, "events the recorder failed to write"),
        (d.spans, "spans dropped by the bundle's cap"),
        (d.unreadable, "unreadable lines skipped"),
        (d.over_cap, "lines beyond the page's read cap"),
    )
    facts += [f"{n} {_e(what)}" for n, what in pairs if n]
    if d.events is None and d.spans is None:
        facts.append("drop counts unknown (no readable telemetry.json)")
    return f"<p class='note'>{' · '.join(facts)}</p>"


def _notes(t: tm.Telemetry) -> str:
    if not t.notes:
        return ""
    return "<ul class='warn'>" + "".join(f"<li>{_e(n)}</li>" for n in t.notes) + "</ul>"


# --- waterfall ------------------------------------------------------------------------------


def _bar(row: tm.SpanRow, axis: tuple[int, int] | None) -> str:
    if axis is None or row.start_ns is None or row.end_ns is None:
        return "<span class='muted'>unknown</span>"
    origin, width = axis
    x = (row.start_ns - origin) * _AXIS / width
    w = max(2.0, (row.end_ns - row.start_ns) * _AXIS / width)
    css = "bar fold" if row.folded > 1 else "bar err" if row.error else "bar"
    label = f"{row.name} · {_duration(row.duration_ns)}"
    return (
        f'<svg viewBox="0 0 {_AXIS} 10" preserveAspectRatio="none" role="img" '
        f'aria-label="{_e(label)}"><rect class="{css}" x="{x:.2f}" y="1" width="{w:.2f}" '
        f'height="8"><title>{_e(label)}</title></rect></svg>'
    )


def _name(row: tm.SpanRow) -> str:
    if row.folded == 1:
        return _e(row.name)
    hidden = f", hiding {row.hidden} descendants" if row.hidden else ""
    return (
        f"<b>+{row.folded} more</b> “{_e(row.name)}” spans "
        f"<span class='note'>(folded{hidden})</span>"
    )


def _status(row: tm.SpanRow) -> str:
    if row.error is None:
        return "<span class='muted'>—</span>"
    return f'<span class="pill fail">error</span> {_e(row.error)}'


def _span_row(row: tm.SpanRow, axis: tuple[int, int] | None) -> str:
    indent = 8 + 14 * min(row.depth, _MAX_INDENT)
    return (
        f'<tr class="wf-row" data-folded="{row.folded}">'
        f'<td class="name" style="padding-left:{indent}px">{_name(row)}</td>'
        f"<td>{_v(row.model)}</td><td class='num'>{_v(row.input_tokens)}</td>"
        f"<td class='num'>{_v(row.output_tokens)}</td><td>{_v(row.cache)}</td>"
        f"<td class='num'>{_duration(row.duration_ns)}</td><td>{_status(row)}</td>"
        f'<td class="track">{_bar(row, axis)}</td></tr>'
    )


def _waterfall_rows(rows: Sequence[tm.SpanRow], axis: tuple[int, int] | None) -> list[str]:
    out: list[str] = []
    service = None
    for row in rows:
        if row.service != service:
            service = row.service
            out.append(f'<tr class="wf-svc"><th colspan="8"><b>{_e(service)}</b></th></tr>')
        out.append(_span_row(row, axis))
    return out


def _link(key: str, token: str | None, **params: object) -> str:
    query = {k: v for k, v in params.items() if v} | ({"token": token} if token else {})
    return f"/bundles/{quote(key)}?{urlencode(query)}#waterfall"


def _pager(key: str, token: str | None, view: TelemetryView, page: int, pages: int) -> str:
    unfold = 1 if view.unfold else None
    parts = [f"<span>page {page} of {pages}</span>"]
    if page > 1:
        href = _link(key, token, spans_page=page - 1, unfold=unfold)
        parts.append(f'<a href="{_e(href)}">previous</a>')
    if page < pages:
        href = _link(key, token, spans_page=page + 1, unfold=unfold)
        parts.append(f'<a href="{_e(href)}">next</a>')
    toggle = _link(key, token, unfold=None if view.unfold else 1)
    word = "fold repeated siblings" if view.unfold else "show every span (unfold)"
    parts.append(f'<a href="{_e(toggle)}">{word}</a>')
    return f"<nav class='pages note'>{''.join(parts)}</nav>"


def _waterfall(t: tm.Telemetry, view: TelemetryView, key: str, token: str | None) -> str:
    if not t.spans:
        return "<p class='muted'>No spans in this bundle.</p>"
    w = tm.waterfall(t.spans, unfold=view.unfold)
    shown, page, pages = tm.page_of(w.rows, view.spans_page, WATERFALL_PAGE)
    axis = None
    if w.start_ns is not None and w.end_ns is not None:
        axis = (w.start_ns, max(1, w.end_ns - w.start_ns))
    head = ("Span", "Model", "In tok", "Out tok", "Cache", "Duration", "Error", "Timeline")
    pager = _pager(key, token, view, page, pages)
    total = _duration(None if axis is None else axis[1])
    return (
        f"<p class='note'>{len(t.spans)} spans in {len(w.rows)} rows · timeline {total}</p>"
        f"{pager}{_table(head, _waterfall_rows(shown, axis), 'wf')}{pager}"
    )


# --- usage and cost -------------------------------------------------------------------------


def _usage_events(t: tm.Telemetry) -> str:
    rows = tm.usage_by_model(t.events)
    if not rows:
        return "<p class='muted'>No usage events.</p>"
    body = [
        f"<tr><td>{_e(r.model)}</td><td class='num'>{r.calls}</td>"
        f"<td class='num'>{_v(r.input_tokens)}</td><td class='num'>{_v(r.output_tokens)}</td>"
        f"<td class='num'>{_usd(r.cost_usd)}</td></tr>"
        for r in rows
    ]
    total = tm.money_sum(r.cost_usd for r in rows)
    body.append(f"<tr><th colspan='4'>Total</th><th class='num'>{_usd(total)}</th></tr>")
    head = ("Model", "Calls", "In tok", "Out tok", "Cost (USD)")
    return _table(head, body)


def _cache(value: object) -> str:
    if not isinstance(value, dict):
        return "unknown"
    c: Mapping[str, Any] = value  # pyright: ignore[reportUnknownVariableType]
    return " · ".join(f"{_v(c.get(k))} {k}" for k in ("hits", "misses", "bypasses", "unknown"))


def _summary_row(label: str, summary: Mapping[str, Any]) -> str:
    usage = summary.get("usage")
    u: Mapping[str, Any] = usage if isinstance(usage, dict) else {}  # pyright: ignore[reportUnknownVariableType]
    calls = summary.get("calls")
    return (
        f"<tr><td>{label}</td><td class='num'>{_v(calls if isinstance(calls, int) else None)}"
        f"</td><td class='num'>{_v(tm.int_or_none(u.get('input_tokens')))}</td>"
        f"<td class='num'>{_v(tm.int_or_none(u.get('output_tokens')))}</td>"
        f"<td>{_cache(summary.get('cache'))}</td>"
        f"<td class='num'>{_usd(tm.money(u.get('cost_usd')))}</td></tr>"
    )


def _breakdown(rows: object, key: str, head: str) -> str:
    items = tm.dicts(rows)
    if not items:
        return f"<p class='muted'>No {key} rows.</p>"
    body = [_summary_row("(anonymous)" if r.get(key) is None else _e(r.get(key)), r) for r in items]
    return _table((head, "Calls", "In tok", "Out tok", "Cache", "Cost (USD)"), body)


def _yes_no(value: object) -> str:
    return "unknown" if not isinstance(value, bool) else "yes" if value else "no"


def _candidate_accounting(c: Mapping[str, Any]) -> str:
    unattributed = _usd(tm.money(c.get("unattributed_cost_usd")))
    return (
        f"<h4><b>{_v(c.get('name'))}</b></h4><p class='note'>unattributed cost: "
        f"{unattributed} · consistent: {_yes_no(c.get('consistent'))}</p>"
        f"{_breakdown(c.get('by_model'), 'model', 'Model')}"
        f"{_breakdown(c.get('by_stage'), 'stage', 'Stage')}"
    )


def _accounting(t: tm.Telemetry) -> str:
    items = tm.dicts((t.accounting or {}).get("candidates"))
    if not items:
        return "<p class='muted'>No report accounting (accounting.json).</p>"
    return "".join(_candidate_accounting(c) for c in items)


# --- logs and cases -------------------------------------------------------------------------


def _filter(entries: Sequence[tm.LogEntry]) -> str:
    counts = {s: sum(e.severity == s for e in entries) for s in tm.SEVERITIES}
    radios = []
    for name, _level in _FILTERS:
        checked = " checked" if name == "all" else ""
        label = "all" if name == "all" else f"{name.upper()} and above"
        radios.append(
            f'<label><input type="radio" name="sev" id="sev-{name}"{checked}> {label}</label>'
        )
    tally = " · ".join(f"{n} {s}" for s, n in counts.items())
    return (
        f"<fieldset><legend>Severity</legend>{''.join(radios)} "
        f"<span class='note'>{tally}</span></fieldset>"
    )


def _logs(t: tm.Telemetry) -> str:
    entries = tm.log_entries(t.events)
    if not entries:
        return "<p class='muted'>No log events.</p>"
    rows = [
        f'<tr data-sev="{_e(e.severity)}"><td class="mono">{_v(e.sequence)}</td>'
        f"<td class='mono'>{_e(e.timestamp)}</td><td>{_e(e.severity)}</td>"
        f"<td>{_e(e.body)}</td><td class='mono'>"
        + " ".join(f"{_e(k)}={_e(v)}" for k, v in e.attributes.items())
        + "</td></tr>"
        for e in entries[:TABLE_CAP]
    ]
    more = (
        f"<p class='note'>Showing the first {TABLE_CAP} of {len(entries)} log entries; the rest "
        "are in events.jsonl.</p>"
        if len(entries) > TABLE_CAP
        else ""
    )
    table = _table(("#", "Time", "Severity", "Message", "Attributes"), rows)
    return f'<div id="tlogs">{_filter(entries)}{more}{table}</div>'


def _cases(t: tm.Telemetry) -> str:
    rows = tm.cases(t.report)
    if not rows:
        return "<p class='muted'>No cases in report.json.</p>"
    body = [
        f"<tr><td>{_e(c.candidate)}</td><td>{_e(c.case_id)}</td><td>{_v(c.status)}</td>"
        f"<td class='num'>{_v(c.score)}</td><td>{_v(c.stop_reason)}</td>"
        f"<td>{_v(c.finish_reason)}</td><td class='num'>{_v(c.rounds)}</td>"
        f"<td class='num'>{_v(c.failures)}</td></tr>"
        for c in rows[:TABLE_CAP]
    ]
    more = (
        f"<p class='note'>Showing the first {TABLE_CAP} of {len(rows)} cases.</p>"
        if len(rows) > TABLE_CAP
        else ""
    )
    head = ("Candidate", "Case", "Status", "Score", "Stop reason", "Finish", "Rounds", "Failures")
    return more + _table(head, body)


def section(t: tm.Telemetry, view: TelemetryView, *, key: str, token: str | None) -> str:
    """The whole Telemetry ``<section>`` of the bundle page."""
    if not t.present:
        body = "<p class='muted'>No telemetry in this bundle (no events, spans or report).</p>"
        return f'<section id="telemetry"><h2>Telemetry</h2>{body}</section>'
    return (
        f'<section id="telemetry"><h2>Telemetry</h2>{_counts(t)}{_notes(t)}'
        f'<h3 id="waterfall">Spans</h3>{_waterfall(t, view, key, token)}'
        f"<h3>Usage and cost</h3><p class='note'>By model, from the SDK usage events "
        f"(scope self):</p>{_usage_events(t)}<p class='note'>By model and by stage, from the "
        f"report's accounting:</p>{_accounting(t)}"
        f"<h3>Logs</h3>{_logs(t)}<h3>Cases</h3>{_cases(t)}</section>"
    )
