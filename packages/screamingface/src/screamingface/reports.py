"""List and open saved reports without starting another evaluation.

Results are retained until ``delete`` is explicitly called. Set
``SCREAMINGFACE_RESULTS_DIR`` to choose their location.
"""

from __future__ import annotations

import asyncio
import builtins
import hashlib
import shutil
import sqlite3
import stat
from dataclasses import dataclass, replace
from pathlib import Path

from screamingface._core.ports import _RunOutcome
from screamingface._evaluation.model import _compiled_evaluation
from screamingface._evaluation.results import report_from_outcomes, report_from_url4_outcome
from screamingface._results.store import ResultStore, SavedRun, storage_error
from screamingface.discovery import BenchmarkInfo
from screamingface.errors import ExecutionError, ScreamingFaceError
from screamingface.report import CandidateResult, Report


@dataclass(frozen=True)
class SavedReportInfo:
    id: str
    candidates: tuple[str, ...]
    directory: Path
    downloaded: bool
    size_bytes: int


def _report_id(run: SavedRun) -> str:
    return run.evaluation["id"] if run.evaluation else run.key


def list(*, directory: str | Path | None = None) -> builtins.list[SavedReportInfo]:
    """List one saved report per evaluation, including interrupted downloads.

    Entries contain lightweight metadata, not decoded case results. ``downloaded``
    means every expected candidate has a local result; integrity is checked by get.
    """
    store = _store(directory)
    groups: dict[str, builtins.list[SavedRun]] = {}
    for run in store.list():
        groups.setdefault(_report_id(run), []).append(run)
    entries = []
    for report_id, runs in groups.items():
        selected = runs[0]
        names = tuple(
            selected.evaluation["candidates"] if selected.evaluation else [selected.candidate.name]
        )
        downloaded = {run.candidate.name for run in runs if run.path.exists()}
        entries.append(
            SavedReportInfo(
                id=report_id,
                candidates=names,
                directory=store.directory,
                downloaded=set(names) <= downloaded,
                size_bytes=sum(_directory_size(run.path.parent) for run in runs),
            )
        )
    return sorted(entries, key=lambda entry: entry.id)


def _directory_size(directory: Path) -> int:
    total = 0
    try:
        for path in directory.iterdir():
            # WHY: unpublished downloads/indices are transient and not saved report storage.
            if path.name.startswith("."):
                continue
            try:
                info = path.stat()
            except FileNotFoundError:
                continue
            if stat.S_ISREG(info.st_mode):
                total += info.st_size
    except FileNotFoundError:
        pass  # WHY: explicit report deletion can also win after manifests were listed.
    return total


def _selected(store: ResultStore, report_id: str) -> SavedRun:
    # WHY: old saved candidate keys remain usable for disk-error remediation.
    matches = [run for run in store.list() if _report_id(run) == report_id]
    return matches[0] if matches else store.load(report_id)


def delete(report_id: str, *, directory: str | Path | None = None) -> None:
    """Explicitly remove every saved candidate belonging to this report.

    Existing Reports backed by these files will no longer be readable.
    """
    store = _store(directory)
    selected = _selected(store, report_id)
    for run in _group(store, selected):
        shutil.rmtree(run.path.parent)
    # INVARIANT: saved metadata must not redirect deletion outside this manifest folder.
    manifests = store.directory / "evaluations"
    manifest = manifests / f"{_report_id(selected)}.json"
    if manifest.parent == manifests:
        manifest.unlink(missing_ok=True)


def _store(directory: str | Path | None) -> ResultStore:
    return ResultStore(None if directory is None else Path(directory))


def _local(run: SavedRun) -> _RunOutcome | None:
    if not run.path.exists():
        return None
    artifact = run.outcome.artifact
    if artifact is not None:
        with run.path.open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
        if run.path.stat().st_size != artifact.size_bytes or digest != artifact.sha256:
            raise ExecutionError(
                "Saved result failed integrity verification", code="result_integrity_mismatch"
            )
    return replace(run.outcome, result_path=run.path)


def _fetch(run: SavedRun) -> _RunOutcome:
    from screamingface._engine.result_download import download_sync
    from screamingface._engine.transport import _mint_sync
    from screamingface.client import Client

    local = _local(run)
    if local is not None:
        return local
    if run.outcome.artifact is None:
        raise ExecutionError(
            "Inline result was not saved before interruption; no Engine ticket",
            code="result_unavailable",
        )
    # WHY: authenticate afresh to this Engine; saved metadata never contains a credential.
    with Client(engine_url=run.engine_url) as client:
        return download_sync(client._http, run, lambda: _mint_sync(client._http))


async def _fetch_async(run: SavedRun) -> _RunOutcome:
    from screamingface._engine.result_download import download_async
    from screamingface._engine.transport import _mint_async
    from screamingface.client import AsyncClient

    local = await asyncio.to_thread(_local, run)
    if local is not None:
        return local
    if run.outcome.artifact is None:
        raise ExecutionError(
            "Inline result was not saved before interruption; no Engine ticket",
            code="result_unavailable",
        )
    async with AsyncClient(engine_url=run.engine_url) as client:
        return await download_async(client._http, run, lambda: _mint_async(client._http))


