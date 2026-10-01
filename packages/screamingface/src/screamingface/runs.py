"""List and recover paid results without starting another evaluation.

Results are retained until ``delete`` is explicitly called. Set
``SCREAMINGFACE_RESULTS_DIR`` to choose their location.
"""

from __future__ import annotations

import builtins
import hashlib
import shutil
from dataclasses import dataclass, replace
from pathlib import Path

from screamingface._core.ports import _RunOutcome
from screamingface._evaluation.model import _compiled_evaluation
from screamingface._evaluation.results import report_from_outcomes, report_from_url4_outcome
from screamingface._results.store import ResultStore, SavedRun
from screamingface.discovery import BenchmarkInfo
from screamingface.errors import ExecutionError, ScreamingFaceError
from screamingface.report import CandidateResult, Report


@dataclass(frozen=True)
class SavedRunInfo:
    key: str
    run_id: str
    candidate: str
    engine_url: str
    directory: Path
    downloaded: bool
    size_bytes: int
    evaluation_id: str | None


def list(*, directory: str | Path | None = None) -> builtins.list[SavedRunInfo]:
    """Find completed-run tickets, including downloads interrupted by a crash."""
    return [
        SavedRunInfo(
            run.key,
            run.outcome.run_id,
            run.candidate.name,
            run.engine_url,
            run.path.parent,
            run.path.exists(),
            sum(p.stat().st_size for p in run.path.parent.iterdir() if p.is_file()),
            run.evaluation["id"] if run.evaluation else None,
        )
        for run in _store(directory).list()
    ]


def delete(run_id: str, *, directory: str | Path | None = None) -> None:
    """Explicitly remove one saved candidate and its recovery metadata.

    Existing Reports backed by these files will no longer be readable.
    """
    run = _store(directory).load(run_id)
    shutil.rmtree(run.path.parent)


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

    local = _local(run)
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


def _decode(run: SavedRun, outcome: _RunOutcome) -> Report:
    if run.evaluation is None:
        return report_from_url4_outcome(run.candidate, outcome)
    context = run.evaluation
    evaluation = _compiled_evaluation(
        benchmark=BenchmarkInfo(**context["benchmark"]),
        limit=None,
        case_count=context["case_count"],
        candidates=(run.candidate,),
        required_models=run.candidate.models,
    )
    return report_from_outcomes(evaluation, ((run.candidate, outcome),))


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


def recover(
    run_id: str, *, directory: str | Path | None = None, destination: str | Path | None = None
) -> Report:
    """Reopen the evaluation containing this saved key or Engine run ID.

    Downloads missing results with fresh authentication. Raises ``candidates_failed``
    with ``partial_report`` and named failures when the evaluation is incomplete.
    """
    store = _store(directory)
    selected = store.load(run_id)
    reports: builtins.list[Report] = []
    errors: dict[str, ScreamingFaceError] = {}
    for run in _group(store, selected):
        try:
            if destination is not None:
                run = _store(destination).copy_run(run)
            reports.append(_decode(run, _fetch(run)))
        except ScreamingFaceError as exc:
            errors[run.candidate.name] = exc
    return _finish(selected, reports, errors)


async def recover_async(
    run_id: str, *, directory: str | Path | None = None, destination: str | Path | None = None
) -> Report:
    """Asynchronous network recovery with the same local result contract."""
    store = _store(directory)
    selected = store.load(run_id)
    reports: builtins.list[Report] = []
    errors: dict[str, ScreamingFaceError] = {}
    for run in _group(store, selected):
        try:
            if destination is not None:
                run = _store(destination).copy_run(run)
            reports.append(_decode(run, await _fetch_async(run)))
        except ScreamingFaceError as exc:
            errors[run.candidate.name] = exc
    return _finish(selected, reports, errors)
