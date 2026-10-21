"""Read workbench evidence bundles from disk for the UI (spec §3.3 layout). Read-only.

A bundle is any directory under the root holding ``trace.json`` or ``executed.ipynb``
(``write_bundle`` lays them out as ``<root>/<target>/<notebook>/``; UI-launched runs add a
``runs/<id>/`` prefix). Bundles may come from an unzipped CI artifact, so every file is
untrusted: odd shapes degrade to "unreadable", and symlinks — directories or files — are
never followed, so nothing outside the root is ever read.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_MARKERS = ("trace.json", "executed.ipynb")


class BundleNotFound(LookupError):
    """The key does not name a bundle inside the root."""


@dataclass(frozen=True)
class BundleSummary:
    key: str  # path relative to root, posix, e.g. "runs/<id>/replay/quickstart"
    target: str
    notebook: str
    passed: bool | None  # None when trace.json is missing/unreadable
    trace_ids: tuple[str, ...]
    reasons: tuple[str, ...]
    modified: float  # mtime of trace.json (or of the dir)


@dataclass(frozen=True)
class BundleDetail:
    summary: BundleSummary
    trace: dict[str, Any] | None
    logs: dict[str, str]  # hop name -> text (already redacted by the bundle writer)
    notebook_path: Path | None


def _regular(path: Path) -> bool:
    return not path.is_symlink() and path.is_file()


def _is_bundle(directory: Path) -> bool:
    return any(_regular(directory / m) for m in _MARKERS)


def _read_trace(directory: Path) -> dict[str, Any] | None:
    marker = directory / "trace.json"
    if not _regular(marker):
        return None
    try:
        value: object = json.loads(marker.read_text())
    except (OSError, ValueError):
        return None
    return value if isinstance(value, dict) else None  # pyright: ignore[reportUnknownVariableType]


def _strings(trace: dict[str, Any], field: str) -> tuple[str, ...]:
    value = trace.get(field)
    if not isinstance(value, list):
        return ()
    items: list[object] = value  # pyright: ignore[reportUnknownVariableType]
    return tuple(item for item in items if isinstance(item, str))


def _summary(root: Path, directory: Path, trace: dict[str, Any] | None) -> BundleSummary:
    marker = directory / "trace.json"
    modified = (marker if _regular(marker) else directory).stat().st_mtime
    data = trace or {}
    passed = data.get("passed")
    return BundleSummary(
        key=directory.relative_to(root).as_posix(),
        target=directory.parent.name,
        notebook=directory.name,
        passed=passed if isinstance(passed, bool) else None,
        trace_ids=_strings(data, "trace_ids"),
        reasons=_strings(data, "reasons"),
        modified=modified,
    )


def _subdirs(directory: Path) -> list[Path]:
    try:
        children = list(directory.iterdir())
    except OSError:
        return []
    return [c for c in children if not c.is_symlink() and c.is_dir()]


def discover(root: Path, *, max_depth: int = 4) -> list[BundleSummary]:
    """Every bundle under ``root``, newest first; no symlinks followed, ``max_depth`` levels."""
    root = root.resolve()
    found: list[BundleSummary] = []
    frontier = [(root, 0)]
    while frontier:
        directory, depth = frontier.pop()
        if directory != root and _is_bundle(directory):
            found.append(_summary(root, directory, _read_trace(directory)))
        elif depth < max_depth:
            frontier.extend((child, depth + 1) for child in _subdirs(directory))
    return sorted(found, key=lambda b: b.modified, reverse=True)


def _resolve(root: Path, key: str) -> Path:
    candidate = (root / key).resolve()  # resolves ".." and symlinks before the containment check
    if root not in candidate.parents or not candidate.is_dir() or not _is_bundle(candidate):
        raise BundleNotFound(key)
    return candidate


def _logs(directory: Path) -> dict[str, str]:
    logs_dir = directory / "logs"
    if logs_dir.is_symlink() or not logs_dir.is_dir():
        return {}
    return {
        p.stem: p.read_text(errors="replace") for p in sorted(logs_dir.glob("*.txt")) if _regular(p)
    }


def load(root: Path, key: str) -> BundleDetail:
    """The bundle named by ``key`` (as listed by ``discover``); ``BundleNotFound`` otherwise."""
    root = root.resolve()
    directory = _resolve(root, key)
    trace = _read_trace(directory)
    notebook = directory / "executed.ipynb"
    return BundleDetail(
        summary=_summary(root, directory, trace),
        trace=trace,
        logs=_logs(directory),
        notebook_path=notebook if _regular(notebook) else None,
    )
