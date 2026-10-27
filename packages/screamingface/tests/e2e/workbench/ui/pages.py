"""Server-rendered HTML for the workbench UI: small functions returning strings.

INVARIANT: every dynamic value reaches the page through ``_e`` (``html.escape``) or, for the
executed notebook, through ``render.sandboxed_iframe``. Bundle files may come from an unzipped
CI artifact, so ``trace.json`` fields are read defensively: a wrong shape renders as "?" or
an "unreadable" note, never as an exception (Review Focus 3).

No external assets (CSP ``default-src 'none'``): one inline ``<style>``, two inline scripts on
the live run page (the output stream with autoscroll, and live telemetry), and CSS ``:has`` for
the paid checkbox. The telemetry script builds rows with ``textContent`` only, never markup.
"""

from __future__ import annotations

import html
import json
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Final
from urllib.parse import quote

from workbench.ui.bundles import BundleDetail, BundleSummary
from workbench.ui.render import notebook_html, sandboxed_iframe
from workbench.ui.runs import Run
from workbench.ui.telemetry import Telemetry, money
from workbench.ui.telemetry_html import STYLE as TELEMETRY_STYLE
from workbench.ui.telemetry_html import TelemetryView
from workbench.ui.telemetry_html import section as telemetry_section
from workbench.ui.trace_html import STYLE as TRACE_STYLE
from workbench.ui.trace_html import section as trace_section
from workbench.ui.trace_story import TraceStory

# pytest's exit codes (pytest.ExitCode), worded for a human reading the run page.
_EXIT_MEANING = {
    0: "all selected notebooks passed",
    1: "some notebooks failed",
    2: "interrupted",
    3: "pytest internal error",
    4: "pytest usage error",
    5: "no notebooks were collected",
}

_STYLE = """
:root{--bg:#fafafa;--fg:#1f2328;--muted:#656d76;--line:#d0d7de;--card:#fff;--code:#f6f8fa;
--pass:#1a7f37;--pass-bg:#dafbe1;--fail:#cf222e;--fail-bg:#ffebe9;--unk:#57606a;--unk-bg:#eaeef2;
--run:#9a6700;--run-bg:#fff8c5;--link:#0969da}
@media (prefers-color-scheme:dark){:root{--bg:#0d1117;--fg:#e6edf3;--muted:#8d96a0;
--line:#30363d;--card:#161b22;--code:#0d1117;--pass:#3fb950;--pass-bg:#12261e;--fail:#f85149;
--fail-bg:#2d1214;--unk:#8d96a0;--unk-bg:#21262d;--run:#d29922;--run-bg:#2b2111;--link:#4493f8}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);font:14px/1.5 system-ui,-apple-system,
"Segoe UI",Roboto,sans-serif}
header{padding:12px 24px;border-bottom:1px solid var(--line);background:var(--card);
display:flex;gap:16px;align-items:baseline;flex-wrap:wrap}
header h1{font-size:16px;margin:0}header .root{color:var(--muted);font-size:12px}
main{padding:16px 24px;max-width:1280px}
a{color:var(--link)}h2{font-size:15px;margin:24px 0 8px}
section{background:var(--card);border:1px solid var(--line);border-radius:6px;padding:12px 16px;
margin-bottom:16px}
table{border-collapse:collapse;width:100%}
th,td{text-align:left;padding:6px 8px;border-bottom:1px solid var(--line);vertical-align:top}
th{font-size:12px;color:var(--muted);font-weight:600}
code,pre,.mono{font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;font-size:12px}
pre{background:var(--code);border:1px solid var(--line);border-radius:6px;padding:8px;
overflow:auto;white-space:pre-wrap;word-break:break-all;margin:6px 0}
#log{max-height:70vh;min-height:8em}
.pill{display:inline-block;padding:1px 8px;border-radius:999px;font-size:12px;font-weight:600;
white-space:nowrap}
.pass{color:var(--pass);background:var(--pass-bg)}.fail{color:var(--fail);background:var(--fail-bg)}
.unknown{color:var(--unk);background:var(--unk-bg)}.running{color:var(--run);background:var(--run-bg)}
.muted{color:var(--muted)}.note{color:var(--muted);font-size:12px}
.warn{border-left:3px solid var(--run);padding:4px 10px;background:var(--run-bg)}
.err{border-left:3px solid var(--fail);padding:4px 10px;background:var(--fail-bg)}
ul.err{padding-left:28px}
fieldset{border:1px solid var(--line);border-radius:6px;margin:0 0 12px;padding:8px 12px}
legend{font-weight:600;font-size:12px;color:var(--muted)}
label{margin-right:16px;display:inline-block}label.off{color:var(--muted)}
.paid{display:none;margin-top:8px}form:has(#target-local:checked) .paid{display:block}
button{font:inherit;padding:4px 14px;border-radius:6px;border:1px solid var(--line);
background:var(--card);color:var(--fg);cursor:pointer}
button.primary{background:var(--pass);color:#fff;border-color:var(--pass)}
button.danger{color:var(--fail);border-color:var(--fail)}
button:disabled{opacity:.5;cursor:not-allowed}
details{margin:6px 0}summary{cursor:pointer}
iframe.nb{width:100%;height:80vh;border:1px solid var(--line);border-radius:6px;background:#fff}
"""

