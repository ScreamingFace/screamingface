"""The gateway reads litellm's bundled model map, never the one on litellm's GitHub main branch.

WHY: litellm's model map decides which parameters a model accepts. The downloaded map changed
under every running gateway on 2026-10-15 (all OpenRouter entries gone), so OpenRouter calls
with ``reasoning_effort`` failed on restart with no change on our side. The bundled map moves
only with ``uv.lock``.

Each check runs in a fresh interpreter: litellm loads the map once, at import, and the test
process has already imported it.
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
from typing import Any

import pytest

# An address nothing listens on: if the gateway still tried the download, the load would fall
# back to the bundled map with a fallback reason instead of reporting a forced local load.
_UNREACHABLE_MAP_URL: str = "http://127.0.0.1:9/model_prices_and_context_window.json"

#: The paid smoke's reasoning member, the model whose calls died on 2026-10-15.
_INCIDENT_MODEL: str = "qwen/qwen3.7-flash"

_PROBE: str = f"""
import json
import aigateway.main  # the app the server runs
import litellm
from litellm.litellm_core_utils.get_model_cost_map import get_model_cost_map_source_info
from litellm.utils import get_optional_params

info = get_model_cost_map_source_info()
# The check litellm runs before every call: a refused parameter raises here, offline.
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
    "source": info["source"],
    "is_env_forced": info["is_env_forced"],
    "fallback_reason": info["fallback_reason"],
    "knows_model": "openrouter/{_INCIDENT_MODEL}" in litellm.model_cost,
    "reasoning_accepted": reasoning_accepted,
}}))
"""


def _load_in_fresh_gateway(map_url: str, inherited_flag: str | None) -> dict[str, Any]:
    """Import the gateway app in a new interpreter and report the model map it ended up with."""
    env: dict[str, str] = {**os.environ, "LITELLM_MODEL_COST_MAP_URL": map_url}
    env.pop("LITELLM_LOCAL_MODEL_COST_MAP", None)
    if inherited_flag is not None:
        env["LITELLM_LOCAL_MODEL_COST_MAP"] = inherited_flag
    result: subprocess.CompletedProcess[str] = subprocess.run(
        [sys.executable, "-c", _PROBE],
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
        check=True,
    )
    report: dict[str, Any] = json.loads(result.stdout.strip().splitlines()[-1])
    return report


@pytest.fixture
def upstream_map_without_openrouter() -> Iterator[str]:
    """Serve the 2026-10-15 upstream map on a local port: litellm's bundled map, OpenRouter rows
    removed. It still passes litellm's integrity check (about 3,650 of 3,920 rows), so a gateway
    that downloaded it would load it."""
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


def test_the_gateway_loads_the_bundled_model_map_without_a_download() -> None:
    """Importing the app forces litellm's bundled map: no fetch was attempted, none fell back."""
    report: dict[str, Any] = _load_in_fresh_gateway(_UNREACHABLE_MAP_URL, inherited_flag=None)

    assert report["source"] == "local"
    assert report["is_env_forced"] is True
    assert report["fallback_reason"] is None


def test_an_inherited_false_cannot_reopen_the_download() -> None:
    """The gateway sets the flag rather than defaulting it, so a stray shell or chart value of
    ``False`` still gets the bundled map."""
    report: dict[str, Any] = _load_in_fresh_gateway(_UNREACHABLE_MAP_URL, inherited_flag="False")

    assert report["source"] == "local"
    assert report["is_env_forced"] is True


def test_openrouter_reasoning_survives_an_upstream_map_without_openrouter(
    upstream_map_without_openrouter: str,
) -> None:
    """The incident replayed offline: the downloadable map has no OpenRouter rows, yet the
    gateway still knows the paid smoke's reasoning member and litellm accepts its
    ``reasoning_effort``. Without the pin, litellm loads the served map and refuses it."""
    report: dict[str, Any] = _load_in_fresh_gateway(
        upstream_map_without_openrouter, inherited_flag=None
    )

    assert report["knows_model"] is True
    assert report["reasoning_accepted"] is True
