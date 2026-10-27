"""The bundle page's Trace view as HTML (spec §3.8; u8 plan, Task 3).

One ``<section id="trace">`` over a ``trace_story.TraceStory``, top to bottom: a header (trace
id, verdict, wall time, model calls, cache hits, spend, counts), the hop path notebook → engine
→ aigateway → provider → scoreboard, the cross-service span tree, the model calls with their
gateway log lines, and the verdict's checks in plain words.

WHY the hop path is a ``<table>`` drawn as boxes: it is tabular (hop, state, reason, spans, log
lines, latency), so a screen reader and a text search read it as rows, while CSS lays the rows
out as five boxes with arrows that wrap into a column under 480px. No script, no SVG layout
maths: each state carries a small inline SVG glyph only.

WHY the tree is nested ``<details>``: it opens and closes with no script (CSP ``default-src
'none'``). The top ``OPEN_DEPTH`` levels and the path to any error start open; that path is red.
The tree is paginated server side (``TREE_PAGE`` rows per page, plain links); a page that starts
mid-subtree repeats the first row's ancestors, marked "continued from the previous page".

INVARIANTS: every dynamic value goes through ``escape`` (bundle content is untrusted); ``None``
renders "unknown", never 0, and a partial spend is unknown; the synthetic client span is always
marked "derived from SDK events" and dashed; anything cut is said. ``section`` never raises.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Final
from urllib.parse import quote, urlencode

from workbench.ui import telemetry as tm
from workbench.ui import trace_story as ts
from workbench.ui.render import cell, duration, escape, usd

TREE_PAGE: Final = 500
OPEN_DEPTH: Final = 2  # tree levels shown open by default, besides the path to an error
_NO_ATTRIBUTES: Final[Mapping[str, Any]] = {}
_ANCESTORS_CAP: Final = 24  # ancestors repeated atop a page that starts mid-subtree
_INDENT_CAP: Final = 24  # nested lists stop indenting past this depth

_MATCH: Final = {
    "call_id": "matched by gateway_call_id",
    "time": "matched by time",
    "time-ambiguous": "matched by time (ambiguous)",
    "none": "no log lines matched",
}
_PILL: Final = {"ok": "pass", "fail": "fail", "grey": "unknown"}
_HELD: Final = {
    True: '<span class="pill pass">✓ held</span>',
    False: '<span class="pill fail">✗ not held</span>',
}
_GLYPH: Final = {
    "ok": "M3 8.5l3 3 7-7",
    "fail": "M4 4l8 8M12 4l-8 8",
    "grey": "M4 8h8",
}
STYLE: Final = (
    ".trace-head{display:grid;grid-template-columns:max-content 1fr;gap:2px 12px;margin:0 0 8px}"
    ".trace-head dt{color:var(--muted);font-size:12px}.trace-head dd{margin:0}"
    "code.copy{user-select:all}"
    ".hop-wrap{overflow-x:auto}table.hop-path{width:auto;border-collapse:separate}"
    "table.hop-path thead{position:absolute;width:1px;height:1px;overflow:hidden;"
    "clip:rect(0 0 0 0)}table.hop-path tbody{display:flex;gap:28px;align-items:stretch}"
    "table.hop-path tr{display:flex;flex-direction:column;width:170px;flex:none;"
    "border:1px solid var(--pass);border-radius:6px;padding:6px 8px;position:relative}"
    "table.hop-path td{border:0;padding:1px 0}table.hop-path td:first-child{font-weight:600}"
    'table.hop-path tr+tr::before{content:"→";position:absolute;left:-21px;top:12px;'
    "color:var(--muted)}table.hop-path tr:has(.pill.fail){border-color:var(--fail)}"
    "table.hop-path tr:has(.pill.unknown){border:1px dashed var(--muted);color:var(--muted)}"
    ".pill svg{width:10px;height:10px;vertical-align:-1px;margin-right:3px}"
    ".pill svg path{fill:none;stroke:currentColor;stroke-width:2}"
    "@media (max-width:480px){table.hop-path,table.hop-path tbody{display:flex;"
    "flex-direction:column;width:100%}table.hop-path tr{width:100%}"
    'table.hop-path tr+tr::before{content:"↓";left:50%;top:-24px}}'
    "ul.tree,ul.tree ul{list-style:none;margin:0;padding-left:14px}ul.tree{padding-left:0}"
    f"ul.tree{' ul' * _INDENT_CAP}{{padding-left:0}}"
    "ul.tree li{margin:1px 0}ul.tree details{margin:0}"
    ".span .sname{font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;"
    "font-size:12px}.span.err .sname{color:var(--fail);font-weight:600}"
    ".span.synthetic{border:1px dashed var(--muted);border-radius:4px;padding:0 4px}"
    "b.times{color:var(--muted)}li.cont>.note{font-style:italic}"
    "table.calls details{margin:0}"
)


@dataclass(frozen=True)
class _Row:
    """One tree node in pre-order: its depth, its parent row, and whether it leads to an error."""

    node: ts.Node
    depth: int
    parent: int | None
    err: bool


# --- header -----------------------------------------------------------------------------------


def _flatten(roots: Sequence[ts.Node]) -> list[_Row]:
    """Pre-order rows, iteratively; ``err`` marks a failed span and every ancestor of one."""
    found: list[tuple[ts.Node, int, int | None]] = []
    stack: list[tuple[ts.Node, int, int | None]] = [(n, 0, None) for n in reversed(roots)]
    while stack:
        node, depth, parent = stack.pop()
        found.append((node, depth, parent))
        here = len(found) - 1
        stack.extend((child, depth + 1, here) for child in reversed(node.children))
    err = [ts.is_error(node.span) for node, _, _ in found]
    for i in reversed(range(len(found))):  # children come after their parent: walk back up
        parent = found[i][2]
        if err[i] and parent is not None:
            err[parent] = True
    return [_Row(node, depth, parent, err[i]) for i, (node, depth, parent) in enumerate(found)]


def _sum_known(values: Sequence[int | None]) -> int | None:
    known = [v for v in values if v is not None]
    return sum(known) if known else None


def _header(story: ts.TraceStory, rows: Sequence[_Row]) -> str:
    calls = story.calls
    spend = tm.money_sum(c.spend for c in calls) if calls else None
    spans = sum(r.node.collapsed for r in rows if not r.node.synthetic)
    ids = " ".join(f'<code class="copy">{escape(t)}</code>' for t in story.trace_ids) or "unknown"
    facts = (
        ("trace id", ids),
        ("verdict", escape(story.verdict)),
        ("wall time", duration(story.wall_ns)),
        ("model calls", str(len(calls))),
        ("cache hits", str(sum(c.cache == "hit" for c in calls))),
        ("spend", usd(spend)),
        ("spans", str(spans)),
        ("SDK events", cell(story.events)),
        ("log lines", cell(_sum_known([h.log_lines for h in story.hops]))),
    )
    body = "".join(f"<dt>{name}</dt><dd>{value}</dd>" for name, value in facts)
    return f'<dl class="trace-head">{body}</dl>'


# --- hop path ---------------------------------------------------------------------------------


def _glyph(state: str) -> str:
    path = _GLYPH.get(state, _GLYPH["grey"])
    return f'<svg viewBox="0 0 16 16" aria-hidden="true"><path d="{path}"/></svg>'


def _hop(hop: ts.Hop) -> str:
    pill = _PILL.get(hop.state, "unknown")
    word = {"ok": "ok", "fail": "failed"}.get(hop.state, "not seen")
    return (
        f"<tr><td>{escape(hop.name)}</td>"
        f'<td><span class="pill {pill}">{_glyph(hop.state)}{word}</span></td>'
        f"<td class='note'>{escape(hop.reason or '')}</td>"
        f"<td class='note'>{hop.spans} spans · {cell(hop.log_lines)} log lines</td>"
        f"<td class='note'>latency {duration(hop.latency_ns)}</td></tr>"
    )


def _hops(story: ts.TraceStory) -> str:
    head = "".join(f"<th>{h}</th>" for h in ("Hop", "State", "Why", "Counts", "Latency"))
    rows = "".join(_hop(h) for h in story.hops)
    return (
        '<p class="note">notebook (SDK) → engine → aigateway → provider or cache → scoreboard'
        "</p>"
        f'<div class="hop-wrap"><table class="hop-path"><thead><tr>{head}</tr></thead>'
        f"<tbody>{rows}</tbody></table></div>"
    )


def _notes(story: ts.TraceStory) -> str:
    items = list(story.notes)
    cut = {k: n for k, n in story.cut.items() if n}
    if cut:
        what = ", ".join(f"{n} {k.replace('_', ' ')}" for k, n in cut.items())
        items.append(f"not shown: {what}")
    if not items:
        return ""
    return "<ul class='warn'>" + "".join(f"<li>{escape(n)}</li>" for n in items) + "</ul>"


# --- span tree --------------------------------------------------------------------------------


def _span_duration(span: Mapping[str, Any]) -> str:
    start, end = tm.int_or_none(span.get("start_ns")), tm.int_or_none(span.get("end_ns"))
    return duration(None if start is None or end is None or end < start else end - start)


def _label(row: _Row) -> str:
    span, node = row.node.span, row.node
    css = "span" + (" err" if row.err else "") + (" synthetic" if node.synthetic else "")
    raw: object = span.get("attributes")
    attributes = next(iter(tm.dicts([raw])), _NO_ATTRIBUTES)
    meta = [escape(span.get("service")), _span_duration(span)]
    meta += [
        f"{label} {escape(value)}"
        for label, key in (("model", "gen_ai.request.model"), ("cache", "url4.cache_status"))
        if isinstance(value := attributes.get(key), str) and value
    ]
    if ts.is_error(span):
        meta.append("error " + escape(attributes.get("error.type") or "status error"))
    times = f' <b class="times">×{node.collapsed}</b>' if node.collapsed > 1 else ""
    derived = ' <span class="pill unknown">derived from SDK events</span>' if node.synthetic else ""
    return (
        f'<span class="{css}"><span class="sname">{escape(span.get("name"))}</span>{times} '
        f'<span class="note">{" · ".join(meta)}</span>{derived}</span>'
    )


def _ancestors(rows: Sequence[_Row], first: _Row) -> list[_Row]:
    """The first row's ancestors, nearest ``_ANCESTORS_CAP`` of them, outermost first."""
    chain: list[_Row] = []
    parent = first.parent
    while parent is not None and len(chain) < _ANCESTORS_CAP:
        chain.append(rows[parent])
        parent = rows[parent].parent
    return chain[::-1]


