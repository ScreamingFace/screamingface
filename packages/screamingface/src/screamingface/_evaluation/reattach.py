"""A Run's Report, rebuilt from the Engine on any machine (E5 P2 spec D9b, D14, §4.6).

FEATURE: a detached Run (OME-1837). STORY: as a researcher who started a Run elsewhere, or whose
kernel restarted, I get the Report the machine that started it would have built.

INVARIANT (D14): the Report is built exactly as an attached evaluation builds it: each Candidate's
outcome from its record, its result saved by the same transport (to this machine's store when
results are saved), and the same `completed_report`, or `candidates_failed` with the Partial
Report. So the two are equal field by field.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from screamingface._core.ports import _RunOutcome, _RunReattaching
from screamingface._engine import runs as wire
from screamingface._engine.run_record import candidate_outcome
from screamingface._evaluation.model import Candidate
from screamingface._evaluation.outcome import (
    _CandidatesFailed,
    _Failed,
    _Settled,
    completed_report,
    raise_candidates_failed,
    settle,
    with_run_id,
)
from screamingface._results.run_context import evaluation_from_context
from screamingface.errors import ExecutionError

if TYPE_CHECKING:
    from screamingface.client import Client
    from screamingface.report import Report


def engine_report(client: Client, run_id: str) -> Report:
    """The ended Run's Report, from its context, its Candidates' records and their results."""
    transport = client._transport
    if not isinstance(transport, _RunReattaching):
        raise _not_here(run_id)
    request = client._http_request
    run = wire.get_sync(request, run_id)
    if run.context is None or any(c.start is None for c in run.candidates):
        # A Run from before P2 kept neither: only the machine that ran it has its results.
        raise _not_here(run_id)
    context = wire.context_sync(request, run_id, run.context)
    starts = tuple(c.start for c in run.candidates if c.start is not None)
    evaluation, candidates = evaluation_from_context(context, starts)
    transport.adopt_run(run_id, candidates)
    if evaluation is None:
        return _url4_report(transport, run_id, candidates, run.candidates)
    from screamingface._evaluation.runner import _prepared_results

    with _prepared_results(transport, evaluation, candidates):
        settled = _settled(transport, run_id, candidates, run.candidates)
        try:
            return completed_report(evaluation, settle(settled), run_id)
        except _CandidatesFailed:
            pass
    raise_candidates_failed(evaluation, settled, run_id)


def _url4_report(
    transport: _RunReattaching,
    run_id: str,
    candidates: tuple[Candidate, ...],
    records: tuple[wire.CandidateRecord, ...],
) -> Report:
    from screamingface._evaluation.results import report_from_url4_outcome

    ((candidate, outcome),) = _settled(transport, run_id, candidates, records)
    assert isinstance(outcome, _RunOutcome)
    return with_run_id(report_from_url4_outcome(candidate, outcome), run_id)


def _settled(
    transport: _RunReattaching,
    run_id: str,
    candidates: tuple[Candidate, ...],
    records: tuple[wire.CandidateRecord, ...],
) -> _Settled:
    settled: _Settled = tuple(
        (candidate, _outcome(transport, run_id, candidate, record))
        for candidate, record in zip(candidates, records, strict=True)
    )
    # WHY: a one-Candidate evaluation raises its Candidate's own error, as it does attached.
    if len(settled) == 1 and isinstance(settled[0][1], _Failed):
        raise settled[0][1].error
    return settled


def _outcome(
    transport: _RunReattaching, run_id: str, candidate: Candidate, record: wire.CandidateRecord
) -> _RunOutcome | _Failed:
    try:
        return transport.save_result(candidate, candidate_outcome(run_id, record))
    except Exception as exc:  # noqa: BLE001 - one Candidate's failure (spec C1b)
        return _Failed(exc)


def _not_here(run_id: str) -> ExecutionError:
    return ExecutionError(
        f"The results of Run {run_id} are not on this machine",
        code="results_not_local",
        permanent=True,
        hint="Open the report on the machine that ran the evaluation.",
    )


__all__ = ["engine_report"]
