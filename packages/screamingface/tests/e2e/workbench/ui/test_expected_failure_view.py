"""Expected-failure bundles in the UI (unit 7 plan, Task 4; spec §3.7).

- the verdict reads "expected FAIL ✓", or "expected FAIL ✗" with each reason;
- the Telemetry section lists the failing ``Span`` events and ERROR ``Log`` events (the verdict's
  own predicates) and links each to its gateway log lines by ``gateway_call_id``: exactly when
  the event names one, else every call of the event's trace, by the exact ``trace_id=`` token;
- the run form labels a notebook that declares ``workbench.expect``.

Shapes are the real ones from the Task 2 discovery (ledger), with made-up ids. Everything is
rendered through the real app and must stay escaped.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from workbench.build_notebooks import NOTEBOOK_DIR
from workbench.ui.app import create_app
from workbench.ui.runs import RunManager

TOKEN = "t0k3n-for-tests"
KEY_PATH = "replay/debug_failing_run"
TID = "04fde8793d8a4d70a02d8d88ed92706c"
OTHER = "953f959699b4f69c700565418efc2db3"
CALL_OK = "call_4ad283ffc2f35c190b4435a842363c62"
CALL_FAILED = "call_14edcc75e6cf68620e52148a7606d37d"
CALL_OTHER_RUN = "call_99999999999999999999999999999999"
LABEL = "(fails on purpose: debugging example)"

_GATEWAY_LOG = "\n".join([
    f"INFO:     aigateway.plugins.taxonomy.session gateway_call_id={CALL_OK} trace_id={TID} "
    "usage accounting started provider=openrouter",
    f"INFO:     aigateway.plugins.taxonomy.session gateway_call_id={CALL_FAILED} trace_id={TID} "
    "usage accounting started provider=openrouter",
    f"INFO:     aigateway.routes.chat_cache_stage gateway_call_id={CALL_OK} trace_id={TID} "
    "global cache hit provider=openrouter model='openrouter/mistralai/ministral-3b-2512'",
    # decoys: another run's trace, and a token that only CONTAINS the id
    f"INFO:     aigateway.x gateway_call_id={CALL_OTHER_RUN} trace_id={OTHER} other run",
    f"INFO:     aigateway.x gateway_call_id={CALL_OTHER_RUN} parent_trace_id={TID} decoy",
]) + "\n"  # fmt: skip

_EXPECT = {"outcome": "fail", "failure_codes": ["upstream_error"], "stage": "candidate"}
_OBSERVED = {
    "failures": [{"code": "upstream_error", "stage": "candidate"}],
    "error_telemetry": {"spans": 1, "logs": 2},
}


def _trace(passed: bool, reasons: list[str], **extra: Any) -> dict[str, Any]:
    return {
        "passed": passed,
        "trace_ids": [TID],
        "reasons": reasons,
        "hops": [],
        "expect": _EXPECT,
        "observed": _OBSERVED,
    } | extra


def _traceparent(tid: str = TID) -> str:
    return f"00-{tid}-3f494e4cddd618c3-01"


def _log(seq: int, number: int, text: str, body: str, **attributes: Any) -> dict[str, Any]:
    return {"kind": "log", "sequence": seq, "timestamp": f"2026-10-22T14:37:{seq:02d}+00:00",
            "traceparent": _traceparent(), "severity_number": number, "severity_text": text,
            "body": body, "attributes": attributes}  # fmt: skip


def _span(seq: int, status: str, model: str, **extra: Any) -> dict[str, Any]:
    return {"kind": "span", "sequence": seq, "traceparent": _traceparent(),
            "name": "/benchmarks/candidate", "operation": "RelUrlNode", "status": status,
            "provider": "openrouter", "request_model": model, "response_model": model,
            "finish_reasons": ["stop"], "refusal": None, "cache_status": "hit"} | extra  # fmt: skip


_EVENTS = [
    _log(1, 9, "INFO", "Model call completed",
         **{"sf.activity.model_id": "openrouter/mistralai/ministral-3b-2512"}),
    _log(2, 17, "ERROR", "Model call failed",
         **{"sf.activity.model_id": "openrouter/openai/gpt-5.5",
            "sf.activity.failure_code": "internal_error"}),
    _log(3, 17, "ERROR", "Answering failed", **{"sf.activity.kind": "answering"}),
    _span(4, "error", "openrouter/mistralai/ministral-3b-2512"),
    _span(5, "ok", "openrouter/healthy/never-an-error"),
]  # fmt: skip


@pytest.fixture
def root(tmp_path: Path) -> Path:
    return tmp_path / "out"


@pytest.fixture
def client(root: Path, tmp_path: Path) -> TestClient:
    root.mkdir(parents=True, exist_ok=True)
    manager = RunManager(root, workdir=tmp_path, environ={})
    app = create_app(
        root=root,
        manager=manager,
        token=TOKEN,
        port=9114,
        notebooks=("debug_failing_run", "quickstart"),
        expected_failures=("debug_failing_run",),
    )
    return TestClient(app, base_url="http://127.0.0.1:9114", follow_redirects=False)


def _bundle(
    root: Path,
    trace: dict[str, Any],
    events: list[dict[str, Any]] | None = None,
    gateway: str | None = None,
) -> None:
    d = root / KEY_PATH
    (d / "logs").mkdir(parents=True, exist_ok=True)
    (d / "trace.json").write_text(json.dumps(trace))
    if events is not None:
        (d / "events.jsonl").write_text("".join(json.dumps(e) + "\n" for e in events))
    if gateway is not None:
        (d / "logs" / "aigateway.txt").write_text(gateway)


def _page(client: TestClient) -> str:
    response = client.get(f"/bundles/{KEY_PATH}")
    assert response.status_code == 200
    return response.text


def _errors(page: str) -> str:
    return page.split('id="errors"', 1)[1].split('id="waterfall"', 1)[0]


def _row_of(html: str, needle: str) -> str:
    start = html.index(needle)
    return html[html.rindex("<tr", 0, start) : html.index("</tr>", start)]


# --- verdict ----------------------------------------------------------------------------------


def test_an_expected_failure_that_held_reads_expected_fail_check(
    root: Path, client: TestClient
) -> None:
    _bundle(root, _trace(True, []))
    page = _page(client)
    assert '<span class="pill pass">expected FAIL ✓</span>' in page
    assert ">PASS<" not in page
    assert "upstream_error" in page and "candidate" in page  # declared and observed
    index = client.get("/").text
    assert "expected FAIL ✓" in index and ">PASS<" not in index


def test_an_expected_failure_that_went_red_reads_cross_with_its_reason(
    root: Path, client: TestClient
) -> None:
    why = "wrong failure code: expected ['upstream_error'], observed ['<b>rate_limited</b>']"
    _bundle(root, _trace(False, [why]))
    page = _page(client)
    assert '<span class="pill fail">expected FAIL ✗</span>' in page
    assert "✗ wrong failure code" in page
    assert "<b>rate_limited</b>" not in page and "&lt;b&gt;rate_limited&lt;/b&gt;" in page
    index = client.get("/").text
    assert "expected FAIL ✗" in index


def test_an_ordinary_bundle_keeps_plain_pass(root: Path, client: TestClient) -> None:
    _bundle(root, {"passed": True, "trace_ids": [TID], "reasons": []})
    page = _page(client)
    assert '<span class="pill pass">PASS</span>' in page and "expected FAIL" not in page


@pytest.mark.parametrize("expect", ["<i>junk</i>", 3, ["x"], {"invalid": "'<i>'"}])
def test_a_malformed_declaration_renders_as_expected_failure_and_escaped(
    root: Path, client: TestClient, expect: object
) -> None:
    _bundle(root, _trace(False, ["malformed workbench.expect: <i>"], expect=expect, observed=7))
    page = _page(client)
    assert "expected FAIL ✗" in page and "<i>" not in page


# --- telemetry: failing spans and ERROR logs --------------------------------------------------


def test_failing_spans_and_error_logs_are_listed_and_highlighted(
    root: Path, client: TestClient
) -> None:
    _bundle(root, _trace(True, []), _EVENTS, _GATEWAY_LOG)
    errors = _errors(_page(client))
    assert "Model call failed" in errors and "Answering failed" in errors
    assert "openrouter/openai/gpt-5.5" in errors and "internal_error" in errors
    assert "/benchmarks/candidate" in errors and "ministral-3b-2512" in errors
    assert "Model call completed" not in errors  # INFO is not an error
    assert "never-an-error" not in errors  # an ok span is not an error
    assert errors.count('class="hl-err"') == 3


def test_an_error_log_row_in_the_log_table_is_highlighted(root: Path, client: TestClient) -> None:
    _bundle(root, _trace(True, []), _EVENTS, _GATEWAY_LOG)
    logs = _page(client).split('id="tlogs"', 1)[1]
    assert 'class="hl-err"' in _row_of(logs, "Model call failed")
    assert 'class="hl-err"' not in _row_of(logs, "Model call completed")


def test_an_event_without_a_call_id_links_every_call_of_its_trace_exactly(
    root: Path, client: TestClient
) -> None:
    _bundle(root, _trace(True, []), _EVENTS, _GATEWAY_LOG)
    page = _page(client)
    row = _row_of(_errors(page), "Model call failed")
    assert f'href="#gw-{CALL_OK}"' in row and f'href="#gw-{CALL_FAILED}"' in row
    assert CALL_OTHER_RUN not in row  # another trace, and a parent_trace_id= decoy
    assert "by trace id" in row
    calls = page.split('id="gateway-calls"', 1)[1].split("</table>", 1)[0]
    assert f'id="gw-{CALL_OK}"' in calls and f'id="gw-{CALL_FAILED}"' in calls
    assert "global cache hit" in _row_of(calls, f'id="gw-{CALL_OK}"')
    assert CALL_OTHER_RUN not in calls


def test_an_event_naming_its_call_id_links_only_that_call(root: Path, client: TestClient) -> None:
    named = _log(9, 17, "ERROR", "Gateway refused", gateway_call_id=CALL_FAILED)
    _bundle(root, _trace(True, []), [named], _GATEWAY_LOG)
    row = _row_of(_errors(_page(client)), "Gateway refused")
    assert f'href="#gw-{CALL_FAILED}"' in row
    assert f'href="#gw-{CALL_OK}"' not in row and "by trace id" not in row


def test_a_call_id_absent_from_the_gateway_log_says_so(root: Path, client: TestClient) -> None:
    named = _log(9, 17, "ERROR", "Gateway refused", gateway_call_id="call_deadbeef")
    _bundle(root, _trace(True, []), [named], _GATEWAY_LOG)
    row = _row_of(_errors(_page(client)), "Gateway refused")
    assert "call_deadbeef" in row and 'href="#gw-call_deadbeef"' not in row
    assert "not in the gateway log" in row


def test_no_gateway_log_says_so(root: Path, client: TestClient) -> None:
    _bundle(root, _trace(True, []), _EVENTS, None)
    errors = _errors(_page(client))
    assert "no gateway log" in errors and 'href="#gw-' not in errors


def test_hostile_values_stay_escaped(root: Path, client: TestClient) -> None:
    evil_call = 'call_x"><script>alert(1)</script>'
    attributes = {"sf.activity.model_id": "<img src=x>", "gateway_call_id": evil_call}
    hostile = _log(9, 17, "ERROR", "<script>alert(2)</script>", **attributes)
    gateway = (
        f"INFO: a gateway_call_id={evil_call} trace_id={TID} <script>alert(3)</script>\n"
        + _GATEWAY_LOG
    )
    _bundle(root, _trace(True, []), [hostile], gateway)
    page = _page(client)
    assert "<script>alert" not in page and "<img src=x>" not in page
    assert 'id="gw-call_x"' not in page  # an id that is no plain token is never an anchor


def test_no_error_events_means_no_errors_subsection(root: Path, client: TestClient) -> None:
    _bundle(root, _trace(True, []), [_EVENTS[0], _EVENTS[4]], _GATEWAY_LOG)
    assert 'id="errors"' not in _page(client)


# --- run form ---------------------------------------------------------------------------------


def test_the_run_form_labels_a_notebook_that_fails_on_purpose(client: TestClient) -> None:
    page = client.get("/", params={"token": TOKEN}).text
    form = page.split('action="/runs"', 1)[1].split("</form>", 1)[0]
    debug = form.split('value="debug_failing_run"', 1)[1].split("</label>", 1)[0]
    quick = form.split('value="quickstart"', 1)[1].split("</label>", 1)[0]
    assert LABEL in debug and LABEL not in quick


def test_expected_failure_stems_reads_the_notebook_metadata() -> None:
    from workbench.ui.__main__ import expected_failure_stems

    stems = expected_failure_stems(NOTEBOOK_DIR)
    assert "debug_failing_run" in stems and "quickstart" not in stems


def test_expected_failure_stems_skips_an_unreadable_notebook(tmp_path: Path) -> None:
    from workbench.ui.__main__ import expected_failure_stems

    (tmp_path / "broken.ipynb").write_text("{not json")
    (tmp_path / "odd.ipynb").write_text(json.dumps({"metadata": {"workbench": "x"}}))
    (tmp_path / "fails.ipynb").write_text(
        json.dumps({"metadata": {"workbench": {"expect": {"outcome": "fail"}}}})
    )
    assert expected_failure_stems(tmp_path) == frozenset({"fails"})