_LIVE_SCRIPT = """
(() => {
  const log = document.getElementById("log");
  const follow = document.getElementById("follow");
  const status = document.getElementById("status");
  const stick = () => { log.scrollTop = log.scrollHeight; };
  const es = new EventSource(log.dataset.events);
  es.onmessage = (e) => {
    const keep = follow.checked;
    log.append(e.data + "\\n");
    if (keep) stick();
  };
  log.addEventListener("scroll", () => {
    follow.checked = log.scrollTop + log.clientHeight >= log.scrollHeight - 8;
  });
  follow.addEventListener("change", () => { if (follow.checked) stick(); });
  const progress = document.getElementById("progress");
  const pad = (n) => String(n).padStart(2, "0");
  const tick = () => {
    const since = Number(progress.dataset.since);
    if (!progress.dataset.label || !since) { progress.textContent = ""; return; }
    const s = Math.max(0, Math.floor(Date.now() / 1000 - since));
    const clock = `${pad(Math.floor(s / 60))}:${pad(s % 60)}`;
    progress.textContent = `running ${progress.dataset.label}… ${clock}`;
  };
  const timer = setInterval(tick, 1000);
  es.addEventListener("progress", (e) => {
    const p = JSON.parse(e.data);
    progress.dataset.label = p.running || "";
    progress.dataset.since = p.since || "";
    tick();
  });
  es.addEventListener("end", () => {
    clearInterval(timer);
    progress.textContent = "";
    es.close();
    status.textContent = "finished: loading the result";
    setTimeout(() => location.reload(), 300);
  });
})();
"""


