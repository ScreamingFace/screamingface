"""Workbench UI app (unit 4 plan, Task 5): routes, loopback/token/CSP guards, pages, ``main``.

Runs use an injected ``spawn`` that runs a tiny Python script (no pytest-in-pytest, no stack);
the script may write a bundle into ``SCREAMINGFACE_WORKBENCH_OUT`` like the real lane does.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import time
from collections.abc import Callable, Iterator, Mapping
from pathlib import Path
from typing import Any

import nbformat
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from workbench.ui import __main__ as entry
from workbench.ui.app import create_app
from workbench.ui.runs import RunManager

PORT = 9112
BASE = f"http://127.0.0.1:{PORT}"
TOKEN = "t0k3n-for-tests"
NOTEBOOKS = ("quickstart", "judge-panel")
TRACE_ID = "a" * 32
DEFAULT_DATA_DIR = Path("/home/tester/.screamingface")

Spawn = Callable[[list[str], dict[str, str], Path], "subprocess.Popen[str]"]

_WRITE_BUNDLE = """
import json, os, pathlib
d = pathlib.Path(os.environ["SCREAMINGFACE_WORKBENCH_OUT"]) / "replay" / "quickstart"
(d / "logs").mkdir(parents=True)
(d / "trace.json").write_text(json.dumps({"passed": True, "trace_ids": [], "reasons": []}))
print("wrote", flush=True)
"""


def _spawn(script: str, calls: list[list[str]]) -> Spawn:
    def spawn(argv: list[str], env: dict[str, str], cwd: Path) -> subprocess.Popen[str]:
        calls.append(argv)
        return subprocess.Popen(
            [sys.executable, "-c", script],
            env=env,
            cwd=cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            start_new_session=True,
        )

    return spawn


class _Rig:
    def __init__(self, tmp_path: Path, script: str, environ: Mapping[str, str]) -> None:
        self.root = tmp_path / "out"
        self.root.mkdir()
        self.calls: list[list[str]] = []
        self.manager = RunManager(
            self.root,
            workdir=tmp_path,
            environ=environ,
            spawn=_spawn(script, self.calls),
            interrupt_grace=5.0,
            terminate_grace=5.0,
        )
        self.app: FastAPI = create_app(
            root=self.root,
            manager=self.manager,
            token=TOKEN,
            port=PORT,
            notebooks=NOTEBOOKS,
            default_data_dir=DEFAULT_DATA_DIR,
        )
        self.client = TestClient(self.app, base_url=BASE, follow_redirects=False)

    def start(self, **form: str | list[str]) -> str:
        data: dict[str, Any] = {"target": "replay", "token": TOKEN} | form
        response = self.client.post("/runs", data=data)
        assert response.status_code == 303, response.text
        match = re.fullmatch(r"/runs/([0-9a-z-]+)\?token=.+", response.headers["location"])
        assert match, response.headers["location"]
        return match.group(1)

    def events(self, run_id: str, **headers: str) -> str:
        with self.client.stream("GET", f"/runs/{run_id}/events", headers=headers) as response:
            assert response.status_code == 200
            assert response.headers["content-type"].startswith("text/event-stream")
            return "".join(response.iter_text())

    def wait(self, run_id: str, timeout: float = 20.0) -> None:
        deadline = time.monotonic() + timeout
        while self.manager.get(run_id).returncode is None:
            assert time.monotonic() < deadline, "run did not end"
            time.sleep(0.05)


@pytest.fixture
def rig_factory(tmp_path: Path) -> Iterator[Callable[..., _Rig]]:
    made: list[_Rig] = []

    def make(script: str = "print('a'); print('b')", environ: Mapping[str, str] | None = None):
        rig = _Rig(tmp_path, script, environ or {})
        made.append(rig)
        return rig

    yield make
    for rig in made:  # never leave a sleeping fake run behind
        for run_id in list(rig.app.state.run_ids):
            rig.manager.cancel(run_id)


@pytest.fixture
def rig(rig_factory: Callable[..., _Rig]) -> _Rig:
    return rig_factory()


def _bundle(root: Path, rel: str, trace: object | None, logs: Mapping[str, str] = {}) -> Path:
    d = root / rel
    (d / "logs").mkdir(parents=True)
    if trace is not None:
        (d / "trace.json").write_text(trace if isinstance(trace, str) else json.dumps(trace))
    for name, text in logs.items():
        (d / "logs" / f"{name}.txt").write_text(text)
    return d


def _notebook(directory: Path, html_output: str) -> None:
    cell = nbformat.v4.new_code_cell("x")
    cell.outputs = [nbformat.v4.new_output("display_data", data={"text/html": html_output})]
    nbformat.write(nbformat.v4.new_notebook(cells=[cell]), directory / "executed.ipynb")


_FULL_TRACE: dict[str, Any] = {
    "passed": False,
    "trace_ids": [TRACE_ID],
    "reasons": ["trace chain incomplete: aigateway: trace aaa absent"],
    "hops": [
        {"name": "engine", "found": True, "lines": 3, "missing_ids": []},
        {"name": "aigateway", "found": False, "lines": 0, "missing_ids": [TRACE_ID]},
    ],
    "lifecycle": {"scheduled": True, "terminated": False},
    "unattributed_gateway_lines": 2,
    "result": {
        "trace_ids": [TRACE_ID],
        "candidates": {
            "best_open_source": {
                "score": 0.75,
                "cache_hits": 4,
                "cache_saved_cost_usd": "0.0123",
            }
        },
    },
    "error": "AssertionError: the client minted no trace id",
}


# --- guards ---------------------------------------------------------------------------------


@pytest.mark.parametrize("host", ["evil.example:9112", "127.0.0.1:9999", "localhost", "evil"])
def test_wrong_host_is_rejected(rig: _Rig, host: str) -> None:
    assert rig.client.get("/", headers={"host": host}).status_code == 400
    response = rig.client.post("/runs", data={"target": "replay", "token": TOKEN},
                               headers={"host": host})  # fmt: skip
    assert response.status_code == 400
    assert rig.calls == []


def test_localhost_with_the_port_is_accepted(rig: _Rig) -> None:
    assert rig.client.get("/", headers={"host": f"localhost:{PORT}"}).status_code == 200


@pytest.mark.parametrize(
    "send",
    [
        {"data": {"target": "replay"}},
        {"data": {"target": "replay", "token": "wrong"}},
        {"json": {"target": "replay"}},
        {"json": {"target": "replay"}, "headers": {"x-workbench-token": "wrong"}},
        # A cross-site form: the browser sends its Origin, never our token.
        {"data": {"target": "replay"}, "headers": {"origin": "https://evil.example"}},
    ],
)
def test_post_without_token_is_forbidden(rig: _Rig, send: dict[str, Any]) -> None:
    response = rig.client.post("/runs", **send)
    assert response.status_code == 403
    assert rig.calls == []


def test_cancel_without_token_is_forbidden(rig_factory: Callable[..., _Rig]) -> None:
    rig = rig_factory(script="import time; print('up', flush=True); time.sleep(30)")
    run_id = rig.start()
    assert rig.client.post(f"/runs/{run_id}/cancel").status_code == 403
    assert rig.client.post(f"/runs/{run_id}/cancel", data={"token": "x"}).status_code == 403
    assert rig.manager.get(run_id).cancelled is False


def test_responses_carry_csp_and_frame_deny(rig: _Rig) -> None:
    for response in (rig.client.get("/"), rig.client.get("/bundles/nope"),
                     rig.client.post("/runs")):  # fmt: skip
        csp = response.headers["content-security-policy"]
        assert "default-src 'none'" in csp
        assert "form-action 'self'" in csp and "base-uri 'none'" in csp
        assert "connect-src 'self'" in csp
        assert response.headers["x-frame-options"] == "DENY"
        assert response.headers["referrer-policy"] == "no-referrer"


def test_the_token_is_embedded_only_when_the_page_was_opened_with_it(rig: _Rig) -> None:
    with_token = rig.client.get("/", params={"token": TOKEN}).text
    assert f'name="token" value="{TOKEN}"' in with_token
    for page in (rig.client.get("/").text, rig.client.get("/?token=forged").text):
        assert "forged" not in page and TOKEN not in page
        assert "startup URL" in page  # tells the human how to get a launch-capable page


# --- index ----------------------------------------------------------------------------------


def test_index_lists_bundles_and_the_run_form(rig: _Rig) -> None:
    _bundle(rig.root, "replay/quickstart",
            {"passed": True, "trace_ids": [TRACE_ID], "reasons": []})  # fmt: skip
    _bundle(rig.root, "runs/r1/replay/judge-panel",
            {"passed": False, "trace_ids": [], "reasons": ["no <b>trace</b> id"]})  # fmt: skip
    page = rig.client.get("/", params={"token": TOKEN}).text
    assert '<form method="post" action="/runs"' in page
    assert 'value="replay"' in page and 'value="local"' in page
    for stem in NOTEBOOKS:
        assert f'name="notebooks" value="{stem}"' in page
    assert 'href="/bundles/replay/quickstart?token=' in page
    assert 'href="/bundles/runs/r1/replay/judge-panel?token=' in page
    assert 'class="pill pass"' in page and 'class="pill fail"' in page
    assert TRACE_ID in page
    assert "no &lt;b&gt;trace&lt;/b&gt; id" in page and "<b>trace</b>" not in page


def test_index_links_runs_found_on_disk(rig: _Rig) -> None:
    _bundle(rig.root, "runs/20261017-101500-ab12/replay/quickstart", {"passed": True})
    page = rig.client.get("/").text
    assert 'href="/runs/20261017-101500-ab12"' in page


def test_index_disables_local_with_the_reason_when_the_key_is_absent(rig: _Rig) -> None:
    page = rig.client.get("/", params={"token": TOKEN}).text
    local = re.search(r'<input[^>]*value="local"[^>]*>', page)
    assert local and "disabled" in local.group(0)
    assert "OPENROUTER_API_KEY is not set" in page


def test_index_offers_local_with_the_paid_checkbox_when_the_key_is_set(
    rig_factory: Callable[..., _Rig],
) -> None:
    rig = rig_factory(environ={"OPENROUTER_API_KEY": "sk-never-shown-0000000000000000"})
    page = rig.client.get("/", params={"token": TOKEN}).text
    local = re.search(r'<input[^>]*value="local"[^>]*>', page)
    assert local and "disabled" not in local.group(0)
    assert 'name="confirm_paid"' in page and "spends real tokens" in page
    assert "sk-never-shown" not in page


def test_index_shows_the_active_run_and_disables_launching(
    rig_factory: Callable[..., _Rig],
) -> None:
    rig = rig_factory(script="import time; print('up', flush=True); time.sleep(30)")
    run_id = rig.start()
    page = rig.client.get("/", params={"token": TOKEN}).text
    assert f'href="/runs/{run_id}?token={TOKEN}"' in page
    assert re.search(r'<button[^>]*type="submit"[^>]*disabled', page)


# --- launching ------------------------------------------------------------------------------


def test_post_with_token_starts_and_redirects(rig: _Rig) -> None:
    run_id = rig.start(notebooks="quickstart")
    assert rig.calls and rig.calls[0][-1].endswith("::test_notebook[replay-quickstart]")
    stream = rig.events(run_id)
    assert "data: a\n" in stream and "data: b\n" in stream
    end = re.search(r"event: end\ndata: (.+)\n\n", stream)
    assert end and json.loads(end.group(1)) == {"returncode": 0, "cancelled": False}
    assert stream.index("data: b") < stream.index("event: end")


def test_json_post_with_the_header_token_starts(rig: _Rig) -> None:
    response = rig.client.post(
        "/runs",
        json={"target": "replay", "notebooks": ["quickstart"]},
        headers={"x-workbench-token": TOKEN},
    )
    assert response.status_code == 303
    assert response.headers["location"].startswith("/runs/")


def test_busy_returns_409(rig_factory: Callable[..., _Rig]) -> None:
    rig = rig_factory(script="import time; print('up', flush=True); time.sleep(30)")
    rig.start()
    response = rig.client.post("/runs", data={"target": "replay", "token": TOKEN})
    assert response.status_code == 409
    assert "already active" in response.text
    assert len(rig.calls) == 1


def test_local_without_key_returns_400_with_reason(rig: _Rig) -> None:
    response = rig.client.post(
        "/runs", data={"target": "local", "confirm_paid": "on", "token": TOKEN}
    )
    assert response.status_code == 400
    assert "OPENROUTER_API_KEY" in response.text
    assert rig.calls == []


def test_local_without_the_paid_confirmation_returns_400(
    rig_factory: Callable[..., _Rig],
) -> None:
    rig = rig_factory(environ={"OPENROUTER_API_KEY": "k"})
    response = rig.client.post("/runs", data={"target": "local", "token": TOKEN})
    assert response.status_code == 400
    assert "spends real tokens" in response.text
    assert rig.calls == []


@pytest.mark.parametrize(
    "send",
    [
        {"data": {"target": "replay", "notebooks": "nosuch"}},
        {"data": {"target": "prod"}},
        {"data": {}},
        {"json": {"target": "replay", "notebooks": "quickstart"}},
        {"json": {"target": "replay", "confirm_paid": "yes"}},
        {"json": ["replay"]},
        {"content": b"{not json", "headers": {"content-type": "application/json"}},
    ],
)
def test_malformed_run_requests_return_400(rig: _Rig, send: dict[str, Any]) -> None:
    headers = {"x-workbench-token": TOKEN} | send.pop("headers", {})
    response = rig.client.post("/runs", headers=headers, **send)
    assert response.status_code == 400
    assert rig.calls == []


def test_an_oversized_body_is_refused(rig: _Rig) -> None:
    response = rig.client.post(
        "/runs",
        content=b"target=replay&x=" + b"y" * 200_000,
        headers={
            "x-workbench-token": TOKEN,
            "content-type": "application/x-www-form-urlencoded",
        },  # fmt: skip
    )
    assert response.status_code == 413
    assert rig.calls == []


# --- run page and stream --------------------------------------------------------------------


def test_running_page_streams_and_offers_cancel(rig_factory: Callable[..., _Rig]) -> None:
    rig = rig_factory(script="import time; print('up', flush=True); time.sleep(30)")
    run_id = rig.start()
    page = rig.client.get(f"/runs/{run_id}", params={"token": TOKEN}).text
    assert '<pre id="log"' in page
    assert "EventSource" in page
    assert f'action="/runs/{run_id}/cancel"' in page
    assert "running" in page


def test_a_running_notebook_shows_an_elapsed_time_indicator(
    rig_factory: Callable[..., _Rig],
) -> None:
    # The tester must see the run is alive between pytest's collection and the result,
    # without log_cli (which would print around the redaction hook).
    script = "import time; print('collecting ... collected 1 item', flush=True); time.sleep(30)"
    rig = rig_factory(script=script)
    run_id = rig.start(notebooks="quickstart")
    assert next(rig.manager.follow(run_id, 0)).endswith("collected 1 item")
    page = rig.client.get(f"/runs/{run_id}", params={"token": TOKEN}).text
    assert re.search(r'id="progress"[^>]*>running quickstart… 00:0\d<', page)
    assert "setInterval" in page
    with rig.client.stream("GET", f"/runs/{run_id}/events") as response:
        lines = response.iter_lines()
        progress = next(ln for ln in lines if ln.startswith("event: progress"))
        data = json.loads(next(lines).removeprefix("data: "))
    assert progress == "event: progress"
    assert data["running"] == "quickstart" and data["since"] > 0


def test_cancel_with_token_ends_the_run_and_redirects(rig_factory: Callable[..., _Rig]) -> None:
    rig = rig_factory(script="import time; print('up', flush=True); time.sleep(30)")
    run_id = rig.start()
    response = rig.client.post(f"/runs/{run_id}/cancel", data={"token": TOKEN})
    assert response.status_code == 303
    assert response.headers["location"].startswith(f"/runs/{run_id}?token=")
    stream = rig.events(run_id)  # ends: the cancel tore the run down
    end = re.search(r"event: end\ndata: (.+)\n\n", stream)
    assert end and json.loads(end.group(1))["cancelled"] is True
    page = rig.client.get(f"/runs/{run_id}").text
    assert "cancelled" in page and "EventSource" not in page


_SLEEP_IN_DATA_DIR = """
import os, pathlib, time
out = pathlib.Path(os.environ["SCREAMINGFACE_WORKBENCH_OUT"])
(out / "pytest-tmp" / "workbench-target0" / "data").mkdir(parents=True)
print("up", flush=True)
time.sleep(30)
"""


def _cancel_and_wait(rig: _Rig, run_id: str) -> str:
    assert next(rig.manager.follow(run_id, 0)) == "up"  # the script is past its setup
    response = rig.client.post(f"/runs/{run_id}/cancel", data={"token": TOKEN})
    assert response.status_code == 303
    rig.events(run_id)  # ends once the cancel finished
    return rig.client.get(f"/runs/{run_id}", params={"token": TOKEN}).text


def test_a_cancelled_local_run_names_the_command_that_stops_its_runtime(
    rig_factory: Callable[..., _Rig],
) -> None:
    # `screamingface up` detaches into its own session: if teardown did not reach `down`, the
    # runtime keeps its ports (and the tester must know how to stop it).
    rig = rig_factory(script=_SLEEP_IN_DATA_DIR, environ={"OPENROUTER_API_KEY": "k"})
    run_id = rig.start(target="local", confirm_paid="on")
    page = _cancel_and_wait(rig, run_id)
    data_dir = rig.root / "runs" / run_id / "pytest-tmp" / "workbench-target0" / "data"
    assert "runtime may still be up" in page
    assert f"screamingface down --data-dir {data_dir}" in page


def test_a_cancelled_local_run_without_a_known_data_dir_names_the_default(
    rig_factory: Callable[..., _Rig],
) -> None:
    rig = rig_factory(
        script="import time; print('up', flush=True); time.sleep(30)",
        environ={"OPENROUTER_API_KEY": "k"},
    )
    run_id = rig.start(target="local", confirm_paid="on")
    page = _cancel_and_wait(rig, run_id)
    assert "runtime may still be up" in page
    assert f"screamingface down --data-dir {DEFAULT_DATA_DIR}" in page


def test_a_killed_replay_run_warns_that_teardown_may_not_have_run(
    rig_factory: Callable[..., _Rig],
) -> None:
    script = (
        "import signal, time; signal.signal(signal.SIGINT, signal.SIG_IGN); "
        "signal.signal(signal.SIGTERM, signal.SIG_IGN); print('up', flush=True); time.sleep(60)"
    )
    rig = rig_factory(script=script)
    rig.manager._graces = (0.2, 0.2)  # pyright: ignore[reportPrivateUsage]
    run_id = rig.start()
    page = _cancel_and_wait(rig, run_id)
    assert "runtime may still be up" in page
    assert f"screamingface down --data-dir {DEFAULT_DATA_DIR}" in page


def test_a_replay_run_cancelled_cleanly_has_no_stop_note(
    rig_factory: Callable[..., _Rig],
) -> None:
    rig = rig_factory(script="import time; print('up', flush=True); time.sleep(30)")
    run_id = rig.start()
    page = _cancel_and_wait(rig, run_id)
    assert "cancelled" in page and "screamingface down" not in page


def test_cancelling_a_finished_run_says_there_is_nothing_to_cancel(rig: _Rig) -> None:
    run_id = rig.start()
    rig.wait(run_id)
    response = rig.client.post(f"/runs/{run_id}/cancel", data={"token": TOKEN})
    assert response.status_code == 409
    assert "already finished — nothing to cancel" in response.text
    assert f'href="/runs/{run_id}?token={TOKEN}"' in response.text
    assert not rig.manager.get(run_id).cancelled


def test_a_crashed_run_shows_partial_output_and_exit_code(
    rig_factory: Callable[..., _Rig],
) -> None:
    rig = rig_factory(script="print('partial <out>', flush=True); raise SystemExit(3)")
    run_id = rig.start()
    rig.wait(run_id)
    page = rig.client.get(f"/runs/{run_id}").text
    assert "partial &lt;out&gt;" in page
    assert "exit 3" in page
    assert "EventSource" not in page  # never left hanging on "running"


def test_a_finished_run_links_the_bundles_it_wrote(rig_factory: Callable[..., _Rig]) -> None:
    rig = rig_factory(script=_WRITE_BUNDLE)
    run_id = rig.start()
    rig.wait(run_id)
    page = rig.client.get(f"/runs/{run_id}").text
    assert f'href="/bundles/runs/{run_id}/replay/quickstart"' in page
    assert "exit 0" in page


def test_a_run_from_an_earlier_ui_process_shows_its_bundles(rig: _Rig) -> None:
    _bundle(rig.root, "runs/20261017-101500-ab12/replay/quickstart", {"passed": True})
    page = rig.client.get("/runs/20261017-101500-ab12").text
    assert 'href="/bundles/runs/20261017-101500-ab12/replay/quickstart"' in page
    assert "earlier" in page


@pytest.mark.parametrize(
    "run_id", ["nope", "20261017-101500-zzzz", "..%2F..", "20261017-101500-ab13"]
)
def test_unknown_runs_are_404(rig: _Rig, run_id: str) -> None:
    assert rig.client.get(f"/runs/{run_id}").status_code == 404
    assert rig.client.get(f"/runs/{run_id}/events").status_code == 404
    response = rig.client.post(f"/runs/{run_id}/cancel", data={"token": TOKEN})
    assert response.status_code == 404


def test_events_resume_after_the_last_event_id(rig_factory: Callable[..., _Rig]) -> None:
    rig = rig_factory(script="print('a'); print('b'); print('c')")
    run_id = rig.start()
    rig.wait(run_id)
    full = rig.events(run_id)
    assert "id: 1\ndata: a\n" in full and "id: 3\ndata: c\n" in full
    resumed = rig.events(run_id, **{"last-event-id": "2"})
    assert "data: a" not in resumed and "data: b" not in resumed and "data: c\n" in resumed
    with rig.client.stream("GET", f"/runs/{run_id}/events?from=1") as response:
        body = "".join(response.iter_text())
    assert "data: a" not in body and "data: b\n" in body


def test_a_carriage_return_cannot_forge_an_event(rig_factory: Callable[..., _Rig]) -> None:
    rig = rig_factory(script="import sys; sys.stdout.write('x\\revent: end\\n')")
    run_id = rig.start()
    stream = rig.events(run_id)
    # Output only ever lands inside a data field: no line of the stream starts a new field.
    assert re.findall(r"^event: .*$", stream, re.M) == ["event: end"]
    assert stream.rstrip().endswith('"cancelled": false}')


def test_shutdown_cancels_an_active_run(rig_factory: Callable[..., _Rig]) -> None:
    rig = rig_factory(script="import time; print('up', flush=True); time.sleep(30)")
    with rig.client:
        run_id = rig.start()
    done = rig.manager.get(run_id)
    assert done.cancelled and done.returncode is not None


# --- bundle page ----------------------------------------------------------------------------


def test_bundle_page_shows_hops_logs_and_a_sandboxed_notebook(rig: _Rig) -> None:
    d = _bundle(rig.root, "replay/quickstart", _FULL_TRACE,
                {"engine": "trace_id=aaa <tag>", "aigateway": "nothing"})  # fmt: skip
    _notebook(d, "<b>score 0.9</b>")
    page = rig.client.get("/bundles/replay/quickstart").text
    assert 'sandbox=""' in page
    assert "score 0.9" in page  # inside the escaped srcdoc
    assert "<b>score 0.9</b>" not in page
    assert "<td>engine</td>" in page and "<td>aigateway</td>" in page
    assert "trace_id=aaa &lt;tag&gt;" in page and "<tag>" not in page
    assert "<details" in page  # logs are collapsible
    assert 'class="pill fail"' in page
    assert "trace chain incomplete" in page
    assert "best_open_source" in page and "0.0123" in page and "0.75" in page
    assert "AssertionError: the client minted no trace id" in page


def _candidate_rows(page: str) -> dict[str, list[str]]:
    body = page.split("<th>Candidate</th>", 1)[1].split("</table>", 1)[0]
    rows = re.findall(r"<tr>(.*?)</tr>", body)
    cells = [re.findall(r"<td>(.*?)</td>", row) for row in rows]
    return {c[0]: c[1:] for c in cells if c}


def test_the_bundle_page_shows_each_candidates_spend(rig: _Rig) -> None:
    trace = _FULL_TRACE | {
        "result": {
            "candidates": {
                "priced": {"score": 0.5, "cost_usd": "0.0421", "cache_hits": 2,
                           "cache_saved_cost_usd": "0.0100"},
                "free": {"score": 0.5, "cost_usd": "0", "cache_hits": 0,
                         "cache_saved_cost_usd": "0"},
            }
        }
    }  # fmt: skip
    _bundle(rig.root, "local/quickstart", trace)
    page = rig.client.get("/bundles/local/quickstart").text
    assert "<th>Spend (USD)</th>" in page
    rows = _candidate_rows(page)
    assert rows["priced"] == ["0.5", "$0.0421", "2", "$0.0100"]
    assert rows["free"] == ["0.5", "$0", "0", "$0"]  # a real zero stays zero
    assert "Total spend: <b>$0.0421</b>" in page


@pytest.mark.parametrize(
    "money",
    [
        {"cost_usd": None, "cache_saved_cost_usd": None},
        {},
        {"cost_usd": "lots", "cache_saved_cost_usd": 3},
    ],
    ids=["null", "absent", "malformed"],
)
def test_unknown_spend_renders_as_unknown_never_zero_or_none(
    rig: _Rig, money: dict[str, Any]
) -> None:
    trace = _FULL_TRACE | {
        "result": {
            "candidates": {
                "unpriced": {"score": None, "cache_hits": None} | money,
                "priced": {"score": 0.5, "cost_usd": "0.0421"},
            }
        }
    }
    _bundle(rig.root, "local/quickstart", trace)
    page = rig.client.get("/bundles/local/quickstart").text
    spend, saved = _candidate_rows(page)["unpriced"][1], _candidate_rows(page)["unpriced"][3]
    assert spend == saved == "unknown"
    # One unknown amount makes the total unknown too: a partial sum would read as complete.
    assert "Total spend: <b>unknown</b>" in page
    assert "None" not in page.split("<th>Candidate</th>", 1)[1].split("</table>", 1)[0]


def test_a_hostile_notebook_output_stays_inert(rig: _Rig) -> None:
    d = _bundle(rig.root, "replay/evil", {"passed": True})
    _notebook(d, '<script>alert(1)</script><img src=x onerror="alert(2)">'
                 '<a href="javascript:alert(3)">x</a>')  # fmt: skip
    page = rig.client.get("/bundles/replay/evil").text
    assert "<script>alert" not in page
    assert "<img src=x" not in page and '<a href="javascript:' not in page
    frames = re.findall(r"<iframe[^>]*>", page)
    assert len(frames) == 1 and 'sandbox=""' in frames[0]


def test_a_bundle_without_a_notebook_says_so(rig: _Rig) -> None:
    _bundle(rig.root, "replay/quickstart", {"passed": True})
    page = rig.client.get("/bundles/replay/quickstart").text
    assert "no executed notebook" in page
    assert "<iframe" not in page


@pytest.mark.parametrize(
    "trace",
    [
        "{not json",
        json.dumps({"passed": "yes", "hops": "nope", "result": [1], "reasons": "x"}),
        json.dumps(
            {
                "passed": True,
                "hops": [1, {"name": 2}, {"found": "y"}],
                "result": {"candidates": {"x": 3, "y": {"score": [1]}}},
            }
        ),  # fmt: skip
        None,
    ],
)
def test_a_malformed_bundle_shows_as_unreadable(rig: _Rig, trace: str | None) -> None:
    d = _bundle(rig.root, "replay/broken", trace, {"engine": "x"})
    if trace is None:
        _notebook(d, "only a notebook")
    assert 'href="/bundles/replay/broken"' in rig.client.get("/").text
    response = rig.client.get("/bundles/replay/broken")
    assert response.status_code == 200
    assert "<pre>x</pre>" in response.text  # the log still shows


def test_missing_and_malformed_traces_are_unreadable_on_index_and_page(rig: _Rig) -> None:
    _bundle(rig.root, "replay/broken", "{not json")
    for page in (rig.client.get("/").text, rig.client.get("/bundles/replay/broken").text):
        assert 'class="pill unknown"' in page and "unreadable" in page


@pytest.mark.parametrize(
    "path",
    [
        "/bundles/..%2F..%2Fetc",
        "/bundles/%2Fetc%2Fpasswd",
        "/bundles/replay/..%2F..%2Fx",
        "/bundles/replay",
        "/bundles/nope",
    ],  # fmt: skip
)
def test_bundle_key_traversal_is_404(rig: _Rig, path: str) -> None:
    _bundle(rig.root, "replay/quickstart", {"passed": True})
    assert rig.client.get(path).status_code == 404


# --- main -----------------------------------------------------------------------------------


def test_main_prints_a_tokenised_loopback_url_and_serves_on_loopback(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    served: list[tuple[FastAPI, str, int]] = []

    def serve(app: FastAPI, *, host: str, port: int, **_: object) -> None:
        served.append((app, host, port))

    entry.main(["--out", str(tmp_path / "wb"), "--port", "9199", "--no-open"], serve=serve)
    url = capsys.readouterr().out.strip().splitlines()[-1]
    match = re.fullmatch(r"http://127\.0\.0\.1:9199/\?token=([A-Za-z0-9_-]{40,})", url)
    assert match, url
    ((app, host, port),) = served
    assert (host, port) == ("127.0.0.1", 9199)
    assert (tmp_path / "wb").is_dir()
    page = TestClient(app, base_url="http://127.0.0.1:9199").get(
        "/", params={"token": match.group(1)}
    )
    assert 'name="notebooks" value="quickstart"' in page.text  # from NOTEBOOK_DIR


def test_main_defaults(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    opened: list[str] = []
    monkeypatch.setattr(entry.webbrowser, "open", opened.append)
    calls: list[int] = []

    def serve(app: FastAPI, *, host: str, port: int, **_: object) -> None:
        calls.append(port)

    entry.main([], serve=serve)
    assert calls == [9112]
    assert (tmp_path / "workbench-out").is_dir()
    deadline = time.monotonic() + 5
    while not opened and time.monotonic() < deadline:  # opened once the server is up
        time.sleep(0.05)
    assert len(opened) == 1 and opened[0].startswith("http://127.0.0.1:9112/?token=")


def test_an_sse_data_field_never_carries_a_line_break() -> None:
    from workbench.ui.app import _sse_line  # pyright: ignore[reportPrivateUsage]

    assert _sse_line("x\revent: end\nid: 9") == "x event: end id: 9"
