"""The release wheel carries what `up` needs to BUILD an Engine environment (OME-1620).

Beside the runtime sources it already vendors, the wheel now ships the Engine's inspect plugin,
the Engine's and url4's project files (so pip/uv can build both from the wheel's own copies) and
the Engine's pinned dependency world. An editable install ships none of it: in a checkout the
Engine environment is the Engine app's own venv, and a frozen copy would shadow live code.
"""

from __future__ import annotations

import zipfile
from collections.abc import Callable
from pathlib import Path

import pytest
from hatchling.build import build_editable, build_wheel

PACKAGE_ROOT: Path = Path(__file__).resolve().parents[1]

ENGINE_DIST_MATERIAL: tuple[str, ...] = (
    "screamingface_engine_inspect/__init__.py",
    "screamingface_engine_inspect/deployment.py",
    "screamingface/_runtime/engine_dist/screamingface-engine/pyproject.toml",
    "screamingface/_runtime/engine_dist/url4/pyproject.toml",
    "screamingface/_runtime/engine_dist/url4/README.md",
    "screamingface/_runtime/engine_dist/url4/LICENSE",
    "screamingface/_runtime/resources/engine-requirements.txt",
)


def _build(
    builder: Callable[[str], str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> zipfile.ZipFile:
    monkeypatch.chdir(PACKAGE_ROOT)
    wheel: str = builder(str(tmp_path))
    return zipfile.ZipFile(tmp_path / wheel)


def test_a_release_wheel_carries_the_engine_dist_material(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with _build(build_wheel, tmp_path, monkeypatch) as archive:
        names: set[str] = set(archive.namelist())

    missing = [name for name in ENGINE_DIST_MATERIAL if name not in names]
    assert missing == []
    # WHY: the plugin's vendored grader code must travel whole — a benchmark whose scorer is
    # missing registers and then fails every run.
    assert any(name.startswith("screamingface_engine_inspect/local_tasks/") for name in names)


def test_an_editable_build_vendors_none_of_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with _build(build_editable, tmp_path, monkeypatch) as archive:
        names: list[str] = archive.namelist()

    assert [name for name in names if name.startswith("screamingface_engine_inspect/")] == []
    assert [name for name in names if "engine_dist" in name] == []