def _tree_rows(rows: Sequence[_Row], shown: Sequence[_Row]) -> str:
    out = ['<ul class="tree">']
    closers: list[tuple[int, str]] = []  # (depth, closing markup) of each element still open
    for ancestor in _ancestors(rows, shown[0]):
        out.append(
            '<li class="cont"><span class="note">continued from the previous page, under</span> '
            f"{_label(ancestor)}<ul>"
        )
        closers.append((ancestor.depth, "</ul></li>"))
    for row in shown:
        while closers and closers[-1][0] >= row.depth:
            out.append(closers.pop()[1])
        if not row.node.children:
            out.append(f"<li>{_label(row)}</li>")
            continue
        opened = " open" if row.err or row.depth < OPEN_DEPTH else ""
        css = ' class="err-path"' if row.err else ""
        out.append(f"<li><details{opened}{css}><summary>{_label(row)}</summary><ul>")
        closers.append((row.depth, "</ul></details></li>"))
    out += [markup for _, markup in reversed(closers)]
    out.append("</ul>")
    return "".join(out)


def _link(key: str, token: str | None, page: int) -> str:
    query = {"trace_page": page} | ({"token": token} if token else {})
    return f"/bundles/{quote(key)}?{urlencode(query)}#trace-tree"


def _pager(key: str, token: str | None, page: int, pages: int) -> str:
    if pages == 1:
        return ""
    parts = [f"<span>page {page} of {pages}</span>"]
    if page > 1:
        parts.append(f'<a href="{escape(_link(key, token, page - 1))}">previous</a>')
    if page < pages:
        parts.append(f'<a href="{escape(_link(key, token, page + 1))}">next</a>')
    return f"<nav class='pages note'>{''.join(parts)}</nav>"


