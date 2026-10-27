"""The UI end to end (unit 4 plan, Task 6): a REAL replay run launched through the routes.

No fake spawn: ``RunManager`` runs the same pytest lane CI runs
(``tests/e2e/workbench/test_notebooks.py`` on the replay stack), and the test reads the result
back through the pages a developer would open. Gated like the replay lane: the e2e gate
(``SCREAMINGFACE_TEST_E2E=1`` + docker) and prepared ifeval assets, or it skips with the reason.

The Trace view (u8 plan, Task 5) is read as a tree of span names: an ``HTMLParser`` maps each
``<li>`` to its first ``sname``, so "``url4.run`` under ``sdk.evaluate``" is a parent edge, not
a substring that would also hold for a sibling or a span on another page.
"""

from __future__ import annotations

import json
import os
import re
from html.parser import HTMLParser
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from harness._gating import require_e2e_stack
from harness.benchmark_assets import assets_root

from workbench.ui import __main__ as entry
from workbench.ui.app import create_app
from workbench.ui.runs import RunManager

pytestmark = pytest.mark.e2e

PORT = 9112
TOKEN = "e2e-token"
NOTEBOOK = "quickstart"
# The child run must never be able to spend: the replay target is keyless, and stripping these
# keeps a stray shell export from turning this into a paid run.
_PAID = ("OPENROUTER_API_KEY", "SCREAMINGFACE_TEST_PAID")


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    require_e2e_stack()
    if not (assets_root() / "ifeval").is_dir():
        pytest.skip(f"replay target needs prepared ifeval assets at {assets_root() / 'ifeval'}")
    environ = {k: v for k, v in os.environ.items() if k not in _PAID}
    manager = RunManager(tmp_path / "out", workdir=entry.PACKAGE_DIR, environ=environ)
    app = create_app(
        root=tmp_path / "out",
        manager=manager,
        token=TOKEN,
        port=PORT,
        notebooks=entry.notebook_stems(),
    )
    return TestClient(app, base_url=f"http://127.0.0.1:{PORT}", follow_redirects=False)


def test_a_replay_run_through_the_ui_lands_a_passing_bundle(client: TestClient) -> None:
    # 1. Launch exactly what the form posts.
    started = client.post("/runs", data={"target": "replay", "notebooks": NOTEBOOK, "token": TOKEN})
    assert started.status_code == 303, started.text
    match = re.fullmatch(r"/runs/([0-9a-z-]+)\?token=.+", started.headers["location"])
    assert match, started.headers["location"]
    run_id = match.group(1)

    # 2. Follow the live stream to its end; the log is the evidence when this fails.
    with client.stream("GET", f"/runs/{run_id}/events") as response:
        assert response.status_code == 200
        stream = "".join(response.iter_text())
    end = re.search(r"event: end\ndata: (.+)\n\n", stream)
    log = "\n".join(re.findall(r"^data: (.*)$", stream, flags=re.M))
    assert end, log
    assert json.loads(end.group(1)) == {"returncode": 0, "cancelled": False}, log
    assert f"test_notebook[replay-{NOTEBOOK}] PASSED" in log, log
    # The run selected its notebook by exact node id, and pushed a live progress state.
    assert f"::test_notebook[replay-{NOTEBOOK}]" in log and "collected 1 item" in log, log
    assert re.search(rf'event: progress\ndata: {{"running": "{NOTEBOOK}", ', stream), stream

    # 3. The index lists the run's bundle with a PASS pill.
    key = f"runs/{run_id}/replay/{NOTEBOOK}"
    index = client.get(f"/?token={TOKEN}")
    assert index.status_code == 200
    row = re.search(rf"<tr>(?:(?!</tr>).)*{re.escape(key)}(?:(?!</tr>).)*</tr>", index.text, re.S)
    assert row, index.text
    assert '<span class="pill pass">PASS</span>' in row.group(0)

    # 4. Its bundle page: the Trace view (five hops, one tree from the client span down to the
    # gateway), the notebook in an empty sandbox.
    page = client.get(f"/bundles/{key}")
    assert page.status_code == 200
    _assert_bundle_page(page.text)
    # 6. Unit 6: the bundle's Telemetry section, and the run's telemetry stream.
    _assert_telemetry_section(page.text)
    _assert_telemetry_stream(client, run_id)


def _assert_bundle_page(text: str) -> None:
    _assert_trace_view(text)
    assert '<iframe class="nb" sandbox=""' in text
    # 5. Spend per candidate: an amount or "unknown", never the string "None".
    candidates = text.split("<th>Candidate</th>", 1)[1].split("</table>", 1)[0]
    assert "<th>Spend (USD)</th>" in text and "None" not in candidates, candidates
    assert re.search(r"Total spend: <b>(\$[0-9.]+|unknown)</b>", text), text


