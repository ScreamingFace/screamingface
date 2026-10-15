"""The local runtime's gateway keeps OpenRouter reasoning when litellm's downloadable map loses it.

Mental model: ``screamingface up`` boots the AI Gateway from the copy shipped in this package,
on the ``[runtime]`` extra's own litellm pin (not the gateway app's). The gateway pins litellm's
model map to the bundled copy at import (OME-1615); this checks that the pin also holds in the
runtime's boot order and on the runtime's litellm version.

WHY in this lane: it is the only CI run with the ``[runtime]`` extra installed (the workflow's
``prepare`` step adds it). Gated on ``SCREAMINGFACE_TEST_E2E=1`` like the rest of the lane, but
needs no Docker: one fresh interpreter boots the runtime's imports and asks litellm, offline,
whether it accepts the parameter.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib.resources import files
from importlib.util import find_spec
from typing import Any

import pytest
from harness._gating import E2E_ENV

pytestmark = pytest.mark.e2e

#: The paid smoke's reasoning member, the model whose calls died on 2026-10-15.
_INCIDENT_MODEL: str = "qwen/qwen3.7-flash"

_PROBE: str = f"""
import json
from screamingface._runtime.server import require_runtime_extra

require_runtime_extra()  # what `screamingface up` runs first: live source, then the app imports
import litellm
from litellm.utils import get_optional_params

try:
    get_optional_params(
        model="{_INCIDENT_MODEL}",
        custom_llm_provider="openrouter",
        reasoning_effort="low",
        max_tokens=16,
    )
    reasoning_accepted = True
except litellm.UnsupportedParamsError:
    reasoning_accepted = False
print(json.dumps({{
    "knows_model": "openrouter/{_INCIDENT_MODEL}" in litellm.model_cost,
    "reasoning_accepted": reasoning_accepted,
}}))
"""


@pytest.fixture
def upstream_map_without_openrouter() -> Iterator[str]:
    """Serve the 2026-10-15 upstream map on a local port: the runtime litellm's bundled map,
    OpenRouter rows removed, still large enough to pass litellm's integrity check."""
    if os.environ.get(E2E_ENV) != "1":
        pytest.skip(f"{E2E_ENV}=1 not set (the e2e replay lane is opt-in)")
    # INVARIANT: inside the lane the extra is installed, so a missing litellm is a broken lane,
    # never a skip.
    assert find_spec("litellm") is not None, 'the lane must install "screamingface[runtime]"'
    bundled: dict[str, Any] = json.loads(
        files("litellm").joinpath("model_prices_and_context_window_backup.json").read_text()
    )
    body: bytes = json.dumps(
        {name: row for name, row in bundled.items() if not name.startswith("openrouter/")}
    ).encode()

    class _MapHandler(BaseHTTPRequestHandler):
        """Answer every GET with the stripped map."""

        def do_GET(self) -> None:  # noqa: N802 - the name http.server dispatches on
            """Send the stripped map as JSON."""
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: Any) -> None:  # noqa: A002 - base signature
            """Keep the test output quiet."""

    server: ThreadingHTTPServer = ThreadingHTTPServer(("127.0.0.1", 0), _MapHandler)
    thread: threading.Thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}/model_prices_and_context_window.json"
    finally:
        server.shutdown()
        server.server_close()


def test_the_runtime_gateway_keeps_openrouter_reasoning_without_upstream_rows(
    upstream_map_without_openrouter: str,
) -> None:
    """The incident replayed through the runtime's boot: the downloadable map has no OpenRouter
    rows, yet litellm still knows the paid smoke's reasoning member and accepts its
    ``reasoning_effort``. Without the gateway's pin, litellm loads the served map and refuses."""
    env: dict[str, str] = {
        **os.environ,
        "LITELLM_MODEL_COST_MAP_URL": upstream_map_without_openrouter,
    }
    env.pop("LITELLM_LOCAL_MODEL_COST_MAP", None)
    result: subprocess.CompletedProcess[str] = subprocess.run(
        [sys.executable, "-c", _PROBE],
        env=env,
        capture_output=True,
        text=True,
        timeout=300,
        check=True,
    )
    report: dict[str, Any] = json.loads(result.stdout.strip().splitlines()[-1])

    assert report["knows_model"] is True
    assert report["reasoning_accepted"] is True
