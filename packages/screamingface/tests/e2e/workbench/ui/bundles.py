"""Read workbench evidence bundles from disk for the UI (spec §3.3 layout). Read-only.

A bundle is any directory under the root holding ``trace.json`` or ``executed.ipynb``
(``write_bundle`` lays them out as ``<root>/<target>/<notebook>/``; UI-launched runs add a
``runs/<id>/`` prefix). Bundles may come from an unzipped CI artifact, so every file is
untrusted: odd shapes degrade to "unreadable", filesystem errors degrade to "not a bundle"
(or a marked log), logs are capped at ``LOG_CAP_BYTES``, and symlinks — directories or files,
at any depth of a key — are never followed, so nothing outside the root is ever read and
``load`` serves exactly the keys ``discover`` lists.

Not defended: a file swapped for a symlink between the ``regular_file`` check and the read
(TOCTOU). Acceptable for a loopback dev tool reading the user's own disk.
"""

from __future__ import annotations

import json
import posixpath
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_MARKERS = ("trace.json", "executed.ipynb")
LOG_CAP_BYTES = 1 << 20  # per log; an unzipped artifact can carry anything
TRUNCATED_MARK = "\n[... truncated by the workbench UI ...]"
UNREADABLE_LOG = "[log unreadable]"


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
    # The notebook fails on purpose (spec §3.7): trace.json carries ``expect``, in any shape —
    # a malformed declaration is still an expected-failure bundle (red), never a plain one.
    expected: bool = False


@dataclass(frozen=True)
class BundleDetail:
    summary: BundleSummary
    trace: dict[str, Any] | None
    logs: dict[str, str]  # hop name -> text (already redacted by the bundle writer)
    notebook_path: Path | None
    directory: Path  # the bundle's own directory (resolved, inside the root)


def regular_file(path: Path) -> bool:
    try:
        return not path.is_symlink() and path.is_file()
    except (OSError, ValueError):
        return False


def _is_bundle(directory: Path) -> bool:
    return any(regular_file(directory / m) for m in _MARKERS)


def _read_trace(directory: Path) -> dict[str, Any] | None:
    marker = directory / "trace.json"
    if not regular_file(marker):
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


def _mtime(directory: Path) -> float:
    marker = directory / "trace.json"
    try:
        return (marker if regular_file(marker) else directory).stat().st_mtime
    except OSError:  # vanished between the bundle check and now
        return 0.0


def _summary(root: Path, directory: Path, trace: dict[str, Any] | None) -> BundleSummary:
    modified = _mtime(directory)
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
        expected="expect" in data,
    )


def _subdirs(directory: Path) -> list[Path]:
    try:
        children = list(directory.iterdir())
    except OSError:
        return []
    return [c for c in children if _plain_dir(c)]


def _plain_dir(path: Path) -> bool:
    try:
        return not path.is_symlink() and path.is_dir()
    except (OSError, ValueError):
        return False


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
    # Lexical normalization first, then a resolve that must change nothing: any symlink on the
    # way (even one pointing back inside the root) makes them differ, so the key is refused.
    normalized = posixpath.normpath(key) if key else ""
    if not normalized or normalized.startswith(("/", "..")) or normalized == ".":
        raise BundleNotFound(key)
    expected = root / normalized
    try:
        candidate = expected.resolve(strict=True)
        found = candidate == expected and _plain_dir(candidate) and _is_bundle(candidate)
    except (OSError, ValueError, RuntimeError):  # NUL byte, ENAMETOOLONG, EACCES, loops
        found = False
    if not found:
        raise BundleNotFound(key)
    return candidate


def _read_log(path: Path) -> str:
    try:
        with path.open("rb") as handle:
            data = handle.read(LOG_CAP_BYTES + 1)
    except OSError:
        return UNREADABLE_LOG
    text = data[:LOG_CAP_BYTES].decode(errors="replace")
    return text + TRUNCATED_MARK if len(data) > LOG_CAP_BYTES else text


def _logs(directory: Path) -> dict[str, str]:
    logs_dir = directory / "logs"
    if not _plain_dir(logs_dir):
        return {}
    try:
        paths = sorted(logs_dir.glob("*.txt"))
    except OSError:
        return {}
    return {p.stem: _read_log(p) for p in paths if regular_file(p)}


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
        notebook_path=notebook if regular_file(notebook) else None,
        directory=directory,
    )
