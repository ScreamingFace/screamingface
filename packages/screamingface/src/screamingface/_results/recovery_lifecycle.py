"""Track explicit recovery while retaining interruption markers after cancellation."""

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from screamingface._results.lifecycle import copy_evaluation, evaluation_operation, evaluation_path
from screamingface._results.store import ResultStore, SavedRun
from screamingface.errors import ExecutionError


@contextmanager
def recovery_operation(
    store: ResultStore, selected: SavedRun | str, destination: str | Path | None
) -> Iterator[None]:
    if isinstance(selected, SavedRun):
        report_id = (selected.evaluation or {}).get("id")
    else:
        identity, members = store.member_manifests(selected)
        report_id = identity if members else None
        if not members:
            # WHY: run-ID aliases use the existing unique-run lookup. Lightweight
            # membership stays first so corrupt candidates still enter tracking.
            try:
                report_id = (store.load(selected).evaluation or {}).get("id")
            except (KeyError, OSError, ExecutionError):
                pass  # WHY: public selection retains its original lookup/error contract.
    source = evaluation_path(store.directory, report_id)
    target = (
        evaluation_path(Path(destination).expanduser(), report_id)
        if destination is not None
        else None
    )

    if source is not None and target is not None:
        copy_evaluation(source, target, "running")
    paths = {path for path in (source, target) if path is not None}
    with evaluation_operation(
        paths,
        "running",
        (ExecutionError,),
        resolve_interruption=True,
        handled_error=lambda exc: (
            isinstance(exc, ExecutionError) and exc.code == "candidates_failed"
        ),
    ):
        yield
