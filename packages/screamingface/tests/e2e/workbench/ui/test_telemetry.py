"""The bundle page's telemetry loader and its pure view models (unit 6 plan, Task 5).

Bundle files may come from an unzipped CI artifact: every file is untrusted, so the loader
caps, skips what it cannot parse (and counts it), never follows a symlink, and redacts again.
"""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from workbench.ui import telemetry as tm

KEY = "sk-or-v1-" + "a1b2c3d4" * 6  # token-shaped: the redactor masks it whole


def _jsonl(path: Path, rows: list[dict[str, Any]], tail: str = "") -> None:
    path.write_text("".join(json.dumps(r) + "\n" for r in rows) + tail, encoding="utf-8")


def span(
    span_id: str,
    *,
    parent: str | None = None,
    name: str = "op",
    service: str | None = "screamingface-engine",
    start: int = 0,
    end: int = 1_000_000,
    attributes: dict[str, Any] | None = None,
    status: str = "ok",
    message: str = "",
) -> dict[str, Any]:
    return {
        "trace_id": "a" * 32,
        "span_id": span_id,
        "parent_span_id": parent,
        "name": name,
        "kind": "internal",
        "start_ns": start,
        "end_ns": end,
        "status": {"code": status, "message": message},
        "service": service,
        "attributes": attributes or {},
    }


def _event(kind: str, seq: int, **fields: Any) -> dict[str, Any]:
    return {
        "kind": kind,
        "sequence": seq,
        "timestamp": f"2026-10-22T11:56:{seq:02d}+00:00",
    } | fields


# --- loader ---------------------------------------------------------------------------------


def test_loads_every_telemetry_file_of_a_bundle(tmp_path: Path) -> None:
    _jsonl(tmp_path / "events.jsonl", [_event("started", 1), _event("log", 2, body="hi")])
    _jsonl(tmp_path / "spans.jsonl", [span("s1", name="url4.run")])
    (tmp_path / "report.json").write_text(json.dumps({"candidates": []}))
    (tmp_path / "accounting.json").write_text(json.dumps({"candidates": [{"name": "c"}]}))
    (tmp_path / "telemetry.json").write_text(
        json.dumps(
            {
                "events": {"recorded": 2, "dropped": 3, "failed": 1, "cap": 20000, "note": None},
                "files": {"report.json": "written", "accounting.json": "error: boom"},
                "spans": {"copied": 1, "dropped": 4, "cap": 20000, "note": None},
            }
        )
    )
    t = tm.load(tmp_path)
    assert [e["kind"] for e in t.events] == ["started", "log"]
    assert [s["name"] for s in t.spans] == ["url4.run"]
    assert t.report == {"candidates": []}
    assert t.accounting == {"candidates": [{"name": "c"}]}
    assert (t.dropped.events, t.dropped.events_failed, t.dropped.spans) == (3, 1, 4)
    assert "accounting.json: error: boom" in t.notes
    assert t.present


def test_a_bundle_without_telemetry_is_empty_not_an_error(tmp_path: Path) -> None:
    t = tm.load(tmp_path)
    assert (t.events, t.spans, t.report, t.accounting) == ((), (), None, None)
    assert t.dropped.events is None and t.dropped.spans is None  # unknown, never 0
    assert not t.present


def test_the_why_of_missing_spans_is_kept(tmp_path: Path) -> None:
    note = "no spans received for this run's trace ids"
    (tmp_path / "telemetry.json").write_text(json.dumps({"spans": {"copied": 0, "note": note}}))
    assert note in tm.load(tmp_path).notes


def test_unparseable_and_torn_lines_are_skipped_and_counted(tmp_path: Path) -> None:
    _jsonl(tmp_path / "events.jsonl", [_event("log", 1)], tail='{not json\n[1]\n{"kind": "lo')
    t = tm.load(tmp_path)
    assert len(t.events) == 1
    assert t.dropped.unreadable == 3  # bad JSON, a non-object, the torn (newline-less) tail


def test_lines_beyond_the_cap_are_counted_never_silently_lost(tmp_path: Path) -> None:
    _jsonl(tmp_path / "spans.jsonl", [span(f"s{i}") for i in range(7)])
    t = tm.load(tmp_path, cap=5)
    assert len(t.spans) == 5 and t.dropped.over_cap == 2


