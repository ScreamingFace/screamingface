"""Server-rendered HTML for the workbench UI: small functions returning strings.

INVARIANT: every dynamic value reaches the page through ``_e`` (``html.escape``) or, for the
executed notebook, through ``render.sandboxed_iframe``. Bundle files may come from an unzipped
CI artifact, so ``trace.json`` fields are read defensively: a wrong shape renders as "?" or
an "unreadable" note, never as an exception (Review Focus 3).

No external assets (CSP ``default-src 'none'``): one inline ``<style>``, one inline script on
the live run page (EventSource + autoscroll), and CSS ``:has`` for the paid checkbox.
"""

from __future__ import annotations

import html
import json
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote

from workbench.ui.bundles import BundleDetail, BundleSummary
from workbench.ui.render import notebook_html, sandboxed_iframe
from workbench.ui.runs import Run

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
  es.addEventListener("end", () => {
    es.close();
    status.textContent = "finished: loading the result";
    setTimeout(() => location.reload(), 300);
  });
})();
"""


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
        f"<title>{_e(title)} · e2e workbench</title><style>{_STYLE}</style></head><body>"
        f"<header><h1><a href='/{_q(token)}'>e2e workbench</a></h1>"
        f"<span class='muted'>{_e(title)}</span></header><main>{body}</main></body></html>"
    )


def error_page(status: int, reason: str, *, token: str | None) -> str:
    body = (
        f"<section><p class='err'>{_e(reason)}</p>"
        f"<p><a href='/{_q(token)}'>Back to the workbench</a></p></section>"
    )
    return layout(f"{status}", body, token=token)


# --- pills -----------------------------------------------------------------------------------


def verdict_pill(passed: bool | None) -> str:
    if passed is True:
        return '<span class="pill pass">PASS</span>'
    if passed is False:
        return '<span class="pill fail">FAIL</span>'
    return '<span class="pill unknown" title="trace.json missing or malformed">unreadable</span>'


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


def _notebook_inputs(notebooks: Sequence[str]) -> str:
    boxes = "".join(
        f'<label><input type="checkbox" name="notebooks" value="{_e(n)}"> {_e(n)}</label>'
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
        f"{_target_inputs(state)}{_notebook_inputs(state.notebooks)}"
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
            f"<tr><td>{verdict_pill(b.passed)}</td><td>{_e(b.target)}</td>"
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


def _run_bundles(run_id: str, bundles: Sequence[BundleSummary], token: str | None) -> str:
    if not bundles:
        return f"<p class='muted'>No bundles under <code>runs/{_e(run_id)}/</code>.</p>"
    return bundle_table(bundles, token)


def run_page(run: Run, bundles: Sequence[BundleSummary], *, token: str | None) -> str:
    notebooks = ", ".join(run.request.notebooks) or "all"
    finished = (
        f"<section><h2>Bundles written by this run</h2>{_run_bundles(run.id, bundles, token)}"
        "</section>"
        if run.returncode is not None
        else ""
    )
    body = (
        f"<section><h2>Run <span class='mono'>{_e(run.id)}</span> {run_pill(run)}</h2>"
        f"<p id='status'>{_e(_exit_text(run))}</p>"
        f"<p>Target <b>{_e(run.request.target)}</b> · notebooks {_e(notebooks)} · output "
        f"<code>{_e(run.out_dir)}</code></p>{_cancel_form(run, token)}</section>"
        f"{finished}<section><h2>Output</h2>{_log_block(run)}</section>"
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
    return _e(value) if isinstance(value, str | int | float | bool) or value is None else "?"


def _dicts(value: object) -> list[Mapping[str, Any]]:
    items: list[object] = value if isinstance(value, list) else []  # pyright: ignore[reportUnknownVariableType]
    return [i for i in items if isinstance(i, dict)]  # pyright: ignore[reportUnknownVariableType]


def _strs(value: object) -> list[str]:
    items: list[object] = value if isinstance(value, list) else []  # pyright: ignore[reportUnknownVariableType]
    return [i for i in items if isinstance(i, str)]


def _hop_table(trace: Mapping[str, Any]) -> str:
    rows = []
    for hop in _dicts(trace.get("hops")):
        found = hop.get("found")
        pill = verdict_pill(found if isinstance(found, bool) else None)
        pill = pill.replace(">PASS<", ">found<").replace(">FAIL<", ">missing<")
        missing = "<br>".join(f"<code>{_e(t)}</code>" for t in _strs(hop.get("missing_ids")))
        rows.append(
            f"<tr><td>{_scalar(hop.get('name'))}</td><td>{pill}</td>"
            f"<td>{_scalar(hop.get('lines'))}</td><td>{missing or '—'}</td></tr>"
        )
    if not rows:
        return "<p class='muted'>No hops recorded in trace.json.</p>"
    return (
        "<table><thead><tr><th>Hop</th><th>Trace found</th><th>Matching lines</th>"
        f"<th>Missing ids</th></tr></thead><tbody>{''.join(rows)}</tbody></table>"
    )


def _chain_facts(trace: Mapping[str, Any]) -> str:
    lifecycle = trace.get("lifecycle")
    facts = []
    if isinstance(lifecycle, dict):
        for name, seen in lifecycle.items():  # pyright: ignore[reportUnknownVariableType]
            facts.append(f"{_e(name)}: {'yes' if seen is True else 'no'}")
    unattributed = trace.get("unattributed_gateway_lines")
    if isinstance(unattributed, int):
        facts.append(f"aigateway lines without gateway_call_id: {unattributed}")
    return f"<p class='note'>{' · '.join(facts)}</p>" if facts else ""


def _candidates(trace: Mapping[str, Any]) -> str:
    result = trace.get("result")
    candidates = result.get("candidates") if isinstance(result, dict) else None  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]
    if not isinstance(candidates, dict) or not candidates:
        return "<p class='muted'>No candidate results reported by the notebook.</p>"
    rows = []
    for name, raw in candidates.items():  # pyright: ignore[reportUnknownVariableType]
        c: Mapping[str, Any] = raw if isinstance(raw, dict) else {}  # pyright: ignore[reportUnknownVariableType]
        rows.append(
            f"<tr><td>{_e(name)}</td><td>{_scalar(c.get('score'))}</td>"
            f"<td>{_scalar(c.get('cache_hits'))}</td>"
            f"<td>{_scalar(c.get('cache_saved_cost_usd'))}</td></tr>"
        )
    return (
        "<table><thead><tr><th>Candidate</th><th>Score</th><th>Cache hits</th>"
        f"<th>Cache-saved cost (USD)</th></tr></thead><tbody>{''.join(rows)}</tbody></table>"
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


def _verdict_section(detail: BundleDetail) -> str:
    s, trace = detail.summary, detail.trace
    reasons = "".join(f"<li>{_e(r)}</li>" for r in s.reasons)
    error = (trace or {}).get("error")
    parts = [
        f"<section><h2>{verdict_pill(s.passed)} {_e(s.notebook)} "
        f"<span class='muted'>on {_e(s.target)}</span></h2>"
        f"<p class='note mono'>{_e(s.key)} · written {_when(s.modified)}</p>"
    ]
    if trace is None:
        parts.append(
            "<p class='warn'>trace.json is missing or unreadable, so the verdict is unknown. "
            "The logs and notebook below are shown as found.</p>"
        )
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


def bundle_page(detail: BundleDetail, *, token: str | None) -> str:
    trace = detail.trace
    chain = (
        f"{_hop_table(trace)}{_chain_facts(trace)}"
        if trace is not None
        else "<p class='muted'>Unavailable without a readable trace.json.</p>"
    )
    raw = (
        "<details><summary>Raw trace.json</summary>"
        f"<pre>{_e(json.dumps(trace, indent=2, default=str))}</pre></details>"
        if trace is not None
        else ""
    )
    body = (
        f"{_verdict_section(detail)}"
        f"<section><h2>Trace chain</h2>{chain}{raw}</section>"
        f"<section><h2>Result</h2>{_candidates(trace or {})}</section>"
        f"<section><h2>Logs</h2>{_logs(detail.logs, _failed_hops(trace))}</section>"
        f"<section><h2>Executed notebook</h2>{_notebook_section(detail)}</section>"
    )
    return layout(f"{detail.summary.target}/{detail.summary.notebook}", body, token=token)