def _group(store: ResultStore, selected: SavedRun) -> builtins.list[SavedRun]:
    if selected.evaluation is None:
        return [selected]
    related = {
        run.candidate.name: run
        for run in store.list()
        if run.evaluation and run.evaluation["id"] == selected.evaluation["id"]
    }
    return [related[name] for name in selected.evaluation["candidates"] if name in related]


def _validate_sibling(selected: SavedRun, run: SavedRun) -> None:
    if selected.evaluation is None:
        return
    # INVARIANT: every recovered Candidate must use the selected Evaluation's context;
    # otherwise a corrupt sibling could fail Report construction outside settlement.
    fields = ("id", "benchmark", "case_count", "candidates")
    if run.evaluation is None or any(
        run.evaluation.get(field) != selected.evaluation.get(field) for field in fields
    ):
        raise ExecutionError(
            "Saved candidate has conflicting evaluation membership",
            code="result_metadata_invalid",
        )


def _decode(run: SavedRun, outcome: _RunOutcome) -> Report:
    if run.evaluation is None:
        return report_from_url4_outcome(run.candidate, outcome)
    try:
        context = run.evaluation
        evaluation = _compiled_evaluation(
            benchmark=BenchmarkInfo(**context["benchmark"]),
            limit=context["case_count"],
            case_count=context["case_count"],
            candidates=(run.candidate,),
            required_models=run.candidate.models,
        )
        return report_from_outcomes(evaluation, ((run.candidate, outcome),))
    except (KeyError, TypeError, ValueError) as exc:
        raise ExecutionError(
            "Invalid saved evaluation metadata", code="result_metadata_invalid"
        ) from exc


def _finish(
    selected: SavedRun, reports: builtins.list[Report], errors: dict[str, ScreamingFaceError]
) -> Report:
    candidates: builtins.list[CandidateResult] = [
        c for report in reports for c in report.candidates
    ]
    expected = (
        selected.evaluation["candidates"] if selected.evaluation else [selected.candidate.name]
    )
    present = {c.name for c in candidates}
    missing = {
        name: errors[name].code if name in errors else "result_not_received"
        for name in expected
        if name not in present
    }
    report = (
        Report(
            benchmark=reports[0].benchmark, case_count=reports[0].case_count, candidates=candidates
        )
        if reports
        else None
    )
    if missing:
        # INVARIANT: use the SDK's existing Partial Report contract, never pretend complete.
        raise ExecutionError(
            "Evaluation recovery is incomplete; completed results are in "
            "partial_report. No models were rerun.",
            code="candidates_failed",
            details={"failed": missing, **_error_messages(errors)},
            partial_report=report,
        ) from next(iter(errors.values()), None)
    assert report is not None
    return report


def _error_messages(errors: dict[str, ScreamingFaceError]) -> dict[str, object]:
    return {"failure_messages": {name: str(exc) for name, exc in errors.items()}} if errors else {}


def get(
    report_id: str, *, directory: str | Path | None = None, destination: str | Path | None = None
) -> Report:
    """Open a saved report by its ID from list(), without rerunning models.

    Downloads missing results with fresh authentication. Raises ``candidates_failed``
    with ``partial_report`` and named failures when the evaluation is incomplete.
    """
    store = _store(directory)
    selected = _selected(store, report_id)
    reports: builtins.list[Report] = []
    errors: dict[str, ScreamingFaceError] = {}
    for run in _group(store, selected):
        try:
            _validate_sibling(selected, run)
            if destination is not None:
                run = _store(destination).copy_run(run)
            reports.append(_decode(run, _fetch(run)))
        except (OSError, sqlite3.Error) as exc:
            errors[run.candidate.name] = storage_error(exc, run.key)
        except ScreamingFaceError as exc:
            errors[run.candidate.name] = exc
    return _finish(selected, reports, errors)


async def get_async(
    report_id: str, *, directory: str | Path | None = None, destination: str | Path | None = None
) -> Report:
    """Open a saved report asynchronously with the same local result contract."""
    store = _store(directory)
    selected = _selected(store, report_id)
    reports: builtins.list[Report] = []
    errors: dict[str, ScreamingFaceError] = {}
    for run in _group(store, selected):
        try:
            _validate_sibling(selected, run)
            if destination is not None:
                run = await asyncio.to_thread(_store(destination).copy_run, run)
            outcome = await _fetch_async(run)
            reports.append(await asyncio.to_thread(_decode, run, outcome))
        except (OSError, sqlite3.Error) as exc:
            errors[run.candidate.name] = storage_error(exc, run.key)
        except ScreamingFaceError as exc:
            errors[run.candidate.name] = exc
    return _finish(selected, reports, errors)