# Live model calls (unit 6 Task 6): rows from /runs/<id>/telemetry, newest KEEP kept in the DOM.
_TELEMETRY_SCRIPT = """
(() => {
  const box = document.getElementById("telemetry");
  const body = box.querySelector("tbody");
  const note = document.getElementById("calls-note");
  const KEEP = 500;
  let total = 0;
  const unk = (v) => (v === null || v === undefined ? "unknown" : String(v));
  const es = new EventSource(box.dataset.telemetry);
  es.addEventListener("reset", () => {
    body.replaceChildren();
    total = 0;
    note.textContent = "";
  });
  es.addEventListener("call", (e) => {
    const c = JSON.parse(e.data);
    total += 1;
    const tr = document.createElement("tr");
    const ms = c.duration_ms === null ? null : `${c.duration_ms} ms`;
    const cells = [c.service, c.model, c.input_tokens, c.output_tokens, c.cache, ms,
      c.error === null ? "ok" : c.error];
    for (const v of cells) {
      const td = document.createElement("td");
      td.textContent = unk(v);
      tr.append(td);
    }
    if (c.error !== null) tr.className = "fail";
    body.append(tr);
    while (body.rows.length > KEEP) body.deleteRow(0);
    note.textContent = total > KEEP ? `showing the newest ${KEEP} of ${total} model calls` : "";
  });
  es.addEventListener("counts", (e) => {
    const c = JSON.parse(e.data);
    for (const el of box.querySelectorAll("[data-k]")) el.textContent = unk(c[el.dataset.k]);
  });
  es.addEventListener("end", () => es.close());
})();
"""
_COUNTERS = (
    ("calls", "model calls"),
    ("input_tokens", "input tokens"),
    ("output_tokens", "output tokens"),
    ("cache_hits", "cache hits"),
    ("errors", "failed calls"),
    ("cost_usd", "cost (USD)"),
    ("events", "SDK events"),
    ("spans", "spans received"),
    ("unreadable", "unreadable lines"),
    ("over_cap", "lines over the cap"),
)
_CALL_COLUMNS = ("service", "model", "in", "out", "cache", "duration", "status")


def _e(value: object) -> str:
    return html.escape(str(value), quote=True)


def _q(token: str | None) -> str:
    """The query suffix that carries the launch token to the next page (none without it)."""
    return f"?token={quote(token, safe='')}" if token else ""


def _when(epoch: float) -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(epoch)) if epoch else "?"


def layout(title: str, body: str, *, token: str | None) -> str:
    return (
        "<!DOCTYPE html><html lang='en'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        f"<title>{_e(title)} · e2e workbench</title>"
        f"<style>{_STYLE}{TELEMETRY_STYLE}{TRACE_STYLE}</style>"
        "</head><body>"
        f"<header><h1><a href='/{_q(token)}'>e2e workbench</a></h1>"
        f"<span class='muted'>{_e(title)}</span></header><main>{body}</main></body></html>"
    )


def error_page(status: int, reason: str, *, token: str | None, back: str | None = None) -> str:
    link = (
        f'<a href="{_e(back)}">Back to the run</a>'
        if back
        else f"<a href='/{_q(token)}'>Back to the workbench</a>"
    )
    body = f"<section><p class='err'>{_e(reason)}</p><p>{link}</p></section>"
    return layout(f"{status}", body, token=token)


# --- pills -----------------------------------------------------------------------------------


_VERDICT_PILLS: Final = {
    (False, True): '<span class="pill pass">PASS</span>',
    (False, False): '<span class="pill fail">FAIL</span>',
    # spec §3.7: a notebook that fails on purpose passes when it failed exactly as declared
    (True, True): '<span class="pill pass">expected FAIL ✓</span>',
    (True, False): '<span class="pill fail">expected FAIL ✗</span>',
}
_UNREADABLE_PILL: Final = (
    '<span class="pill unknown" title="trace.json missing or malformed">unreadable</span>'
)


def verdict_pill(passed: bool | None, *, expected: bool = False) -> str:
    """PASS/FAIL; for a notebook that fails on purpose (spec §3.7) ``expected FAIL ✓``/``✗``."""
    if passed is None:
        return _UNREADABLE_PILL
    return _VERDICT_PILLS[(expected, passed)]


def run_pill(run: Run) -> str:
    if run.returncode is None:
        word = "cancelling" if run.cancelled else "running"
        return f'<span class="pill running">{word}</span>'
    if run.cancelled:
        return f'<span class="pill unknown">cancelled · exit {run.returncode}</span>'
    css = "pass" if run.returncode == 0 else "fail"
    return f'<span class="pill {css}">exit {run.returncode}</span>'


def _exit_text(run: Run) -> str:
    if run.returncode is None:
        return "The run is in progress; output streams below."
    if run.returncode < 0:
        return f"pytest was killed by signal {-run.returncode}."
    return _EXIT_MEANING.get(run.returncode, "pytest ended with an unexpected exit code") + "."


# --- index -----------------------------------------------------------------------------------


