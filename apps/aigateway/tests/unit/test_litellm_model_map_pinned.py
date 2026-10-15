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

# An address nothing listens on: if the gateway still tried the download, the load would fall
# back to the bundled map with a fallback reason instead of reporting a forced local load.
_UNREACHABLE_MAP_URL: str = "http://127.0.0.1:9/model_prices_and_context_window.json"

_PROBE: str = """
import json
import aigateway.main  # the app the server runs
from litellm.litellm_core_utils.get_model_cost_map import get_model_cost_map_source_info

info = get_model_cost_map_source_info()
print(json.dumps({
    "source": info["source"],
    "is_env_forced": info["is_env_forced"],
    "fallback_reason": info["fallback_reason"],
}))
"""


def _load_in_fresh_gateway(inherited_flag: str | None) -> dict[str, object]:
    """Import the gateway app in a new interpreter and report where litellm's map came from."""
    env: dict[str, str] = {**os.environ, "LITELLM_MODEL_COST_MAP_URL": _UNREACHABLE_MAP_URL}
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
    report: dict[str, object] = json.loads(result.stdout.strip().splitlines()[-1])
    return report


def test_the_gateway_loads_the_bundled_model_map_without_a_download() -> None:
    """Importing the app forces litellm's bundled map: no fetch was attempted, none fell back."""
    report: dict[str, object] = _load_in_fresh_gateway(inherited_flag=None)

    assert report["source"] == "local"
    assert report["is_env_forced"] is True
    assert report["fallback_reason"] is None


def test_an_inherited_false_cannot_reopen_the_download() -> None:
    """The gateway sets the flag rather than defaulting it, so a stray shell or chart value of
    ``False`` still gets the bundled map."""
    report: dict[str, object] = _load_in_fresh_gateway(inherited_flag="False")

    assert report["source"] == "local"
    assert report["is_env_forced"] is True
