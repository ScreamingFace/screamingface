"""Type checkers see the two replay forms of `evaluate` and refuse a call with nothing to run.

FEATURE: OME-1613 (spec §1, Q5, R4) — `evaluate` has one overload per replay id (`pinned_cache=`
or `score_id=`), so Pyright accepts both replay forms and rejects `evaluate()` with neither
candidates nor a replay id, and `capture=True` on a replay. The runtime refuses them too
(`test_evaluate_doors.py`); this test pins what an editor shows.

Pyright runs on small snippets with `--outputjson`; the assertions read the parsed diagnostics.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

PACKAGE = Path(__file__).resolve().parents[1]
COPY = "0b1f6d3a-5c0e-4a8e-9a3f-2f6f8f4c7d11"

ACCEPTED = f"""
import screamingface as sf

sf.evaluate(pinned_cache="{COPY}")
sf.evaluate(score_id="score-id")
sf.evaluate(pinned_cache="{COPY}", score_id="score-id", record_reproduction=False)
sf.Client().evaluate(pinned_cache="{COPY}")


async def replay(client: sf.AsyncClient) -> None:
    await client.evaluate(score_id="score-id")
"""

REFUSED = {
    "nothing-to-run": "sf.evaluate()",
    "capture-on-a-replay": f'sf.evaluate(pinned_cache="{COPY}", capture=True)',
    "client-nothing-to-run": "sf.Client().evaluate()",
}


def _pyright(tmp_path: Path, source: str) -> list[dict[str, object]]:
    (tmp_path / "snippet.py").write_text(source, encoding="utf-8")
    config = {
        "include": ["snippet.py"],
        "venvPath": str(PACKAGE),
        "venv": ".venv",
        "pythonVersion": "3.12",
        "typeCheckingMode": "basic",
    }
    (tmp_path / "pyrightconfig.json").write_text(json.dumps(config), encoding="utf-8")
    completed = subprocess.run(
        [sys.executable, "-m", "pyright", "--outputjson", "-p", str(tmp_path)],
        capture_output=True,
        text=True,
        check=False,
        timeout=300,
    )
    report = json.loads(completed.stdout)
    return [
        diagnostic
        for diagnostic in report["generalDiagnostics"]
        if diagnostic["severity"] == "error"
    ]


def test_both_replay_forms_type_check(tmp_path: Path) -> None:
    assert _pyright(tmp_path, ACCEPTED) == []


@pytest.mark.parametrize("call", list(REFUSED.values()), ids=list(REFUSED))
def test_a_call_with_nothing_to_run_or_capture_on_a_replay_is_a_type_error(
    tmp_path: Path, call: str
) -> None:
    errors = _pyright(tmp_path, f"import screamingface as sf\n\n{call}\n")

    assert [error["rule"] for error in errors] == ["reportCallIssue"]
