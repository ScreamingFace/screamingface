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

import tempfile
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


def _partial_checkout(tmp_path: Path) -> Path:
    """A monorepo copy with `apps/` present but the url4 sources missing; returns the SDK dir."""

    package: Path = tmp_path / "checkout" / "packages" / "screamingface"
    (package / "scripts").mkdir(parents=True)
    (package / "src" / "screamingface").mkdir(parents=True)
    (package / "src" / "screamingface" / "__init__.py").touch()
    for name in ("pyproject.toml", "README.md", "LICENSE", "scripts/runtime_build_hook.py"):
        (package / name).write_bytes((PACKAGE_ROOT / name).read_bytes())
    for app in ("aigateway", "scoreboard", "screamingface-engine"):
        (tmp_path / "checkout" / "apps" / app / "src").mkdir(parents=True)
    return package


def test_an_editable_build_refuses_a_checkout_missing_a_source_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(_partial_checkout(tmp_path))

    # WHY: Python silently skips a .pth entry that does not exist, so a partial checkout
    # would install "fine" and then fail on the first `import url4` with no hint. Refuse
    # at build time, with the same message the release build already gives.
    with pytest.raises(RuntimeError, match=r"runtime distribution sources are missing.*url4"):
        build_editable(str(tmp_path / "dist"))


def test_an_editable_build_leaves_no_staging_directory_behind(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    scratch: Path = tmp_path / "tmp"
    scratch.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(scratch))

    with _build(build_editable, tmp_path, monkeypatch):
        pass

    # INVARIANT: the .pth is staged in a temp dir only long enough for hatchling to copy
    # it into the wheel — every `uv sync` rebuild would otherwise leak one.
    assert list(scratch.iterdir()) == []
