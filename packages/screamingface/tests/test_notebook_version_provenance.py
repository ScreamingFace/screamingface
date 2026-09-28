"""Generated notebook identity survives sharing without machine-dependent metadata."""

from __future__ import annotations

import json
import runpy
import tomllib
from pathlib import Path

import pytest

from screamingface import _version

_ROOT = Path(__file__).resolve().parents[1]


def test_builder_stamps_source_version_deterministically_not_an_unrelated_install(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(_version, "distribution_version", lambda _: "999.0.0")
    builder = runpy.run_path(str(_ROOT / "scripts/build_notebooks.py"))["notebooks"]
    expected = tomllib.loads((_ROOT / "pyproject.toml").read_text())["project"]["version"]
    first = builder()
    second = builder()

    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)
    for notebook in first.values():
        assert notebook.metadata["screamingface"] == {"generated_by_version": expected}
        for cell in notebook.cells:
            if cell.cell_type == "code":
                assert cell.execution_count is None
                assert cell.outputs == []


@pytest.mark.parametrize("path", sorted((_ROOT / "examples").glob("*.ipynb")), ids=lambda p: p.name)
def test_distributed_notebooks_keep_their_generation_stamp(path: Path) -> None:
    # WHY: a later package release must not rewrite the historical generation version.
    metadata = json.loads(path.read_text())["metadata"]["screamingface"]
    assert set(metadata) == {"generated_by_version"}
    assert isinstance(metadata["generated_by_version"], str)
    assert metadata["generated_by_version"].strip()
