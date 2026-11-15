"""Record evaluation membership before starting candidate runs."""

import os
from dataclasses import asdict
from uuid import uuid4

from screamingface._evaluation.model import Candidate, _Evaluation
from screamingface._results.store import ResultStore, atomic_json, storage_error


def prepare(
    store: ResultStore,
    evaluation: _Evaluation,
    candidates: tuple[Candidate, ...],
    *,
    report_id: str | None = None,
) -> dict[int, dict]:
    # FEATURE (OME-1785, spec D8): keyed by the Run's id, so `sf.runs.get(id).report()` finds it;
    # by the Run's `client_key` when the Engine did not register it.
    context = {
        "id": report_id or uuid4().hex,
        "owner_pid": os.getpid(),
        "state": "running",
        "benchmark": asdict(evaluation.benchmark),
        "case_count": evaluation.case_count,
        "candidates": [c.name for c in candidates],
    }
    try:
        atomic_json(store.directory / "evaluations" / f"{context['id']}.json", context)
    except OSError as exc:
        raise storage_error(exc) from exc
    return {id(candidate): context for candidate in candidates}