def _tree(rows: Sequence[_Row], key: str, token: str | None, page: int) -> str:
    if not rows:
        return (
            "<p class='warn'>Empty tree: no spans received (the export may be down, or the "
            "bundle predates span capture). An empty tree is no evidence of success.</p>"
        )
    shown, page, pages = tm.page_of(rows, page, TREE_PAGE)
    pager = _pager(key, token, page, pages)
    note = (
        f"<p class='note'>{len(rows)} rows. Same-named sibling leaves fold into one (×N); "
        "the path to an error opens by default and is red.</p>"
    )
    return f"{note}{pager}{_tree_rows(rows, shown)}{pager}"


# --- model calls ------------------------------------------------------------------------------


def _status(call: ts.Call) -> str:
    if call.status != "error":
        return escape(call.status)
    return f'<span class="pill fail">error</span> {cell(call.failure_code)}'


def _log_cell(call: ts.Call) -> str:
    label = _MATCH.get(call.match, "unknown match")
    if not call.log_lines:
        return f"<span class='muted'>{escape(label)}</span>"
    opened = " open" if call.status == "error" else ""
    count = len(call.log_lines)
    return (
        f"<details{opened}><summary>{count} line{'s' if count != 1 else ''} · "
        f"{escape(label)}</summary><pre>{escape(chr(10).join(call.log_lines))}</pre></details>"
    )


