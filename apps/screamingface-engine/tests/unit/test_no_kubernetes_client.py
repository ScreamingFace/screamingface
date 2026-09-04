"""No import of the kubernetes client remains under apps/screamingface-engine (OME-1092).

The cutover retires the Job adapter, so the `kubernetes` client dependency must go with it.
This scan is the RED gate: a stray `from kubernetes...` import (or a resurrected adapter)
fails here before the dependency can quietly come back.

WHY a scan and not just dropping the dependency: the dependency being absent from
pyproject.toml does not stop a committed import from type-checking against a stale lockfile
or a transitive install. The scan asserts the codebase itself is clean.
"""

from __future__ import annotations

import re
from pathlib import Path

_APP_ROOT = Path(__file__).resolve().parents[2]
_SRC = _APP_ROOT / "src"
_TESTS = _APP_ROOT / "tests"
_SELF = Path(__file__).resolve()

_SKIP_DIRS = {"__pycache__", ".pytest_cache", ".ruff_cache", "data"}
_TEXT_SUFFIXES = {".py", ".toml", ".yaml", ".yml", ".tpl", ".json", ".md", ".txt"}

# Any import of the kubernetes client, in any spelling.
_IMPORT_RE = re.compile(r"^\s*(?:from\s+kubernetes|import\s+kubernetes)\b", re.MULTILINE)


def _scanned_files() -> list[Path]:
    found: list[Path] = []
    for root in (_SRC, _TESTS):
        for path in root.rglob("*"):
            if not path.is_file() or path.suffix not in _TEXT_SUFFIXES:
                continue
            if any(part in _SKIP_DIRS for part in path.parts):
                continue
            if path.resolve() == _SELF:
                continue
            found.append(path)
    return found


def test_the_scan_actually_reaches_the_source_tree() -> None:
    """Guard against a permanently green gate: a scan that matches nothing passes vacuously."""
    scanned = _scanned_files()
    assert len(scanned) > 100, f"expected to scan the whole app, found only {len(scanned)} files"


def test_no_import_of_the_kubernetes_client_remains() -> None:
    offenders = [
        str(path.relative_to(_APP_ROOT))
        for path in _scanned_files()
        if _IMPORT_RE.search(path.read_text(encoding="utf-8", errors="replace"))
    ]
    assert not offenders, (
        f"the kubernetes client is still imported in: {sorted(offenders)} — the Job adapter "
        f"is retired (OME-1092); delete the import and drop the dependency"
    )


def test_the_kubernetes_dependency_is_dropped_from_pyproject() -> None:
    pyproject = (_APP_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert "kubernetes" not in pyproject, (
        "the kubernetes client dependency must be dropped from pyproject.toml — nothing "
        "under this app imports it anymore"
    )