@pytest.mark.parametrize("name", ["events.jsonl", "report.json"])
def test_a_symlinked_file_is_not_followed(tmp_path: Path, name: str) -> None:
    outside = tmp_path / "outside"
    outside.write_text(json.dumps(_event("log", 1)) + "\n")
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    (bundle / name).symlink_to(outside)
    t = tm.load(bundle)
    assert t.events == () and t.report is None


def test_a_secret_on_disk_is_redacted_again_on_load(tmp_path: Path) -> None:
    # A bundle from elsewhere (an old artifact) may predate the writer's redaction.
    _jsonl(
        tmp_path / "events.jsonl",
        [_event("log", 1, body=f"provider said: bad key {KEY}", attributes={"x-api-key": "zz"})],
    )
    _jsonl(tmp_path / "spans.jsonl", [span("s1", status="error", message=f"401 {KEY}")])
    (tmp_path / "report.json").write_text(json.dumps({"error": f"Bearer {KEY}"}))
    t = tm.load(tmp_path)
    dumped = json.dumps([t.events, t.spans, t.report])
    assert KEY not in dumped and '"zz"' not in dumped


# --- waterfall view model -------------------------------------------------------------------


def test_waterfall_groups_by_service_and_nests_by_parent() -> None:
    spans = (
        span("gw", parent="c1", name="POST /v1/chat/completions", service="aigateway", start=5),
        span("root", name="url4.run", start=0, end=100),
        span("c2", parent="root", name="b", start=20),
        span("c1", parent="root", name="a", start=10),
    )
    w = tm.waterfall(spans)
    assert [(r.service, r.depth, r.name) for r in w.rows] == [
        ("aigateway", 0, "POST /v1/chat/completions"),  # parent in another service: a root here
        ("screamingface-engine", 0, "url4.run"),
        ("screamingface-engine", 1, "a"),
        ("screamingface-engine", 1, "b"),
    ]
    assert (w.start_ns, w.end_ns) == (0, 1_000_000)


def test_waterfall_rows_carry_model_tokens_cache_duration_and_error() -> None:
    attrs = {
        "gen_ai.request.model": "openrouter/x/req",
        "gen_ai.response.model": "openrouter/x/resp",
        "gen_ai.usage.input_tokens": 12,
        "gen_ai.usage.output_tokens": 3,
        "url4.cache_status": "hit",
    }
    (call,) = tm.waterfall((span("s", attributes=attrs, start=0, end=2_500_000),)).rows
    assert (call.model, call.input_tokens, call.output_tokens, call.cache) == (
        "openrouter/x/resp", 12, 3, "hit")  # fmt: skip
    assert call.duration_ns == 2_500_000 and call.error is None
    failed = tm.waterfall((span("e", status="error", message="429 rate limited"),)).rows[0]
    assert failed.error == "429 rate limited"
    typed = tm.waterfall((span("t", status="unset", attributes={"error.type": "Timeout"}),))
    assert typed.rows[0].error == "Timeout"


@pytest.mark.parametrize(
    "bad",
    [
        {"start_ns": None, "end_ns": "x"},
        {"attributes": "nope", "status": [1]},
        {"attributes": {"gen_ai.usage.input_tokens": True, "url4.cache_status": 7}},
        {"span_id": None, "name": 5, "service": 3},
    ],
)
def test_a_malformed_span_degrades_to_unknown_never_raises(bad: dict[str, Any]) -> None:
    (row,) = tm.waterfall((span("s") | bad,)).rows
    assert row.input_tokens is None or isinstance(row.input_tokens, int)
    assert row.cache is None or isinstance(row.cache, str)
    if "start_ns" in bad:
        assert row.duration_ns is None


def test_a_parent_cycle_does_not_hang_or_drop_spans() -> None:
    spans = (span("a", parent="b"), span("b", parent="a"), span("c", parent="c"))
    assert sorted(r.name for r in tm.waterfall(spans).rows) == ["op", "op", "op"]