class _TreeEdges(HTMLParser):
    """``(name, parent name)`` per tree ``<li>``, and which rows are the derived client span."""

    def __init__(self) -> None:
        super().__init__()
        self.stack: list[str | None] = []  # the open <li>s' span names, outermost first
        self.edges: list[tuple[str, str | None]] = []
        self.synthetic: list[str] = []
        self._name: bool = False
        self._synthetic: bool = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        css = (dict(attrs).get("class") or "").split()
        if tag == "li":
            self.stack.append(None)
        elif tag == "span" and "synthetic" in css:
            self._synthetic = True
        elif tag == "span" and "sname" in css and self.stack and self.stack[-1] is None:
            self._name = True

    def handle_data(self, data: str) -> None:
        if not self._name:
            return
        self._name = False
        self.stack[-1] = data
        parents = [n for n in self.stack[:-1] if n is not None]
        self.edges.append((data, parents[-1] if parents else None))
        if self._synthetic:
            self.synthetic.append(data)
        self._synthetic = False

    def handle_endtag(self, tag: str) -> None:
        if tag == "li" and self.stack:
            self.stack.pop()


def _assert_trace_view(text: str) -> None:
    """Five hops; ``sdk.evaluate`` (derived) roots ``url4.run``; a gateway chat span sits under
    the engine's ``/benchmarks/candidate`` (u8 plan, Task 5; spec §3.8)."""
    assert '<section id="trace"><h2>Trace</h2>' in text, text
    section = text.split('<section id="trace">', 1)[1].split("</section>", 1)[0]
    hop_path = section.split('<table class="hop-path">', 1)[1].split("</table>", 1)[0]
    hop_row = r'<tr><td>(\w+)</td><td><span class="pill (\w+)"'
    assert re.findall(hop_row, hop_path) == [
        ("notebook", "pass"),
        ("engine", "pass"),
        ("aigateway", "pass"),
        ("provider", "unknown"),
        ("scoreboard", "unknown"),
    ], hop_path
    tree = section.split('<ul class="tree">', 1)[1].split('<h3 id="trace-calls">', 1)[0]
    parsed = _TreeEdges()
    parsed.feed('<ul class="tree">' + tree)
    assert parsed.synthetic == ["sdk.evaluate"], parsed.edges
    assert ("sdk.evaluate", None) in parsed.edges, parsed.edges
    assert "derived from SDK events" in tree, tree
    assert ("url4.run", "sdk.evaluate") in parsed.edges, parsed.edges
    assert ("POST /v1/chat/completions", "/benchmarks/candidate") in parsed.edges, parsed.edges


def _assert_telemetry_section(text: str) -> None:
    """Waterfall with the engine root and a gateway span, usage, logs and cases (unit 6, T7)."""
    assert '<section id="telemetry"><h2>Telemetry</h2>' in text, text
    section = text.split('<section id="telemetry">', 1)[1].split("</section>", 1)[0]
    counts = re.search(r"(\d+) events · (\d+) spans", section)
    assert counts and int(counts.group(1)) > 0 and int(counts.group(2)) > 0, section
    spans = section.split('<h3 id="waterfall">Spans</h3>', 1)[1].split("<h3>", 1)[0]
    # Both services under the notebook's trace id: the engine's url4.run tree and the gateway.
    assert "<b>screamingface-engine</b>" in spans and "<b>aigateway</b>" in spans, spans
    assert ">url4.run<" in spans, spans
    assert "POST /v1/chat/completions" in spans, spans
    assert "<svg" in spans, spans
    usage = section.split("<h3>Usage and cost</h3>", 1)[1].split("<h3>", 1)[0]
    assert "<th>Cost (USD)</th>" in usage and "None" not in usage, usage
    logs = section.split("<h3>Logs</h3>", 1)[1].split("<h3>", 1)[0]
    assert "<fieldset><legend>Severity</legend>" in logs and "<tr data-sev=" in logs, logs
    cases = section.split("<h3>Cases</h3>", 1)[1]
    assert "<th>Case</th>" in cases and "No cases in report.json" not in cases, cases


def _assert_telemetry_stream(client: TestClient, run_id: str) -> None:
    """The ended run's live telemetry stream replays its model calls and counts, then ends."""
    with client.stream("GET", f"/runs/{run_id}/telemetry") as response:
        assert response.status_code == 200
        stream = "".join(response.iter_text())
    calls = [json.loads(d) for d in re.findall(r"event: call\ndata: (.+)\n\n", stream)]
    assert calls and all(c["model"] for c in calls), stream
    counts = [json.loads(d) for d in re.findall(r"event: counts\ndata: (.+)\n\n", stream)]
    assert counts and counts[-1]["spans"] > 0 and counts[-1]["events"] > 0, stream
    assert stream.endswith("event: end\ndata: {}\n\n"), stream
