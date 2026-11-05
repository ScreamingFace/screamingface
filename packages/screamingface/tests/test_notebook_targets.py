"""Every Benchmark notebook says, in one visible variable, which Engine it runs against.

INVARIANT under test: a notebook that runs a Benchmark configures its Engine from `TARGET`,
which defaults to the researcher's own `screamingface up` stack. WHY: left unconfigured, the
SDK falls back from a stopped local stack to the hosted Engine without a word, so a researcher
who forgot `screamingface up` would run against the hosted Engine and not notice.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from screamingface import _default_client

_EXAMPLES = Path(__file__).parent.parent / "examples"
# WHY these are exempt: 01 and 02 teach Client construction and `sf.configure` themselves,
# and 14 reads a saved Report with no Engine at all.
_NO_TARGET = {"01_client_tour.ipynb", "02_connection.ipynb", "14_report_accounting.ipynb"}
_BENCHMARK_NOTEBOOKS = sorted(
    path for path in _EXAMPLES.glob("*.ipynb") if path.name not in _NO_TARGET
)
_LOCAL = ("http://127.0.0.1:9108", "http://127.0.0.1:9106")
_HOSTED = ("https://fusion.screamingface.ai", "https://leaderboard.screamingface.ai")


def _target_cell(notebook: Path) -> str:
    """Return the notebook's code cell that assigns TARGET, minus its network calls."""
    cells = json.loads(notebook.read_text(encoding="utf-8"))["cells"]
    sources: list[str] = [
        "".join(cell["source"])
        for cell in cells
        if cell["cell_type"] == "code" and 'TARGET = "local"' in "".join(cell["source"])
    ]
    assert len(sources) == 1, f"{notebook.name} needs exactly one TARGET cell"
    return sources[0].replace("sf.connect()", "")


def _engine_for(source: str, target: str, monkeypatch: pytest.MonkeyPatch) -> tuple[str, str]:
    """Run the TARGET cell with one value and return the Engine and Scoreboard it chose."""
    monkeypatch.setattr(_default_client, "_client", None)
    exec(source.replace('TARGET = "local"', f'TARGET = "{target}"', 1), {})  # noqa: S102
    client = _default_client.default_client()
    return client.engine_url, client.scoreboard_url


@pytest.mark.parametrize("notebook", _BENCHMARK_NOTEBOOKS, ids=lambda path: path.name)
def test_the_target_defaults_to_the_local_stack_and_switches_to_hosted(
    notebook: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = _target_cell(notebook)
    monkeypatch.delenv("SCREAMINGFACE_ENGINE_URL", raising=False)
    monkeypatch.delenv("SCREAMINGFACE_SCOREBOARD_URL", raising=False)

    assert _engine_for(source, "local", monkeypatch) == _LOCAL
    assert _engine_for(source, "hosted", monkeypatch) == _HOSTED
    with pytest.raises(ValueError, match="TARGET must be"):
        _engine_for(source, "lcoal", monkeypatch)
    monkeypatch.setattr(_default_client, "_client", None)
