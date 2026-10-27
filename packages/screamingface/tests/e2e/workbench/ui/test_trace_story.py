"""The Trace view's model (u8 plan, Task 2): one story of a run across every hop.

Each rule is pinned on a small bundle written into ``tmp_path``. Bundle files are untrusted:
a corrupt parent chain, a hostile log line or an over-cap file must degrade, never raise.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from workbench.ui import trace_story as ts

TID = "4bf92f3577b34da6a3ce929d0e0e4736"
CLIENT = "00f067aa0ba902b7"  # the notebook's traceparent span id: in no span file
T0 = int(datetime(2026, 10, 27, 12, 0, tzinfo=UTC).timestamp()) * 1_000_000_000
MS = 1_000_000
ENGINE = "screamingface-engine"
GATEWAY = "aigateway"
CHAT = "POST /v1/chat/completions"
MODEL = "openrouter/mistralai/ministral-3b-2512"


def span(
    span_id: str,
    parent: str | None,
    name: str,
    *,
    service: str = ENGINE,
    start: int = 0,
    end: int = 10,
    attributes: dict[str, Any] | None = None,
    status: str = "ok",
) -> dict[str, Any]:
    """A span as ``spans.jsonl`` holds it; ``start``/``end`` are milliseconds after ``T0``."""
    return {
        "trace_id": TID,
        "span_id": span_id,
        "parent_span_id": parent,
        "name": name,
        "kind": "internal",
        "start_ns": T0 + start * MS,
        "end_ns": T0 + end * MS,
        "status": {"code": status, "message": "error" if status == "error" else ""},
        "service": service,
        "attributes": attributes or {},
    }


def candidate_attrs(cache: str = "hit") -> dict[str, Any]:
    return {
        "gen_ai.request.model": MODEL,
        "gen_ai.provider.name": "openrouter",
        "gen_ai.usage.input_tokens": 12,
        "gen_ai.usage.output_tokens": 34,
        "gen_ai.response.finish_reasons": ["stop"],
        "url4.cache_status": cache,
    }


def run_spans(*, cache: str = "hit", candidate_status: str = "ok") -> list[dict[str, Any]]:
    """The real replay shape: url4.run (parent: the client) → … → candidate → 2 gateway calls."""
    return [
        span("run", CLIENT, "url4.run", start=0, end=100),
        span("proc", "run", "ProcessNode", start=1, end=99),
        span(
            "cand",
            "proc",
            "/benchmarks/candidate",
            start=10,
            end=60,
            attributes=candidate_attrs(cache),
            status=candidate_status,
        ),
        span("chat1", "cand", CHAT, service=GATEWAY, start=20, end=30, status="unset"),
        span("chat2", "cand", CHAT, service=GATEWAY, start=40, end=50, status="unset"),
        span("seal", "run", "POST /v1/frozen-copies/x/seal", service=GATEWAY, start=95, end=98),
    ]


def trace_doc(**extra: Any) -> dict[str, Any]:
    return {
        "trace_ids": [TID],
        "hops": [
            {"name": "engine", "found": True, "lines": 4, "missing_ids": []},
            {"name": "aigateway", "found": True, "lines": 3, "missing_ids": []},
        ],
        "lifecycle": {"scheduled": True, "terminated": True},
        "unattributed_gateway_lines": 0,
        "passed": True,
        "reasons": [],
    } | extra


def bundle(
    root: Path,
    spans: list[dict[str, Any]] | None = None,
    *,
    trace: dict[str, Any] | None = None,
    recorder: dict[str, Any] | None = None,
    accounting: dict[str, Any] | None = None,
    gateway_log: str | None = None,
    events: list[dict[str, Any]] | None = None,
) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    if spans is not None:
        (root / "spans.jsonl").write_text("".join(json.dumps(s) + "\n" for s in spans))
    (root / "trace.json").write_text(json.dumps(trace_doc() if trace is None else trace))
    if recorder is not None:
        (root / "recorder.json").write_text(json.dumps(recorder))
    if accounting is not None:
        (root / "accounting.json").write_text(json.dumps(accounting))
    if gateway_log is not None:
        (root / "logs").mkdir()
        (root / "logs" / "aigateway.txt").write_text(gateway_log)
    if events is not None:
        (root / "events.jsonl").write_text("".join(json.dumps(e) + "\n" for e in events))
    return root


def walk(roots: tuple[ts.Node, ...]) -> list[tuple[int, ts.Node]]:
    """Every node with its depth, depth first (iterative: the test must not recurse either)."""
    out: list[tuple[int, ts.Node]] = []
    stack = [(0, n) for n in reversed(roots)]
    while stack:
        depth, node = stack.pop()
        out.append((depth, node))
        stack.extend((depth + 1, c) for c in reversed(node.children))
    return out


def find(roots: tuple[ts.Node, ...], span_id: str) -> ts.Node:
    return next(n for _, n in walk(roots) if n.span.get("span_id") == span_id)


def ids(nodes: tuple[ts.Node, ...]) -> list[str]:
    return [str(n.span.get("span_id")) for n in nodes]


# --- tree -------------------------------------------------------------------------------------


def test_spans_nest_by_parent_across_services(tmp_path: Path) -> None:
    story = ts.build(bundle(tmp_path, run_spans()))
    candidate = find(story.roots, "cand")
    assert ids(candidate.children) == ["chat1", "chat2"]  # gateway spans under the engine span
    assert [c.span["service"] for c in candidate.children] == [GATEWAY, GATEWAY]
    assert ids(find(story.roots, "run").children) == ["proc", "seal"]  # in start order


# --- the client span (Review Focus 2) ---------------------------------------------------------


def test_one_url4_run_orphan_gets_a_synthetic_sdk_evaluate_root(tmp_path: Path) -> None:
    recorder = {"first_event_ns": T0 - 5 * MS, "last_event_ns": T0 + 105 * MS}
    story = ts.build(bundle(tmp_path, run_spans(), recorder=recorder))
    (root,) = story.roots
    assert root.synthetic
    assert root.span["name"] == "sdk.evaluate"
    assert root.span["span_id"] == CLIENT  # the orphan's parent: url4.run now hangs off it
    assert (root.span["start_ns"], root.span["end_ns"]) == (T0 - 5 * MS, T0 + 105 * MS)
    assert ids(root.children) == ["run"]
    assert not any(n.synthetic for _, n in walk(root.children))
    assert story.wall_ns == 110 * MS


def test_the_synthetic_span_is_never_written_back(tmp_path: Path) -> None:
    path = bundle(tmp_path, run_spans())
    before = (path / "spans.jsonl").read_text()
    ts.build(path)
    assert (path / "spans.jsonl").read_text() == before


def test_without_recorder_times_the_client_span_bounds_are_unknown(tmp_path: Path) -> None:
    story = ts.build(bundle(tmp_path, run_spans()))
    (root,) = story.roots
    assert root.synthetic and root.span["start_ns"] is None and root.span["end_ns"] is None
    assert any("client span" in n and "unknown" in n for n in story.notes)


@pytest.mark.parametrize(
    ("spans", "reason"),
    [
        ([span("run", None, "url4.run")], "no span has a parent outside"),
        (
            [span("run", CLIENT, "url4.run"), span("run2", "ffffffffffffffff", "url4.run")],
            "2 spans have a parent outside",
        ),
        ([span("x", CLIENT, "ProcessNode")], "not url4.run"),
    ],
    ids=["no-orphan", "two-orphans", "orphan-not-url4-run"],
)
def test_no_client_span_is_invented_unless_exactly_one_url4_run_orphan(
    tmp_path: Path, spans: list[dict[str, Any]], reason: str
) -> None:
    story = ts.build(bundle(tmp_path, spans))
    assert not any(n.synthetic for _, n in walk(story.roots))
    assert any(reason in n for n in story.notes), story.notes


# --- cycles (Review Focus 3) ------------------------------------------------------------------


def test_a_parent_cycle_terminates_and_its_member_becomes_a_root(tmp_path: Path) -> None:
    spans = [span("a", "b", "A", start=1), span("b", "a", "B", start=2)]
    story = ts.build(bundle(tmp_path, spans))
    assert ids(story.roots) == ["a"]
    assert ids(story.roots[0].children) == ["b"]
    assert story.roots[0].children[0].children == ()  # the back edge to a is not followed
    assert any("cycle" in n and "'A'" in n for n in story.notes), story.notes


def test_a_self_parent_is_a_root_with_a_note(tmp_path: Path) -> None:
    story = ts.build(bundle(tmp_path, [span("s", "s", "Self")]))
    assert ids(story.roots) == ["s"]
    assert story.roots[0].children == ()
    assert any("its own parent" in n for n in story.notes), story.notes


def test_a_deep_chain_builds_without_recursion(tmp_path: Path) -> None:
    chain = [span("s0", None, "N")] + [span(f"s{i}", f"s{i - 1}", "N") for i in range(1, 5_000)]
    story = ts.build(bundle(tmp_path, chain))
    assert len(walk(story.roots)) == 5_000


# --- collapse ---------------------------------------------------------------------------------


def test_nine_sibling_text_nodes_collapse_to_one_node(tmp_path: Path) -> None:
    spans = [span("p", None, "StructNode")]
    spans += [span(f"t{i}", "p", "TextNode", start=i) for i in range(9)]
    story = ts.build(bundle(tmp_path, spans))
    (collapsed,) = story.roots[0].children
    assert collapsed.collapsed == 9
    assert collapsed.span["span_id"] == "t0"


def test_an_error_span_is_never_collapsed_away(tmp_path: Path) -> None:
    spans = [span("p", None, "StructNode")]
    spans += [span(f"t{i}", "p", "TextNode", start=i) for i in range(9)]
    spans.append(span("bad", "p", "TextNode", start=20, status="error"))
    story = ts.build(bundle(tmp_path, spans))
    kids = story.roots[0].children
    assert [k.collapsed for k in kids] == [9, 1]
    assert kids[1].span["span_id"] == "bad"


def test_a_few_siblings_or_ones_with_children_stay_apart(tmp_path: Path) -> None:
    spans = [span("p", None, "P")]
    spans += [span(f"t{i}", "p", "TextNode", start=i) for i in range(2)]
    spans += [span(f"c{i}", "p", "CollectNode", start=10 + i) for i in range(6)]
    spans += [span(f"g{i}", f"c{i}", "Leaf", start=20 + i) for i in range(6)]
    story = ts.build(bundle(tmp_path, spans))
    assert all(k.collapsed == 1 for k in story.roots[0].children)
    assert len(story.roots[0].children) == 8


# --- calls ------------------------------------------------------------------------------------


def _accounting(*rows: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema": "workbench.accounting.v1",
        "candidates": [{"name": "c", "by_model": list(rows)}],
    }


def test_each_chat_completion_span_is_a_call_described_by_its_engine_parent(tmp_path: Path) -> None:
    story = ts.build(bundle(tmp_path, run_spans()))
    assert [c.span_id for c in story.calls] == ["chat1", "chat2"]
    call = story.calls[0]
    assert (call.model, call.provider, call.cache) == (MODEL, "openrouter", "hit")
    assert (call.tokens_in, call.tokens_out) == (12, 34)
    assert call.latency_ns == 10 * MS
    assert call.status == "ok" and call.failure_code is None
    assert call.spend is None  # replay: accounting holds no rows — unknown, never $0


def test_spend_comes_from_accounting_by_model_when_one_call_used_it(tmp_path: Path) -> None:
    spans = run_spans()[:4]  # one chat call
    row = {"model": MODEL, "calls": 1, "usage": {"cost_usd": "0.0042"}}
    story = ts.build(bundle(tmp_path, spans, accounting=_accounting(row)))
    assert story.calls[0].spend == Decimal("0.0042")


def test_a_model_total_shared_by_several_calls_is_not_split(tmp_path: Path) -> None:
    row = {"model": MODEL, "calls": 2, "usage": {"cost_usd": "0.0042"}}
    story = ts.build(bundle(tmp_path, run_spans(), accounting=_accounting(row)))
    assert [c.spend for c in story.calls] == [None, None]  # a guessed split would be invented


def test_a_failing_engine_parent_makes_its_calls_failed_with_the_observed_code(
    tmp_path: Path,
) -> None:
    trace = trace_doc(
        expect={"outcome": "fail", "failure_codes": ["upstream_error"], "stage": "candidate"},
        observed={"failures": [{"code": "upstream_error", "stage": "candidate"}]},
    )
    story = ts.build(bundle(tmp_path, run_spans(candidate_status="error"), trace=trace))
    assert {(c.status, c.failure_code) for c in story.calls} == {("error", "upstream_error")}
    gateway = next(h for h in story.hops if h.name == "aigateway")
    assert gateway.state == "fail" and gateway.reason is not None
    assert "upstream_error" in gateway.reason


def test_calls_past_the_cap_are_counted(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ts, "CALLS_CAP", 1)
    story = ts.build(bundle(tmp_path, run_spans()))
    assert len(story.calls) == 1 and story.cut["calls"] == 1


# --- log lines to calls (Review Focus 4) ------------------------------------------------------


def _line(at_ms: int, call: str, body: str = "global cache hit", tid: str = TID) -> str:
    stamp = datetime.fromtimestamp((T0 + at_ms * MS) / 1e9, tz=UTC).isoformat()
    return f"{stamp} INFO:     aigateway.x gateway_call_id={call} trace_id={tid} {body}\n"


def test_a_line_inside_exactly_one_call_window_matches_by_time(tmp_path: Path) -> None:
    log = _line(25, "call_a") + _line(45, "call_b")
    story = ts.build(bundle(tmp_path, run_spans(), gateway_log=log))
    first, second = story.calls
    assert first.match == "time" and len(first.log_lines) == 1 and "call_a" in first.log_lines[0]
    assert second.match == "time" and "call_b" in second.log_lines[0]


def test_a_line_inside_two_windows_shows_under_both_as_ambiguous(tmp_path: Path) -> None:
    spans = run_spans()
    spans[4] = span("chat2", "cand", CHAT, service=GATEWAY, start=22, end=50, status="unset")
    story = ts.build(bundle(tmp_path, spans, gateway_log=_line(25, "call_a")))
    assert [c.match for c in story.calls] == ["time-ambiguous", "time-ambiguous"]
    assert all(len(c.log_lines) == 1 for c in story.calls)


def test_a_trace_id_substring_or_a_line_without_time_never_matches(tmp_path: Path) -> None:
    log = _line(25, "call_a", tid=TID + "x")
    log += f"INFO:     aigateway.x gateway_call_id=call_c trace_id={TID} no stamp\n"
    story = ts.build(bundle(tmp_path, run_spans(), gateway_log=log))
    assert [c.match for c in story.calls] == ["none", "none"]
    assert all(c.log_lines == () for c in story.calls)
    assert any("1 gateway log line" in n for n in story.notes), story.notes


def test_a_gateway_call_id_on_the_span_matches_by_call_id(tmp_path: Path) -> None:
    spans = run_spans()
    spans[3]["attributes"] = {"gateway_call_id": "call_b"}
    log = _line(45, "call_b") + _line(45, "call_c")  # call_b's time would point at chat2
    story = ts.build(bundle(tmp_path, spans, gateway_log=log))
    first, second = story.calls
    assert first.match == "call_id" and first.log_lines == (_line(45, "call_b").strip(),)
    assert second.match == "time" and second.log_lines == (_line(45, "call_c").strip(),)


# --- hops (Review Focus 1) --------------------------------------------------------------------


def hop(story: ts.TraceStory, name: str) -> ts.Hop:
    return next(h for h in story.hops if h.name == name)


def test_five_hops_in_order_with_replay_states(tmp_path: Path) -> None:
    events = [{"kind": "started", "sequence": 1}]
    recorder = {"first_event_ns": T0, "last_event_ns": T0 + 100 * MS}
    story = ts.build(bundle(tmp_path, run_spans(), events=events, recorder=recorder))
    assert [h.name for h in story.hops] == [
        "notebook",
        "engine",
        "aigateway",
        "provider",
        "scoreboard",
    ]
    assert hop(story, "notebook").state == "ok" and hop(story, "notebook").spans == 1
    assert hop(story, "notebook").latency_ns == 100 * MS
    engine = hop(story, "engine")
    assert (engine.state, engine.spans, engine.log_lines) == ("ok", 3, 4)
    assert engine.latency_ns == 100 * MS
    gateway = hop(story, "aigateway")
    assert (gateway.state, gateway.spans, gateway.log_lines) == ("ok", 3, 3)
    provider = hop(story, "provider")
    assert (provider.state, provider.reason) == ("grey", "none on replay: served from cache")
    assert (hop(story, "scoreboard").state, hop(story, "scoreboard").reason) == (
        "grey",
        "not instrumented",
    )


def test_a_cache_miss_puts_the_provider_on_the_path(tmp_path: Path) -> None:
    story = ts.build(bundle(tmp_path, run_spans(cache="miss")))
    assert hop(story, "provider").state == "ok"


def test_engine_fails_when_trace_json_did_not_find_its_trace_id(tmp_path: Path) -> None:
    trace = trace_doc()
    trace["hops"][0] = {"name": "engine", "found": False, "lines": 0, "missing_ids": [TID]}
    story = ts.build(bundle(tmp_path, run_spans(), trace=trace))
    assert hop(story, "engine").state == "fail"


def test_with_no_spans_hops_follow_trace_json_and_the_tree_says_so(tmp_path: Path) -> None:
    trace = trace_doc()
    trace["hops"][1] = {"name": "aigateway", "found": False, "lines": 0, "missing_ids": [TID]}
    story = ts.build(bundle(tmp_path, None, trace=trace))
    assert story.roots == () and story.calls == ()
    assert hop(story, "engine").state == "ok"
    assert hop(story, "aigateway").state == "fail"
    assert hop(story, "notebook").state == "grey"
    assert "no spans received" in story.notes
    assert story.verdict == "pass"  # the verdict is trace.json's, never re-judged here


def test_an_empty_bundle_is_all_grey_and_unknown(tmp_path: Path) -> None:
    tmp_path.joinpath("trace.json").write_text("[1, 2]")  # not an object: unreadable
    story = ts.build(tmp_path)
    assert story.verdict == "unknown" and story.trace_ids == ()
    assert {h.state for h in story.hops} == {"grey"}
    assert story.wall_ns is None


# --- checks -----------------------------------------------------------------------------------


def test_each_trace_json_fact_becomes_one_plain_check(tmp_path: Path) -> None:
    trace = trace_doc(
        unattributed_gateway_lines=2, lifecycle={"scheduled": True, "terminated": False}
    )
    story = ts.build(bundle(tmp_path, run_spans(), trace=trace))
    held = [c.held for c in story.checks]
    assert len(story.checks) == 4 and held == [True, True, False, False]
    assert "engine" in story.checks[0].rule and "4" in story.checks[0].evidence
    assert "terminated: no" in story.checks[2].evidence
    assert "2" in story.checks[3].evidence


def test_an_expected_failure_adds_its_expect_observed_check(tmp_path: Path) -> None:
    trace = trace_doc(
        expect={"outcome": "fail", "failure_codes": ["upstream_error"], "stage": "candidate"},
        observed={"failures": [{"code": "upstream_error", "stage": "candidate"}]},
    )
    story = ts.build(bundle(tmp_path, run_spans(), trace=trace))
    check = story.checks[-1]
    assert check.held and "upstream_error" in check.rule
    assert "observed upstream_error at candidate" in check.evidence


def test_an_expected_failure_that_did_not_happen_is_a_failed_check(tmp_path: Path) -> None:
    trace = trace_doc(
        expect={"outcome": "fail", "failure_codes": ["upstream_error"], "stage": "candidate"},
        observed={"failures": []},
    )
    story = ts.build(bundle(tmp_path, run_spans(), trace=trace))
    assert not story.checks[-1].held
    assert "no failures" in story.checks[-1].evidence


# --- caps and hostile input -------------------------------------------------------------------


def test_spans_past_the_read_cap_are_counted(tmp_path: Path) -> None:
    spans = [span(f"{i:016x}", None, "N") for i in range(20_001)]
    story = ts.build(bundle(tmp_path, spans))
    assert story.cut["spans"] == 1
    assert len(walk(story.roots)) == 20_000


def test_hostile_shapes_degrade_to_unknown(tmp_path: Path) -> None:
    bad = span("x", None, "url4.run")
    bad |= {"start_ns": "soon", "attributes": [1], "status": "broken", "parent_span_id": 7}
    chat = span("c", "x", CHAT, service=GATEWAY)
    chat["end_ns"] = 10**30
    trace = {"trace_ids": "nope", "hops": [1, {"name": 3}], "lifecycle": [], "passed": "yes"}
    story = ts.build(bundle(tmp_path, [bad, chat], trace=trace, recorder={"first_event_ns": True}))
    assert story.verdict == "unknown"
    assert story.calls[0].latency_ns is None
    assert story.trace_ids == (TID,)  # from the spans when trace.json has none