def _call_row(n: int, call: ts.Call) -> str:
    css = ' class="hl-err"' if call.status == "error" else ""
    return (
        f"<tr{css}><td class='num'>{n}</td><td>{cell(call.model)}</td>"
        f"<td>{cell(call.provider)}</td><td>{cell(call.cache)}</td>"
        f"<td class='num'>{cell(call.tokens_in)}</td><td class='num'>{cell(call.tokens_out)}</td>"
        f"<td class='num'>{usd(call.spend)}</td><td class='num'>{duration(call.latency_ns)}</td>"
        f"<td>{_status(call)}</td><td>{_log_cell(call)}</td></tr>"
    )


def _calls(story: ts.TraceStory) -> str:
    if not story.calls:
        return "<p class='muted'>No model calls (no gateway chat-completion spans).</p>"
    head = ("#", "Model", "Provider", "Cache", "In tok", "Out tok", "Spend (USD)", "Latency",
            "Status", "Gateway log lines")  # fmt: skip
    th = "".join(f"<th>{h}</th>" for h in head)
    rows = "".join(_call_row(n, c) for n, c in enumerate(story.calls, 1))
    return (
        "<p class='note'>One row per gateway chat span, described by its engine parent span. "
        "Log lines join a call by the exact trace_id token and the span's time window until "
        "gateway spans carry a gateway_call_id. Spend is per call only when one call used "
        "that model.</p>"
        f'<table class="calls"><thead><tr>{th}</tr></thead><tbody>{rows}</tbody></table>'
    )


# --- checks -----------------------------------------------------------------------------------


def _checks(story: ts.TraceStory) -> str:
    if not story.checks:
        return "<p class='muted'>No verdict checks in trace.json.</p>"
    rows = "".join(
        f"<tr><td>{_HELD[c.held]}</td><td>{escape(c.rule)}</td>"
        f"<td class='note'>{escape(c.evidence)}</td></tr>"
        for c in story.checks
    )
    return (
        "<p class='note'>Each rule the verdict applied, from trace.json. The log excerpts "
        "behind them are under <a href='#logs'>Logs</a>.</p>"
        f"<table><thead><tr><th>Held</th><th>Rule</th><th>Evidence</th></tr></thead>"
        f"<tbody>{rows}</tbody></table>"
    )


# --- the section ------------------------------------------------------------------------------


def section(
    story: ts.TraceStory, key: str, token: str | None, page: int = 1, *, appendix: str = ""
) -> str:
    """The whole Trace ``<section>``; ``page`` is the tree's 1-based page (clamped). Never
    raises: should the story trip a view, only this section says so. ``appendix`` is trusted
    markup the caller appends inside the section (the raw trace.json)."""
    try:
        body = _body(story, key, token, page)
    except Exception as exc:  # noqa: BLE001 - the rest of the page must survive a bad bundle
        body = f"<p class='warn'>Trace view could not be shown: {escape(type(exc).__name__)}.</p>"
    return f'<section id="trace"><h2>Trace</h2>{body}{appendix}</section>'


def _body(story: ts.TraceStory, key: str, token: str | None, page: int) -> str:
    rows = _flatten(story.roots)
    return (
        f"{_header(story, rows)}"
        f'<h3 id="trace-hops">Trace chain</h3>{_hops(story)}{_notes(story)}'
        f'<h3 id="trace-tree">Span tree</h3>{_tree(rows, key, token, page)}'
        f'<h3 id="trace-calls">Model calls</h3>{_calls(story)}'
        f'<h3 id="trace-checks">Checks</h3>{_checks(story)}'
    )