@dataclass(frozen=True)
class LaunchState:
    token: str | None  # the valid launch token, or None when the page was opened without it
    notebooks: Sequence[str]
    local_blocker: str | None  # why `local` is unavailable, None when it is offered
    active: Run | None
    fails_on_purpose: frozenset[str] = frozenset()  # notebooks declaring workbench.expect


def _target_inputs(state: LaunchState) -> str:
    replay = (
        '<label><input type="radio" name="target" id="target-replay" value="replay" checked> '
        "<b>replay</b> <span class='note'>keyless; recorded provider answers</span></label>"
    )
    if state.local_blocker:
        local = (
            '<label class="off"><input type="radio" name="target" id="target-local" '
            'value="local" disabled> <b>local</b> '
            f"<span class='note'>unavailable: {_e(state.local_blocker)}</span></label>"
        )
        paid = ""
    else:
        local = (
            '<label><input type="radio" name="target" id="target-local" value="local"> '
            "<b>local</b> <span class='note'>boots the real runtime; paid</span></label>"
        )
        paid = (
            '<div class="paid warn"><label><input type="checkbox" name="confirm_paid" '
            'value="on"> I understand this run <b>spends real tokens</b> on OpenRouter</label>'
            "</div>"
        )
    return f"<fieldset><legend>Target</legend>{replay}<br>{local}{paid}</fieldset>"


_FAILS_ON_PURPOSE = "(fails on purpose: debugging example)"


def _notebook_inputs(notebooks: Sequence[str], fails_on_purpose: frozenset[str]) -> str:
    def note(n: str) -> str:
        return f" <span class='note'>{_FAILS_ON_PURPOSE}</span>" if n in fails_on_purpose else ""

    boxes = "".join(
        f'<label><input type="checkbox" name="notebooks" value="{_e(n)}"> {_e(n)}{note(n)}</label>'
        for n in notebooks
    )
    return (
        "<fieldset><legend>Notebooks</legend>"
        f"{boxes or '<span class=note>none found</span>'}"
        "<div class='note'>Leave all unchecked to run every notebook.</div></fieldset>"
    )


def _launcher(state: LaunchState) -> str:
    if state.token is None:
        return (
            "<section><h2>Launch a run</h2><p class='warn'>This page was opened without the "
            "launch token, so it is read-only. Open the startup URL printed in the terminal "
            "(it ends in <code>?token=…</code>) to start or cancel runs.</p></section>"
        )
    busy = ""
    disabled = ""
    if state.active is not None:
        link = f"/runs/{_e(state.active.id)}{_q(state.token)}"
        busy = (
            f"<p class='warn'>Run <a href=\"{link}\">{_e(state.active.id)}</a> is active. "
            "One run at a time: the local target binds fixed ports.</p>"
        )
        disabled = " disabled"
    return (
        f"<section><h2>Launch a run</h2>{busy}"
        '<form method="post" action="/runs">'
        f'<input type="hidden" name="token" value="{_e(state.token)}">'
        f"{_target_inputs(state)}{_notebook_inputs(state.notebooks, state.fails_on_purpose)}"
        f'<button class="primary" type="submit"{disabled}>Start run</button>'
        " <span class='note'>Runs <code>pytest tests/e2e/workbench/test_notebooks.py</code>, "
        "exactly the CI lane.</span></form></section>"
    )


def _bundle_rows(bundles: Sequence[BundleSummary], token: str | None) -> str:
    rows = []
    for b in bundles:
        ids = (
            "<br>".join(f"<code>{_e(t)}</code>" for t in b.trace_ids)
            or "<span class=muted>—</span>"
        )
        why = "<br>".join(_e(r) for r in b.reasons) or "<span class=muted>—</span>"
        rows.append(
            f"<tr><td>{verdict_pill(b.passed, expected=b.expected)}</td><td>{_e(b.target)}</td>"
            f'<td><a href="/bundles/{_e(quote(b.key))}{_q(token)}">{_e(b.notebook)}</a>'
            f"<div class='note mono'>{_e(b.key)}</div></td>"
            f"<td>{ids}</td><td>{why}</td><td class='mono'>{_when(b.modified)}</td></tr>"
        )
    return "".join(rows)