def test_many_same_named_siblings_fold_into_one_row() -> None:
    kids = tuple(
        span(f"k{i}", parent="root", name="case", start=i, end=i + 10,
             attributes={"gen_ai.usage.input_tokens": 2})
        for i in range(1000)
    )  # fmt: skip
    grandkid = span("g", parent="k999", name="leaf")
    w = tm.waterfall((span("root", name="url4.run", end=2000), *kids, grandkid))
    names = [(r.name, r.folded) for r in w.rows]
    assert names[:4] == [("url4.run", 1), ("case", 1), ("case", 1), ("case", 1)]
    fold = w.rows[4]
    assert (fold.name, fold.folded, fold.hidden) == ("case", 997, 1)
    assert fold.input_tokens == 997 * 2 and (fold.start_ns, fold.end_ns) == (3, 1009)
    assert len(w.rows) == 5
    unfolded = tm.waterfall((span("root"), *kids), unfold=True)
    assert len(unfolded.rows) == 1 + len(kids)


def test_a_fold_with_an_unknown_token_count_is_unknown() -> None:
    kids = [span(f"k{i}", parent="r", name="c", attributes={"gen_ai.usage.input_tokens": 1})
            for i in range(20)]  # fmt: skip
    kids[-1]["attributes"] = {}
    fold = tm.waterfall((span("r"), *kids)).rows[-1]
    assert fold.folded > 1 and fold.input_tokens is None


def test_a_fold_with_an_error_says_how_many_failed() -> None:
    kids = [span(f"k{i}", parent="r", name="c", status="error" if i % 5 == 0 else "ok",
                 message="boom", start=i, end=i + 1) for i in range(20)]  # fmt: skip
    fold = tm.waterfall((span("r"), *kids)).rows[-1]
    assert fold.error == "3 of 17 failed"


# --- usage, accounting, logs, cases ---------------------------------------------------------


def _usage(model: str | None, cost: str | None, tokens: int | None, scope: str = "self") -> Any:
    usage = {"input_tokens": tokens, "output_tokens": 1, "cache_read_tokens": 0,
             "cache_creation_tokens": 0, "reasoning_tokens": 0, "cost_usd": cost}  # fmt: skip
    return _event("usage", 1, scope=scope, provider="openrouter", model=model, usage=usage)


def test_usage_events_sum_by_model_and_unknown_poisons_the_total() -> None:
    events = (
        _usage("m/a", "0.5", 10),
        _usage("m/a", "0.25", 5),
        _usage("m/b", None, None),
        _usage("m/a", "9", 99, scope="subtree"),  # a subtree roll-up would double count
        _event("log", 2),
    )
    rows = {r.model: r for r in tm.usage_by_model(events)}
    assert (rows["m/a"].calls, rows["m/a"].input_tokens, rows["m/a"].cost_usd) == (
        2, 15, Decimal("0.75"))  # fmt: skip
    assert rows["m/b"].cost_usd is None and rows["m/b"].input_tokens is None


def test_log_entries_include_failed_terminations_with_their_error() -> None:
    events = (
        _event("log", 1, severity_text="WARN", body="slow", attributes={"a": 1}),
        _event(
            "terminated",
            2,
            status="failed",
            error={"code": "provider_error", "message": "401 bad key"},
        ),  # fmt: skip
        _event("terminated", 3, status="succeeded", error=None),
        _event("log", 4, severity_text="LOUD", body=None),
    )
    logs = tm.log_entries(events)
    assert [(e.severity, e.body) for e in logs] == [
        ("WARN", "slow"),
        ("ERROR", "terminated failed: provider_error: 401 bad key"),
        ("unknown", ""),
    ]


def test_cases_come_from_every_candidate_of_the_report() -> None:
    report = {
        "candidates": [
            {"name": "c1", "cases": [{"case_id": 1, "status": "scored", "grade": {"score": 1.0},
                                      "stop_reason": "passed", "failures": []}]},
            {"name": "c2", "cases": [{"case_id": "x", "status": "failed", "grade": None,
                                      "failures": [{"code": "e"}, {"code": "f"}]}, 3]},
            "junk",
        ]
    }  # fmt: skip
    cases = tm.cases(report)
    assert [(c.candidate, c.case_id, c.status, c.score, c.failures) for c in cases] == [
        ("c1", "1", "scored", 1.0, 0),
        ("c2", "x", "failed", None, 2),
    ]
    assert tm.cases(None) == [] and tm.cases({"candidates": "no"}) == []
