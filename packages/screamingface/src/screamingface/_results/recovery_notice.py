"""Announce interrupted saved evaluations when the researcher next opens the SDK."""

from __future__ import annotations

import json
import logging
from pathlib import Path

from screamingface._environment import running_in_notebook
from screamingface._notices import ClientNotice
from screamingface._results.lifecycle import evaluation_path
from screamingface._results.ownership import owner_alive as _owner_alive
from screamingface._results.ownership import recorded_owners
from screamingface._results.store import ResultStore, SavedRun
from screamingface._ui.notice_view import display_notebook_notice

_logger = logging.getLogger(__name__)
_shown: set[tuple[Path, str]] = set()


def recovery_notice(report_id: str, directory: Path) -> ClientNotice:
    call = (
        f"import screamingface as sf; sf.reports.get({report_id!r}, directory={str(directory)!r})"
    )
    return ClientNotice(
        code="evaluation_recovery",
        severity="info",
        title="Saved results are available to recover",
        body="Reopen completed results from an interrupted evaluation without rerunning models: "
        + call,
    )


def _is_interrupted(value: dict) -> bool:
    owners = [(value.get("owner_pid"), value.get("state")), *recorded_owners(value)]
    return any(
        isinstance(state, str)
        and state in {"running", "exporting", "rendering"}
        and isinstance(pid, int)
        and not isinstance(pid, bool)
        and pid > 0
        and not _owner_alive(pid)
        for pid, state in owners
    )


def _pending_report(store: ResultStore, run: SavedRun) -> str | None:
    selected = None
    try:
        membership = run.evaluation or {}
        path = evaluation_path(store.directory, membership.get("id"))
        if path is not None and _is_interrupted(json.loads(path.read_text())):
            selected = membership["id"]
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        _logger.debug("Could not inspect a saved evaluation for recovery", exc_info=True)
    return selected


def _display(notice: ClientNotice) -> None:
    try:
        display_notebook_notice(notice)
    except Exception:  # noqa: BLE001 - a display failure cannot abort SDK startup
        _logger.warning(notice.message)


def show_recoverable_results(store: ResultStore, engine_url: str) -> None:
    # WHY: no notebook banner on healthy runs, and no startup I/O for headless clients.
    if not running_in_notebook():
        return
    try:
        runs = store.list()
    except (OSError, ValueError, KeyError, TypeError):
        _logger.debug("Could not inspect saved evaluations for recovery", exc_info=True)
        return
    for run in runs:
        if run.engine_url != engine_url or not run.evaluation:
            continue
        report_id = _pending_report(store, run)
        if report_id is not None and (store.directory, report_id) not in _shown:
            _shown.add((store.directory, report_id))
            _display(recovery_notice(report_id, store.directory))


__all__: list[str] = []