def bundle_table(bundles: Sequence[BundleSummary], token: str | None) -> str:
    if not bundles:
        return "<p class='muted'>No bundles yet. Start a run above.</p>"
    return (
        "<table><thead><tr><th>Verdict</th><th>Target</th><th>Notebook</th><th>Trace ids</th>"
        f"<th>Reasons</th><th>Written</th></tr></thead><tbody>{_bundle_rows(bundles, token)}"
        "</tbody></table>"
    )


def _run_list(run_ids: Sequence[str], bundles: Sequence[BundleSummary], token: str | None) -> str:
    if not run_ids:
        return ""
    items = []
    for run_id in run_ids:
        mine = [b for b in bundles if b.key.startswith(f"runs/{run_id}/")]
        passed = sum(b.passed is True for b in mine)
        failed = sum(b.passed is False for b in mine)
        items.append(
            f'<tr><td><a class="mono" href="/runs/{_e(run_id)}{_q(token)}">{_e(run_id)}</a></td>'
            f"<td>{len(mine)}</td><td>{passed}</td><td>{failed}</td></tr>"
        )
    return (
        "<section><h2>Runs</h2><table><thead><tr><th>Run</th><th>Bundles</th><th>Passed</th>"
        f"<th>Failed</th></tr></thead><tbody>{''.join(items)}</tbody></table></section>"
    )


def index_page(
    state: LaunchState, *, root: str, run_ids: Sequence[str], bundles: Sequence[BundleSummary]
) -> str:
    body = (
        f"{_launcher(state)}{_run_list(run_ids, bundles, state.token)}"
        f"<section><h2>Evidence bundles</h2><p class='note'>Under <code>{_e(root)}</code>, "
        f"newest first.</p>{bundle_table(bundles, state.token)}</section>"
    )
    return layout("bundles and runs", body, token=state.token)


# --- run page --------------------------------------------------------------------------------


def _cancel_form(run: Run, token: str | None) -> str:
    if token is None or run.returncode is not None:
        return ""
    disabled = " disabled" if run.cancelled else ""
    return (
        f'<form method="post" action="/runs/{_e(run.id)}/cancel" style="display:inline" '
        "onsubmit=\"return confirm('Cancel this run? Its process group is interrupted and "
        "the target is torn down.')\">"
        f'<input type="hidden" name="token" value="{_e(token)}">'
        f'<button class="danger" type="submit"{disabled}>Cancel run</button></form>'
    )


def elapsed(seconds: float) -> str:
    """``mm:ss`` (minutes keep counting past 59), as the live script renders it."""
    whole = max(0, int(seconds))
    return f"{whole // 60:02d}:{whole % 60:02d}"


def _progress(run: Run, now: float) -> str:
    """The "running <notebook>… mm:ss" line; the live script ticks it every second."""
    if run.returncode is not None:
        return ""
    label, since = run.running, run.running_since
    text = f"running {label}… {elapsed(now - since)}" if label and since else ""
    return (
        f'<p id="progress" class="mono" data-label="{_e(label or "")}" '
        f'data-since="{_e(since or "")}">{_e(text)}</p>'
    )


def _log_block(run: Run) -> str:
    if run.returncode is None:
        events = f"/runs/{run.id}/events?from=0"
        return (
            "<label><input type='checkbox' id='follow' checked> Follow output</label>"
            f'<pre id="log" data-events="{_e(events)}"></pre>'
            f"<script>{_LIVE_SCRIPT}</script>"
        )
    dropped = (
        f"<p class='note'>{run.dropped} earlier lines were dropped (memory cap).</p>"
        if run.dropped
        else ""
    )
    text = "\n".join(run.lines) or "(no output)"
    return f'{dropped}<pre id="log">{_e(text)}</pre>'


