"""Best-effort lifecycle markers distinguish interrupted reports from healthy history."""

from __future__ import annotations

import json
import logging
import os
from collections.abc import Callable, Iterator
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
_interrupted: dict[tuple[int, Path], str] = {}


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
    try:
        folder = directory.resolve() / "evaluations"
        path = folder / f"{report_id}.json"
        return path if folder.resolve() == folder and not path.is_symlink() else None
    except (OSError, RuntimeError):
        return None


def _safe_marker(path: Path) -> bool:
    return (
        path.parent.name == "evaluations"
        and path.suffix == ".json"
        and evaluation_path(path.parent.parent, path.stem) is not None
    )


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
    with evaluation_operation(_report_paths(report), state, (Exception,)):
        yield


@contextmanager
def evaluation_operation(
    paths: set[Path],
    state: str,
    handled_errors: tuple[type[BaseException], ...],
    *,
    handled_error: Callable[[BaseException], bool] | None = None,
    resolve_interruption: bool = False,
) -> Iterator[None]:
    token = object()
    keys = []
    with _lock:
        for path in paths:
            try:
                key = (os.getpid(), path.resolve())
            except OSError:
                continue  # WHY: optional marker lookup cannot prevent a usable operation.
            keys.append(key)
            _active.setdefault(key, {})[token] = state
            mark_evaluation(path, state)
    settled = False
    try:
        yield
        settled = True
    except handled_errors as exc:
        settled = handled_error(exc) if handled_error is not None else True
        raise
    finally:
        _finish_operation(keys, token, state, settled, resolve_interruption)


def _finish_operation(
    keys: list[tuple[int, Path]],
    token: object,
    state: str,
    settled: bool,
    resolve_interruption: bool,
) -> None:
    with _lock:
        for key in keys:
            operations = _active[key]
            del operations[token]
            if not operations:
                del _active[key]
            if not settled:
                _interrupted[key] = state
            elif resolve_interruption:
                # WHY: explicit recovery can resolve a prior interrupted operation;
                # an unrelated successful export/display cannot hide that interruption.
                _interrupted.pop(key, None)
            mark_evaluation(key[1], "ready" if settled else state)


def mark_evaluation(path: Path, state: str) -> None:
    if not _safe_marker(path):
        return
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
    if not _safe_marker(source) or not _safe_marker(destination):
        return
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
    pending = next(
        reversed(operations.values()), _interrupted.get((os.getpid(), path.resolve()), state)
    )
    value.update(state=pending, owner_pid=os.getpid())
    atomic_json(path, value)
