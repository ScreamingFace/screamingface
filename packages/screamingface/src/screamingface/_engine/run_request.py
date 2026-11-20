"""What `POST /runs` sends for an evaluation (E5 P2 spec §4.1, D1, D8, D9b).

FEATURE: a detached Run (OME-1837). The Engine starts every Candidate itself, so the Run carries
each one's start: its url4 and the flags the start route used to take as headers.
"""

from __future__ import annotations

from collections.abc import Sequence
from uuid import uuid4

from screamingface._engine.runs import RunRequest, StartRequest
from screamingface._evaluation.model import Candidate, _Evaluation
from screamingface._results.run_context import URL4_RUN_LABEL, run_context
from screamingface._version import resolve_version


def start_request(candidate: Candidate) -> StartRequest:
    return StartRequest(
        name=candidate.name,
        url4=candidate.url4,
        answer_seed=candidate.answer_seed,
        capture=candidate.capture,
        use_cache=candidate.use_cache,
        replay_frozen_copy=candidate.replay_frozen_copy,
    )


def new_client_key() -> str:
    """A fresh key for every evaluate (P1 spec §4.1): a lost answer is re-sent under it."""
    return uuid4().hex


def run_request(
    evaluation: _Evaluation | None,
    candidates: Sequence[Candidate],
    *,
    detach: bool = False,
    deadline_s: int | None = None,
) -> RunRequest:
    """``evaluation`` is None for a raw-url4 or replay evaluation, which has no benchmark."""
    return RunRequest(
        client_key=new_client_key(),
        benchmark=URL4_RUN_LABEL if evaluation is None else evaluation.benchmark.id,
        case_count=0 if evaluation is None else evaluation.case_count,
        candidates=tuple(start_request(candidate) for candidate in candidates),
        client_version=resolve_version(),
        context=run_context(evaluation, candidates),
        detach=detach,
        deadline_s=deadline_s,
    )


__all__ = ["new_client_key", "run_request", "start_request"]