def _live_telemetry(run: Run) -> str:
    """While the run executes: its model calls and running totals, streamed (unit 6 Task 6)."""
    if run.returncode is not None:
        return ""
    counters = " · ".join(
        f"{_e(label)} <b class='mono' data-k=\"{_e(key)}\">0</b>" for key, label in _COUNTERS
    )
    head = "".join(f"<th>{_e(c)}</th>" for c in _CALL_COLUMNS)
    return (
        f'<section id="telemetry" data-telemetry="/runs/{_e(run.id)}/telemetry">'
        "<h2>Live telemetry</h2>"
        f"<p id='counters'>{counters}</p>"
        "<p class='note'>Model calls as the engine exports their spans; unknown values say "
        "unknown, never 0. The full picture is in each bundle's Telemetry section.</p>"
        f"<table id='calls'><thead><tr>{head}</tr></thead><tbody></tbody></table>"
        f"<p class='note' id='calls-note'></p><script>{_TELEMETRY_SCRIPT}</script></section>"
    )


def _run_bundles(run_id: str, bundles: Sequence[BundleSummary], token: str | None) -> str:
    if not bundles:
        return f"<p class='muted'>No bundles under <code>runs/{_e(run_id)}/</code>.</p>"
    return bundle_table(bundles, token)


def _stop_note(run: Run, stop_command: str | None) -> str:
    if stop_command is None:
        return ""
    why = (
        "The run's process group had to be killed, so its teardown (which runs "
        "<code>screamingface down</code>) may not have run."
        if run.killed
        else "<code>screamingface up</code> detaches into its own session, so cancelling the "
        "run does not stop it; only the teardown's <code>down</code> does."
    )
    return (
        f"<div class='warn' id='stop-note'><p><b>The runtime may still be up.</b> {why} "
        "Check, and stop it with (from <code>packages/screamingface</code>, prefix "
        "<code>uv run --extra runtime</code>):</p>"
        f"<pre>{_e(stop_command)}</pre></div>"
    )


def run_page(
    run: Run,
    bundles: Sequence[BundleSummary],
    *,
    token: str | None,
    stop_command: str | None = None,
) -> str:
    notebooks = ", ".join(run.request.notebooks) or "all"
    finished = (
        f"<section><h2>Bundles written by this run</h2>{_run_bundles(run.id, bundles, token)}"
        "<p class='note'>Each bundle's Telemetry section holds the run's spans, usage, logs "
        "and cases.</p></section>"
        if run.returncode is not None
        else ""
    )
    body = (
        f"<section><h2>Run <span class='mono'>{_e(run.id)}</span> {run_pill(run)}</h2>"
        f"<p id='status'>{_e(_exit_text(run))}</p>{_progress(run, time.time())}"
        f"<p>Target <b>{_e(run.request.target)}</b> · notebooks {_e(notebooks)} · output "
        f"<code>{_e(run.out_dir)}</code></p>{_cancel_form(run, token)}"
        f"{_stop_note(run, stop_command)}</section>"
        f"{finished}{_live_telemetry(run)}<section><h2>Output</h2>{_log_block(run)}</section>"
    )
    return layout(f"run {run.id}", body, token=token)


def past_run_page(run_id: str, bundles: Sequence[BundleSummary], *, token: str | None) -> str:
    body = (
        f"<section><h2>Run <span class='mono'>{_e(run_id)}</span></h2><p class='note'>Started "
        "by an earlier UI process: its live output is not kept, only the bundles it wrote."
        f"</p></section><section><h2>Bundles</h2>{_run_bundles(run_id, bundles, token)}"
        "</section>"
    )
    return layout(f"run {run_id}", body, token=token)


# --- bundle page -----------------------------------------------------------------------------


def _scalar(value: object) -> str:
    if value is None:
        return "—"
    return _e(value) if isinstance(value, str | int | float | bool) else "?"


def _usd(amount: Decimal | None) -> str:
    return "unknown" if amount is None else _e(f"${amount}")


