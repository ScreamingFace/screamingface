"""Record evaluation membership before starting candidate runs."""

import os
from dataclasses import asdict
from uuid import uuid4

from screamingface._evaluation.model import Candidate, _Evaluation
from screamingface._results.store import ResultStore, atomic_json, storage_error


def prepare(
    store: ResultStore, evaluation: _Evaluation, candidates: tuple[Candidate, ...]
) -> dict[int, dict]:
    context = {
        "id": uuid4().hex,
        "state": "running",
        "owner_pid": os.getpid(),
        "benchmark": asdict(evaluation.benchmark),
        "case_count": evaluation.case_count,
        "candidates": [c.name for c in candidates],
    }
    try:
        atomic_json(store.directory / "evaluations" / f"{context['id']}.json", context)
    except OSError as exc:
        raise storage_error(exc) from exc
    return {id(candidate): context for candidate in candidates}
