"""Best-effort lifecycle markers distinguish interrupted reports from healthy history."""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from screamingface._results.store import atomic_json

if TYPE_CHECKING:
    from screamingface.report import Report

_logger = logging.getLogger(__name__)


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


def mark_report(report: Report, state: Literal["ready", "exporting", "rendering"]) -> None:
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
    for path in paths:
        try:
            value = json.loads(path.read_text())
            if "owner_pid" not in value:
                continue  # WHY: legacy history must not be guessed to have crashed.
            value.update(state=state, owner_pid=os.getpid())
            atomic_json(path, value)
        except (OSError, ValueError, AttributeError, TypeError):
            # INVARIANT: optional lifecycle metadata cannot discard a usable Report.
            _logger.debug("Could not update saved-report lifecycle", exc_info=True)
