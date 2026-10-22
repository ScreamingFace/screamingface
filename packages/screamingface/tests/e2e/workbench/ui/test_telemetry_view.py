"""The bundle page's Telemetry section (unit 6 plan, Task 5; Review Focus 2 and 5).

Rendered through the real app (``/bundles/<key>``) from files on disk, the way a run writes them.
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from workbench.ui import telemetry as tm
from workbench.ui.app import create_app
from workbench.ui.runs import RunManager
from workbench.ui.test_telemetry import KEY, recursion_limit_1000, span  # noqa: F401

TOKEN = "t0k3n-for-tests"
KEY_PATH = "replay/quickstart"


@pytest.fixture
def root(tmp_path: Path) -> Path:
    out = tmp_path / "out"
    (out / KEY_PATH).mkdir(parents=True)
    (out / KEY_PATH / "trace.json").write_text(json.dumps({"passed": True, "trace_ids": []}))
    return out


@pytest.fixture
def client(root: Path, tmp_path: Path) -> TestClient:
    manager = RunManager(root, workdir=tmp_path, environ={})
    app = create_app(root=root, manager=manager, token=TOKEN, port=9113, notebooks=())
    return TestClient(app, base_url="http://127.0.0.1:9113", follow_redirects=False)


def _write(root: Path, name: str, rows: list[dict[str, Any]] | dict[str, Any]) -> None:
    path = root / KEY_PATH / name
    if isinstance(rows, list):
        path.write_text("".join(json.dumps(r) + "\n" for r in rows))
    else:
        path.write_text(json.dumps(rows))


def _section(page: str) -> str:
    return page.split('id="telemetry"', 1)[1].split('id="executed-notebook"', 1)[0]


def _get(client: TestClient, query: str = "") -> str:
    response = client.get(f"/bundles/{KEY_PATH}{query}")
    assert response.status_code == 200
    return _section(response.text)


def _log(seq: int, severity: str, body: str) -> dict[str, Any]:
    return {"kind": "log", "sequence": seq, "timestamp": f"2026-10-22T11:56:{seq:02d}+00:00",
            "severity_text": severity, "body": body, "attributes": {}}  # fmt: skip


def test_no_telemetry_says_so(client: TestClient) -> None:
    section = _get(client)
    assert "No telemetry in this bundle" in section


def test_waterfall_is_inline_svg_grouped_by_service(root: Path, client: TestClient) -> None:
    call = {"gen_ai.response.model": "openrouter/x/phi", "gen_ai.usage.input_tokens": 12,
            "gen_ai.usage.output_tokens": 3, "url4.cache_status": "hit"}  # fmt: skip
    _write(root, "spans.jsonl", [
        span("r", name="url4.run", start=0, end=10_000_000),
        span("c", parent="r", name="/benchmarks/candidate", start=1_000_000, end=3_500_000,
             attributes=call),
        span("g", parent="c", name="POST /v1/chat/completions", service="aigateway",
             start=1_500_000, end=3_000_000, status="error", message="upstream 502"),
    ])  # fmt: skip
    section = _get(client)
    assert "<svg" in section and "<rect" in section
    assert section.index(">aigateway<") < section.index(">screamingface-engine<")
    assert "openrouter/x/phi" in section and ">12<" in section and ">3<" in section
    assert ">hit<" in section and "2.5 ms" in section
    assert "upstream 502" in section and 'class="pill fail"' in section


def test_unknown_values_read_unknown_never_zero_or_none(root: Path, client: TestClient) -> None:
    _write(root, "spans.jsonl", [span("r", attributes={"gen_ai.request.model": "m"},
                                      start=None, end=None)])  # type: ignore[arg-type]  # fmt: skip
    _write(root, "events.jsonl", [{"kind": "usage", "sequence": 1, "scope": "self",
                                   "model": "m", "usage": {"cost_usd": None}}])  # fmt: skip
    section = _get(client)
    rows = re.findall(r"<tr[^>]*>(.*?)</tr>", section, re.S)
    model_rows = [r for r in rows if ">m<" in r]
    assert model_rows and all("unknown" in r for r in model_rows)
    assert ">None<" not in section and "$None" not in section


def test_everything_is_escaped(root: Path, client: TestClient) -> None:
    evil = "<script>alert(1)</script>"
    _write(root, "spans.jsonl", [span("r", name=evil, service=evil,
                                      attributes={"gen_ai.request.model": evil})])  # fmt: skip
    _write(root, "events.jsonl", [_log(1, "INFO", evil)])
    _write(root, "report.json", {"candidates": [{"name": evil, "cases": [
        {"case_id": evil, "status": evil}]}]})  # fmt: skip
    section = _get(client)
    assert "<script>" not in section and "&lt;script&gt;" in section


def test_no_secret_from_a_provider_error_reaches_the_page(root: Path, client: TestClient) -> None:
    _write(root, "spans.jsonl", [span("r", status="error", message=f"401 invalid key {KEY}")])
    _write(root, "events.jsonl", [
        _log(1, "ERROR", f"provider error: Authorization: Bearer {KEY}"),
        {"kind": "terminated", "sequence": 2, "status": "failed",
         "error": {"code": "provider_error", "message": f"bad key {KEY}"}},
    ])  # fmt: skip
    page = client.get(f"/bundles/{KEY_PATH}").text
    assert KEY not in page and KEY[:16] not in page
    assert "provider_error" in page  # the error itself still shows


def test_usage_and_cost_by_model_and_by_stage(root: Path, client: TestClient) -> None:
    usage = {"input_tokens": 10, "output_tokens": 2, "cost_usd": "0.0421"}
    _write(root, "events.jsonl", [{"kind": "usage", "sequence": 1, "scope": "self",
                                   "model": "openrouter/x/phi", "usage": usage}])  # fmt: skip
    cache = {"hits": 1, "misses": 1, "bypasses": 0, "unknown": 0}
    summary = {"usage": {"input_tokens": 7, "output_tokens": 1, "cost_usd": "0.0100"},
               "calls": 2, "cache": cache}  # fmt: skip
    _write(root, "accounting.json", {"candidates": [{
        "name": "best", "unattributed_cost_usd": None, "consistent": True,
        "by_model": [{"model": "openrouter/x/phi"} | summary, {"model": None} | summary],
        "by_stage": [{"stage": "generation"} | summary],
    }]})  # fmt: skip
    section = _get(client)
    assert "$0.0421" in section and "$0.0100" in section
    assert ">generation<" in section and ">best<" in section
    assert "(anonymous)" in section  # the None model bucket
    assert "unattributed cost: unknown · consistent: yes" in section


def test_log_list_filters_by_severity_without_javascript(root: Path, client: TestClient) -> None:
    _write(root, "events.jsonl", [_log(1, "DEBUG", "dbg"), _log(2, "INFO", "inf"),
                                  _log(3, "WARN", "wrn"), _log(4, "ERROR", "err")])  # fmt: skip
    section = _get(client)
    assert "<script" not in section  # the filter is CSS (:has), all rows show without it
    for severity in ("DEBUG", "INFO", "WARN", "ERROR"):
        assert f'data-sev="{severity}"' in section
    assert re.search(r'<input type="radio" name="sev"[^>]*id="sev-warn"', section)
    page = client.get(f"/bundles/{KEY_PATH}").text
    assert '#tlogs:has(#sev-warn:checked) tr[data-sev="INFO"]' in page


def test_cases_table(root: Path, client: TestClient) -> None:
    _write(root, "report.json", {"candidates": [{"name": "best", "cases": [
        {"case_id": 7, "status": "scored", "grade": {"score": 0.5}, "stop_reason": "passed",
         "finish_reason": "stop", "rounds_executed": 1, "failures": []}]}]})  # fmt: skip
    section = _get(client)
    row = re.search(r"<tr><td>best</td>(.*?)</tr>", section)
    assert row and ">7<" in row.group(1) and ">scored<" in row.group(1) and ">0.5<" in row.group(1)


def test_dropped_counts_and_notes_are_shown(root: Path, client: TestClient) -> None:
    _write(root, "telemetry.json", {
        "events": {"recorded": 20000, "dropped": 17, "failed": 0, "cap": 20000, "note": None},
        "spans": {"copied": 0, "dropped": 0, "cap": 20000,
                  "note": "no spans received for this run's trace ids"},
        "files": {"report.json": "no report"},
    })  # fmt: skip
    section = _get(client)
    assert "17 events dropped" in section
    assert "no spans received for this run&#x27;s trace ids" in section
    assert "report.json: no report" in section


def test_a_thousand_spans_paginate_and_fold_quickly(root: Path, client: TestClient) -> None:
    roots = [span(f"r{i}", name=f"root-{i}", start=i, end=i + 5) for i in range(450)]
    kids = [span(f"k{i}", parent="r0", name="case", start=i, end=i + 1) for i in range(1200)]
    _write(root, "spans.jsonl", roots + kids)
    began = time.monotonic()
    first = _get(client, f"?token={TOKEN}")
    assert time.monotonic() - began < 5
    assert first.count('class="wf-row"') == 200  # one page
    assert "page 1 of 3" in first
    assert "1197 more" in first  # the 1200 "case" siblings fold to 3 + one row
    assert f'href="/bundles/{KEY_PATH}?spans_page=2&amp;token={TOKEN}#waterfall"' in first
    third = _get(client, f"?spans_page=3&token={TOKEN}")
    assert third.count('class="wf-row"') == 454 - 400 and "page 3 of 3" in third
    unfolded = _get(client, "?unfold=1&spans_page=999")
    assert "page 9 of 9" in unfolded  # 1650 rows; an out-of-range page is clamped
    assert _get(client, "?spans_page=nope").count('class="wf-row"') == 200


# --- hostile input (review of Task 5) -------------------------------------------------------


def _deep(depth: int) -> str:
    return '{"a":' + "[" * depth + "]" * depth + "}"


@pytest.mark.usefixtures("recursion_limit_1000")
@pytest.mark.parametrize("depth", [2_000, 100_000])
def test_a_too_deep_file_never_takes_the_page_down(
    root: Path, client: TestClient, depth: int
) -> None:
    bundle = root / KEY_PATH
    for name in ("spans.jsonl", "events.jsonl"):
        (bundle / name).write_text(_deep(depth) + "\n")
    for name in ("report.json", "accounting.json"):
        (bundle / name).write_text(_deep(depth))
    response = client.get(f"/bundles/{KEY_PATH}")
    assert response.status_code == 200
    assert "Trace chain" in response.text and "2 unreadable lines skipped" in response.text


def test_a_huge_timestamp_or_score_reads_unknown(root: Path, client: TestClient) -> None:
    _write(root, "spans.jsonl", [span("s1", start=0, end=10**400)])
    _write(root, "report.json", {"candidates": [{"name": "best", "cases": [
        {"case_id": 1, "grade": {"score": 10**400}},
        {"case_id": 2, "grade": {"score": float("nan")}},
        {"case_id": 3, "grade": {"score": float("inf")}}]}]})  # fmt: skip
    section = _get(client)
    assert "nan" not in section and "inf<" not in section
    assert section.count("<td class='num'>unknown</td>") >= 3


def test_an_oversized_report_is_named_not_silently_missing(
    root: Path, client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(tm, "JSON_BYTES_CAP", 64)
    _write(root, "report.json", {"candidates": [], "pad": "x" * 100})
    assert "report.json: over the page&#x27;s read cap" in _get(client)


def test_a_truncated_jsonl_reads_at_least(
    root: Path, client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(tm, "JSONL_BYTES_CAP", 600)
    _write(root, "spans.jsonl", [span(f"s{i}") for i in range(20)])
    section = _get(client)
    assert "at least 1 lines beyond the page&#x27;s read cap" in section
    assert "spans.jsonl is truncated" in section


def test_nested_log_attributes_render_as_json(root: Path, client: TestClient) -> None:
    entry = _log(1, "INFO", "hi") | {"attributes": {"k": {"a": [1, "b"]}, "n": 3}}
    _write(root, "events.jsonl", [entry])
    section = _get(client)
    assert "k={&quot;a&quot;: [1, &quot;b&quot;]}" in section and "n=3" in section
