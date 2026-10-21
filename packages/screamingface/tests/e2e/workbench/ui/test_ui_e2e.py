"""The UI end to end (unit 4 plan, Task 6): a REAL replay run launched through the routes.

No fake spawn: ``RunManager`` runs the same pytest lane CI runs
(``tests/e2e/workbench/test_notebooks.py`` on the replay stack), and the test reads the result
back through the pages a developer would open. Gated like the replay lane: the e2e gate
(``SCREAMINGFACE_TEST_E2E=1`` + docker) and prepared ifeval assets, or it skips with the reason.
"""

from __future__ import annotations

import json
import os
import re
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

    # 3. The index lists the run's bundle with a PASS pill.
    key = f"runs/{run_id}/replay/{NOTEBOOK}"
    index = client.get(f"/?token={TOKEN}")
    assert index.status_code == 200
    row = re.search(rf"<tr>(?:(?!</tr>).)*{re.escape(key)}(?:(?!</tr>).)*</tr>", index.text, re.S)
    assert row, index.text
    assert '<span class="pill pass">PASS</span>' in row.group(0)

    # 4. Its bundle page: both hops of the chain found, the notebook in an empty sandbox.
    page = client.get(f"/bundles/{key}")
    assert page.status_code == 200
    hop_row = r'<tr><td>(engine|aigateway)</td><td><span class="pill (\w+)"'
    hops = dict(re.findall(hop_row, page.text))
    assert hops == {"engine": "pass", "aigateway": "pass"}, page.text
    assert page.text.count(">found<") >= 2
    assert '<iframe class="nb" sandbox=""' in page.text