def _dicts(value: object) -> list[Mapping[str, Any]]:
    items: list[object] = value if isinstance(value, list) else []  # pyright: ignore[reportUnknownVariableType]
    return [i for i in items if isinstance(i, dict)]  # pyright: ignore[reportUnknownVariableType]


def _strs(value: object) -> list[str]:
    items: list[object] = value if isinstance(value, list) else []  # pyright: ignore[reportUnknownVariableType]
    return [i for i in items if isinstance(i, str)]


def _candidates(trace: Mapping[str, Any]) -> str:
    result = trace.get("result")
    candidates = result.get("candidates") if isinstance(result, dict) else None  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]
    if not isinstance(candidates, dict) or not candidates:
        return "<p class='muted'>No candidate results reported by the notebook.</p>"
    rows, spends = [], []
    for name, raw in candidates.items():  # pyright: ignore[reportUnknownVariableType]
        c: Mapping[str, Any] = raw if isinstance(raw, dict) else {}  # pyright: ignore[reportUnknownVariableType]
        spend = money(c.get("cost_usd"))
        spends.append(spend)
        rows.append(
            f"<tr><td>{_e(name)}</td><td>{_scalar(c.get('score'))}</td>"
            f"<td>{_usd(spend)}</td><td>{_scalar(c.get('cache_hits'))}</td>"
            f"<td>{_usd(money(c.get('cache_saved_cost_usd')))}</td></tr>"
        )
    # One unknown amount makes the total unknown: a partial sum would read as the whole spend.
    known = [s for s in spends if s is not None]
    total = sum(known, Decimal(0)) if len(known) == len(spends) else None
    return (
        f"<p>Total spend: <b>{_usd(total)}</b> <span class='note'>(what the provider billed; "
        "the cache-saved amount is reported separately and never included)</span></p>"
        "<table><thead><tr><th>Candidate</th><th>Score</th><th>Spend (USD)</th>"
        "<th>Cache hits</th><th>Cache-saved cost (USD)</th></tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table>"
    )


def _logs(logs: Mapping[str, str], failed_hops: set[str]) -> str:
    if not logs:
        return "<p class='muted'>No log excerpts in this bundle.</p>"
    blocks = []
    for name, text in logs.items():
        count = len(text.splitlines())
        is_open = " open" if name in failed_hops else ""
        blocks.append(
            f"<details{is_open}><summary><b>{_e(name)}</b> "
            f"<span class='note'>{count} lines</span></summary><pre>{_e(text)}</pre></details>"
        )
    return "".join(blocks)


def _failed_hops(trace: Mapping[str, Any] | None) -> set[str]:
    hops = _dicts((trace or {}).get("hops"))
    return {str(h.get("name")) for h in hops if h.get("found") is False}


def _failure_pairs(value: object) -> str:
    """``code at stage`` per failure dict, escaped; "none" for an empty list, "?" otherwise."""
    if not isinstance(value, list):
        return "?"
    pairs = [f"{_scalar(f.get('code'))} at {_scalar(f.get('stage'))}" for f in _dicts(value)]
    return ", ".join(pairs) or "none"


def _expectation(trace: Mapping[str, Any] | None, passed: bool | None) -> str:
    """Spec §3.7: what the notebook declared, what the run showed, and the ✓ or ✗."""
    raw_expect = (trace or {}).get("expect")
    raw_observed = (trace or {}).get("observed")
    expect: Mapping[str, Any] = raw_expect if isinstance(raw_expect, dict) else {}  # pyright: ignore[reportUnknownVariableType]
    observed: Mapping[str, Any] = raw_observed if isinstance(raw_observed, dict) else {}  # pyright: ignore[reportUnknownVariableType]
    codes = ", ".join(_e(c) for c in _strs(expect.get("failure_codes"))) or "?"
    counts = observed.get("error_telemetry")
    tele: Mapping[str, Any] = counts if isinstance(counts, dict) else {}  # pyright: ignore[reportUnknownVariableType]
    outcome = (
        "<p>✓ It failed exactly as declared, and the telemetry caught the error.</p>"
        if passed is True
        else ""
    )
    return (
        "<p>This notebook <b>fails on purpose</b>. Declared: "
        f"<code>{codes}</code> at stage <code>{_scalar(expect.get('stage'))}</code>. "
        f"Observed: <code>{_failure_pairs(observed.get('failures'))}</code> · error "
        f"telemetry: {_scalar(tele.get('spans'))} failing spans, {_scalar(tele.get('logs'))} "
        f"ERROR logs.</p>{outcome}"
    )


