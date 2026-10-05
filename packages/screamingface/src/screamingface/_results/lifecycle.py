"""Best-effort lifecycle markers distinguish interrupted reports from healthy history."""

from __future__ import annotations

import json
import logging
import os
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from threading import RLock
from typing import TYPE_CHECKING, Literal

from screamingface._results.store import atomic_json

if TYPE_CHECKING:
    from screamingface.report import Report

_logger = logging.getLogger(__name__)
_lock = RLock()
_active: dict[tuple[int, Path], dict[object, str]] = {}


def evaluation_path(directory: Path, report_id: object) -> Path | None:
    # INVARIANT: metadata cannot redirect marker reads/writes outside evaluations.
    if (
        not isinstance(report_id, str)
        or not report_id
        or any(
            character not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-"
            for character in report_id
        )
    ):
        return None
    return directory / "evaluations" / f"{report_id}.json"


def _report_paths(report: Report) -> set[Path]:
    from screamingface._results.cases import DiskCases

    paths: set[Path] = set()
    for candidate in report.candidates:
        items = candidate.cases._items
        if not isinstance(items, DiskCases):
            continue
        try:
            folder = items.path.parent
            manifest = json.loads((folder / "run.json").read_text())
            path = evaluation_path(folder.parent, manifest.get("evaluation", {}).get("id"))
            if path is not None:
                paths.add(path)
        except (OSError, ValueError, AttributeError):
            continue
    return paths


def mark_report(report: Report, state: Literal["ready", "exporting", "rendering"]) -> None:
    for path in _report_paths(report):
        mark_evaluation(path, state)


@contextmanager
def report_operation(report: Report, state: Literal["exporting", "rendering"]) -> Iterator[None]:
    token = object()
    keys = [(os.getpid(), path.resolve()) for path in _report_paths(report)]
    with _lock:
        for key in keys:
            _active.setdefault(key, {})[token] = state
        mark_report(report, state)
    try:
        yield
    finally:
        with _lock:
            for key in keys:
                operations = _active[key]
                del operations[token]
                if not operations:
                    del _active[key]
            mark_report(report, "ready")


def mark_evaluation(path: Path, state: str) -> None:
    try:
        with _lock:
            value = json.loads(path.read_text())
            if "owner_pid" not in value:
                return  # WHY: legacy history must not be guessed to have crashed.
            _write_marker(path, value, state)
    except (OSError, ValueError, AttributeError, TypeError):
        # INVARIANT: optional lifecycle metadata cannot discard a usable Report.
        _logger.debug("Could not update saved-report lifecycle", exc_info=True)


def copy_evaluation(source: Path, destination: Path, state: str) -> None:
    # WHY: moving recovery must retain interruption discovery on both disks.
    try:
        with _lock:
            value = json.loads(source.read_text())
            if "owner_pid" not in value:
                return
            _write_marker(destination, value, state)
    except (OSError, ValueError, AttributeError, TypeError):
        _logger.debug("Could not copy saved-report lifecycle", exc_info=True)


def _write_marker(path: Path, value: dict, state: str) -> None:
    # INVARIANT: every marker writer preserves active presentation operations.
    operations = _active.get((os.getpid(), path.resolve()), {})
    pending = next(reversed(operations.values()), state)
    value.update(state=pending, owner_pid=os.getpid())
    atomic_json(path, value)
