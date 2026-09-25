"""The build hook: editable installs point at the live code; wheels still carry it.

Mental model: the wheel smuggles url4 and three whole apps into site-packages, so a
`pip install screamingface` user gets a working stack. A dev's editable install used to
get the same smuggled copy, frozen on the day `uv sync` last built it. `import
screamingface` loads url4 before checkout activation can run, so that frozen copy won
(`No module named 'url4.cli._config'`, 2026-09-25: a Sep 18 url4 copy running Sep 22
Engine code). An editable build now ships a `.pth` pointing at the live source
directories instead of a copy, so there is nothing to go stale.

These tests run hatchling's real PEP 660/517 entry points against this package, because
the risky part is whether hatchling honours the editable override at all.
"""

from __future__ import annotations

import zipfile
from collections.abc import Callable
from pathlib import Path

import pytest
from hatchling.build import build_editable, build_wheel

from screamingface._runtime import source

PACKAGE_ROOT: Path = Path(__file__).resolve().parents[1]
CHECKOUT_ROOT: Path = PACKAGE_ROOT.parents[1]
SOURCES_PTH: str = "_screamingface_runtime_sources.pth"

# WHY these roots: exactly what the hook force-includes into a wheel. Any of them
# inside an editable wheel is a frozen copy that can shadow the live checkout.
_VENDORED_ROOTS: tuple[str, ...] = (
    "url4/",
    "aigateway/",
    "scoreboard/",
    "screamingface_engine/",
    "screamingface/",
)


def _build(
    builder: Callable[[str], str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> zipfile.ZipFile:
    """Build this package the way pip/uv would and open the resulting wheel."""

    # hatchling's PEP 517 hooks read pyproject.toml from the working directory.
    monkeypatch.chdir(PACKAGE_ROOT)
    wheel: str = builder(str(tmp_path))
    return zipfile.ZipFile(tmp_path / wheel)


def test_an_editable_build_vendors_no_frozen_copies(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with _build(build_editable, tmp_path, monkeypatch) as archive:
        names: list[str] = archive.namelist()

    # INVARIANT: a dev venv never holds a copy of url4 or an app — a copy is frozen at
    # build time and outlives the next url4 change, which is the 2026-09-25 crash.
    vendored: list[str] = [name for name in names if name.startswith(_VENDORED_ROOTS)]
    assert vendored == []
    assert SOURCES_PTH in names


def test_the_editable_pth_lists_exactly_the_live_source_directories(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with _build(build_editable, tmp_path, monkeypatch) as archive:
        lines: list[str] = archive.read(SOURCES_PTH).decode().splitlines()

    # INVARIANT: the hook's list and checkout activation's list are one list — a
    # directory missing here is served stale (or not at all) by an editable install.
    checkout = source.RuntimeSource(mode=source.MODE_CHECKOUT, root=CHECKOUT_ROOT)
    assert lines == list(source.source_directories(checkout))
    assert all(Path(line).is_dir() for line in lines)


def test_a_release_wheel_still_vendors_the_runtime(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with _build(build_wheel, tmp_path, monkeypatch) as archive:
        names: list[str] = archive.namelist()

    # WHY: `pip install "screamingface[runtime]"` users have no checkout — the wheel must
    # keep carrying the live url4 (including the module whose absence crashed boot).
    assert "url4/__init__.py" in names
    assert "url4/cli/_config.py" in names
    assert "screamingface_engine/__init__.py" in names
    assert SOURCES_PTH not in names