def _verdict_section(detail: BundleDetail) -> str:
    s, trace = detail.summary, detail.trace
    mark = "✗ " if s.expected else ""
    reasons = "".join(f"<li>{mark}{_e(r)}</li>" for r in s.reasons)
    error = (trace or {}).get("error")
    parts = [
        f"<section><h2>{verdict_pill(s.passed, expected=s.expected)} {_e(s.notebook)} "
        f"<span class='muted'>on {_e(s.target)}</span></h2>"
        f"<p class='note mono'>{_e(s.key)} · written {_when(s.modified)}</p>"
    ]
    if trace is None:
        parts.append(
            "<p class='warn'>trace.json is missing or unreadable, so the verdict is unknown. "
            "The logs and notebook below are shown as found.</p>"
        )
    if s.expected:
        parts.append(_expectation(trace, s.passed))
    if reasons:
        parts.append(f"<ul class='err'>{reasons}</ul>")
    if isinstance(error, str) and error:
        parts.append(f"<p>Notebook error:</p><pre>{_e(error)}</pre>")
    ids = " ".join(f"<code>{_e(t)}</code>" for t in s.trace_ids) or "none"
    parts.append(f"<p>Trace ids: {ids}</p></section>")
    return "".join(parts)


def _notebook_section(detail: BundleDetail) -> str:
    if detail.notebook_path is None:
        return "<p class='muted'>This bundle has no executed notebook.</p>"
    return (
        "<p class='note'>Rendered in a sandboxed frame: notebook outputs are untrusted and "
        "cannot run scripts here.</p>" + sandboxed_iframe(notebook_html(detail.notebook_path))
    )


def bundle_page(
    detail: BundleDetail,
    telemetry: Telemetry | None = None,
    view: TelemetryView | None = None,
    *,
    token: str | None,
    story: TraceStory | None = None,
    trace_page: int = 1,
    story_error: str | None = None,
) -> str:
    """The bundle page. ``story`` is ``None`` when the Trace view could not be built;
    ``story_error`` then names why (the exception type)."""
    trace = detail.trace
    raw = (
        "<details><summary>Raw trace.json</summary>"
        f"<pre>{_e(json.dumps(trace, indent=2, default=str))}</pre></details>"
        if trace is not None
        else ""
    )
    telemetry_html = telemetry_section(
        telemetry or Telemetry(),
        view or TelemetryView(),
        key=detail.summary.key,
        token=token,
        gateway_log=detail.logs.get("aigateway"),
    )
    trace_html = (
        trace_section(story, detail.summary.key, token, trace_page, appendix=raw)
        if story is not None
        else '<section id="trace"><h2>Trace</h2><p class="warn">The Trace view could not be '
        f"built from this bundle{': ' + _e(story_error) if story_error else ''}.</p>"
        f"{raw}</section>"
    )
    body = (
        f"{_verdict_section(detail)}"
        f"{trace_html}"
        f"<section><h2>Result</h2>{_candidates(trace or {})}</section>"
        f"{telemetry_html}"
        f'<section id="logs"><h2>Logs</h2>{_logs(detail.logs, _failed_hops(trace))}</section>'
        f'<section id="executed-notebook"><h2>Executed notebook</h2>'
        f"{_notebook_section(detail)}</section>"
    )
    return layout(f"{detail.summary.target}/{detail.summary.notebook}", body, token=token)
