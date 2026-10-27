"""The bundle page's Trace view (u8 plan, Task 3): one story of a run across every hop, as HTML.

Each test renders ``trace_html.section`` over a ``TraceStory`` built from a small bundle in
``tmp_path`` (the Task 2 fixtures), or the whole bundle page through the real app.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from workbench.ui import trace_html as th
from workbench.ui import trace_story as ts
from workbench.ui.app import create_app
from workbench.ui.runs import RunManager
from workbench.ui.test_trace_story import (
    CHAT,
    CLIENT,
    GATEWAY,
    MS,
    T0,
    TID,
    bundle,
    candidate_attrs,
    run_spans,
    span,
    trace_doc,
)

KEY = "replay/quickstart"
TOKEN = "t0k3n-for-tests"
RECORDER = {"first_event_ns": T0 - 5 * MS, "last_event_ns": T0 + 105 * MS}


def _render(directory: Path, page: int = 1, token: str | None = None) -> str:
    return th.section(ts.build(directory), KEY, token, page)


def _part(html: str, start: str, end: str = "<h3") -> str:
    return html.split(start, 1)[1].split(end, 1)[0]


def _row_of(html: str, needle: str) -> str:
    at = html.index(needle)
    return html[html.rindex("<tr", 0, at) : html.index("</tr>", at)]


# --- header -----------------------------------------------------------------------------------


def test_the_header_shows_trace_verdict_calls_cache_hits_and_unknown_spend(
    tmp_path: Path,
) -> None:
    html = _render(bundle(tmp_path, run_spans(), recorder=RECORDER))
    header = _part(html, '<dl class="trace-head">', "</dl>")
    assert TID in header
    assert "<dt>verdict</dt><dd>pass</dd>" in header
    assert "<dt>model calls</dt><dd>2</dd>" in header
    assert "<dt>cache hits</dt><dd>2</dd>" in header
    assert "<dt>spend</dt><dd>unknown</dd>" in header  # replay: no accounting, never $0
    assert "<dt>wall time</dt><dd>110.0 ms</dd>" in header


# --- hop path ---------------------------------------------------------------------------------


def test_the_hop_path_has_five_hops_and_grey_ones_say_why(tmp_path: Path) -> None:
    html = _render(bundle(tmp_path, run_spans(), recorder=RECORDER))
    path = _part(html, '<table class="hop-path"', "</table>")
    names = re.findall(r"<tr><td>(\w+)</td>", path)
    assert names == ["notebook", "engine", "aigateway", "provider", "scoreboard"]
    assert "none on replay: served from cache" in _row_of(path, "<td>provider</td>")
    assert "not instrumented" in _row_of(path, "<td>scoreboard</td>")
    assert 'class="pill unknown"' in _row_of(path, "<td>scoreboard</td>")
    assert 'class="pill pass"' in _row_of(path, "<td>engine</td>")
    assert "<svg" in path


def test_with_no_spans_the_view_still_shows_hops_checks_and_says_no_spans(tmp_path: Path) -> None:
    html = _render(bundle(tmp_path, None))
    assert html.count("<tr><td>") >= 5
    tree = _part(html, '<h3 id="trace-tree"')
    assert "no spans received" in tree and "<details" not in tree
    assert "the engine log carries the run&#x27;s trace id" in html
    header = _part(html, '<dl class="trace-head">', "</dl>")
    assert "<dt>model calls</dt><dd>unknown</dd>" in header  # nobody observed them: not 0
    assert "<dt>cache hits</dt><dd>unknown</dd>" in header
    assert "<dt>SDK events</dt><dd>unknown</dd>" in header  # no events.jsonl: not 0
    assert "No model calls" not in html
    assert "no spans received" in _part(html, '<h3 id="trace-calls"')


def test_an_empty_events_file_is_a_measured_zero(tmp_path: Path) -> None:
    html = _render(bundle(tmp_path, run_spans(), events=[]))
    assert "<dt>SDK events</dt><dd>0</dd>" in _part(html, '<dl class="trace-head">', "</dl>")


# --- span tree --------------------------------------------------------------------------------


def test_the_synthetic_client_span_is_marked_derived_from_sdk_events(tmp_path: Path) -> None:
    html = _render(bundle(tmp_path, run_spans(), recorder=RECORDER))
    tree = _part(html, '<h3 id="trace-tree"')
    row = tree[tree.index("sdk.evaluate") - 200 : tree.index("sdk.evaluate") + 200]
    assert "synthetic" in row and "derived from SDK events" in row
    assert '<span class="span synthetic"><span class="sname">sdk.evaluate</span>' in tree
    assert tree.index("sdk.evaluate") < tree.index("url4.run") < tree.index(CHAT)


def test_collapsed_siblings_read_times_n(tmp_path: Path) -> None:
    spans = [span("p", None, "StructNode")]
    spans += [span(f"t{i}", "p", "TextNode", start=i) for i in range(9)]
    html = _render(bundle(tmp_path, spans))
    assert 'TextNode</span> <b class="times">×9</b>' in html
    assert html.count("TextNode") == 1


def test_the_path_to_an_error_is_open_and_red(tmp_path: Path) -> None:
    spans = run_spans(candidate_status="error")
    html = _render(bundle(tmp_path, spans, recorder=RECORDER))
    tree = _part(html, '<h3 id="trace-tree"')
    for name in ("sdk.evaluate", "url4.run", "ProcessNode", "/benchmarks/candidate"):
        at = tree.index(f">{name}<")
        opener = tree[tree.rindex("<details", 0, at) : at]
        assert opener.startswith('<details open class="err-path"'), (name, opener)
    assert 'class="span err"' in tree


def test_a_failing_gateway_hop_shows_a_cross_and_the_failure_code(tmp_path: Path) -> None:
    trace = trace_doc(
        expect={"outcome": "fail", "failure_codes": ["upstream_error"], "stage": "candidate"},
        observed={"failures": [{"code": "upstream_error", "stage": "candidate"}]},
    )
    spans = run_spans(candidate_status="error")
    html = _render(bundle(tmp_path, spans, trace=trace, recorder=RECORDER))
    row = _row_of(_part(html, '<table class="hop-path"', "</table>"), "<td>aigateway</td>")
    assert 'class="pill fail"' in row and th._GLYPH["fail"] in row  # pyright: ignore[reportPrivateUsage]
    assert "2 of 2 calls failed: upstream_error" in row


def test_a_span_without_service_or_name_reads_unknown(tmp_path: Path) -> None:
    bare = {k: v for k, v in span("a", None, "A").items() if k not in ("service", "name")}
    tree = _part(_render(bundle(tmp_path, [bare])), '<h3 id="trace-tree"')
    assert '<span class="sname">unknown</span>' in tree
    assert "None" not in tree


def test_an_off_error_branch_below_the_top_levels_stays_closed(tmp_path: Path) -> None:
    spans = [span("a", None, "A"), span("b", "a", "B"), span("c", "b", "C"), span("d", "c", "D")]
    tree = _part(_render(bundle(tmp_path, spans)), '<h3 id="trace-tree"')
    at = tree.index(">C<")
    assert tree[tree.rindex("<details", 0, at) : at].startswith("<details>")


def test_1200_spans_give_three_pages_with_a_pager(tmp_path: Path) -> None:
    spans = [span("r", None, "Root")] + [span(f"s{i}", "r", f"N{i}", start=i) for i in range(1199)]
    path = bundle(tmp_path, spans)
    first = _render(path, 1, TOKEN)
    assert "page 1 of 3" in first
    assert f'href="/bundles/{KEY}?trace_page=2&amp;token={TOKEN}#trace-tree"' in first
    last = _render(path, 3, TOKEN)
    assert "page 3 of 3" in last and ">N1198<" in last and ">N0<" not in last
    assert "continued from the previous page" in last  # the root's place is kept
    assert "previous" in last and "trace_page=4" not in last


# --- model calls ------------------------------------------------------------------------------


def _log_line(at_ms: int, call: str, body: str = "global cache hit") -> str:
    from datetime import UTC, datetime

    stamp = datetime.fromtimestamp((T0 + at_ms * MS) / 1e9, tz=UTC).isoformat()
    return f"{stamp} INFO:     aigateway.x gateway_call_id={call} trace_id={TID} {body}\n"


def test_a_call_row_expands_to_its_log_lines_matched_by_time(tmp_path: Path) -> None:
    log = _log_line(25, "call_a") + _log_line(45, "call_b")
    html = _render(bundle(tmp_path, run_spans(), gateway_log=log))
    calls = _part(html, '<h3 id="trace-calls"')
    assert calls.count("<details") == 2
    assert "matched by time" in calls
    assert "gateway_call_id=call_a" in calls and "gateway_call_id=call_b" in calls
    assert "openrouter/mistralai/ministral-3b-2512" in calls


def test_an_ambiguous_time_match_says_so(tmp_path: Path) -> None:
    spans = run_spans()
    spans[4] = span("chat2", "cand", CHAT, service=GATEWAY, start=22, end=50, status="unset")
    html = _render(bundle(tmp_path, spans, gateway_log=_log_line(25, "call_a")))
    assert _part(html, '<h3 id="trace-calls"').count("matched by time (ambiguous)") == 2


def test_a_failed_call_row_is_red_and_open(tmp_path: Path) -> None:
    spans = run_spans(candidate_status="error")
    html = _render(bundle(tmp_path, spans, gateway_log=_log_line(25, "call_a")))
    calls = _part(html, '<h3 id="trace-calls"')
    assert calls.count('<tr class="hl-err">') == 2
    assert "<details open>" in calls


# --- checks and notes -------------------------------------------------------------------------


def test_checks_read_in_plain_words_with_held_or_not(tmp_path: Path) -> None:
    trace = trace_doc(hops=[{"name": "engine", "found": False, "lines": 0, "missing_ids": [TID]}])
    html = _render(bundle(tmp_path, run_spans(), trace=trace))
    checks = _part(html, '<h3 id="trace-checks"')
    row = _row_of(checks, "the engine log carries")
    assert 'class="pill fail"' in row and TID in row
    assert 'class="pill pass"' in _row_of(checks, "scheduled and terminated")


def test_the_story_notes_are_shown(tmp_path: Path) -> None:
    spans = [span("run", CLIENT, "url4.run"), span("run2", "ffffffffffffffff", "url4.run")]
    html = _render(bundle(tmp_path, spans))
    assert "no client span derived: 2 spans have a parent outside the bundle" in html


# --- hostile input ----------------------------------------------------------------------------


def test_every_field_from_a_hostile_bundle_is_escaped(tmp_path: Path) -> None:
    evil = "<script>alert(1)</script>"
    attrs = candidate_attrs() | {"gen_ai.request.model": evil, "url4.cache_status": evil}
    spans = [
        span("run", CLIENT, evil, start=0, end=100),
        span("cand", "run", evil, start=10, end=60, attributes=attrs, status="error"),
        span("chat1", "cand", CHAT, service=evil, start=20, end=30),
    ]
    trace = trace_doc(
        trace_ids=[evil], hops=[{"name": evil, "found": False, "missing_ids": [evil]}]
    )
    html = _render(bundle(tmp_path, spans, trace=trace, gateway_log=_log_line(25, evil)))
    assert "<script>" not in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html


def test_section_never_raises(tmp_path: Path) -> None:
    story = ts.build(bundle(tmp_path, run_spans()))
    broken = ts.TraceStory(**{**story.__dict__, "hops": (object(),)})  # type: ignore[arg-type]
    html = th.section(broken, KEY, None)
    assert 'id="trace"' in html and "Trace view could not be shown" in html


# --- the bundle page --------------------------------------------------------------------------


def test_the_bundle_page_has_the_trace_view_and_keeps_the_raw_trace_json(tmp_path: Path) -> None:
    root = tmp_path / "out"
    directory = bundle(root / KEY, run_spans(), recorder=RECORDER)
    (directory / "trace.json").write_text(json.dumps(trace_doc()))
    manager = RunManager(root, workdir=tmp_path, environ={})
    app = create_app(root=root, manager=manager, token=TOKEN, port=9113, notebooks=())
    client = TestClient(app, base_url="http://127.0.0.1:9113", follow_redirects=False)
    page = client.get(f"/bundles/{KEY}?trace_page=1").text
    assert '<section id="trace"><h2>Trace</h2>' in page
    assert "sdk.evaluate" in _part(page, '<section id="trace">', "</section>")
    assert "<summary>Raw trace.json</summary>" in page
    assert "<th>Trace found</th>" not in page  # the old hop table is gone


def test_a_story_that_cannot_be_built_names_the_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "out"
    bundle(root / KEY, run_spans())

    def boom(_directory: Path) -> ts.TraceStory:
        raise LookupError("bad bundle")

    monkeypatch.setattr(ts, "build", boom)
    manager = RunManager(root, workdir=tmp_path, environ={})
    app = create_app(root=root, manager=manager, token=TOKEN, port=9113, notebooks=())
    client = TestClient(app, base_url="http://127.0.0.1:9113", follow_redirects=False)
    trace = _part(client.get(f"/bundles/{KEY}").text, '<section id="trace">', "</section>")
    assert "could not be built from this bundle: LookupError" in trace


def test_a_calls_log_lines_stay_one_per_line(tmp_path: Path) -> None:
    log = _log_line(22, "call_a", "first") + _log_line(24, "call_a", "second")
    html = _render(bundle(tmp_path, run_spans(), gateway_log=log))
    assert "first\n" in _part(html, '<h3 id="trace-calls"')
    assert "2 lines · matched by time" in html
