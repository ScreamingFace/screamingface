"""A Run's Report, built once when the Run has ended, from the Engine's records (E5 P2 spec
D9b, D14, §4.6).

FEATURE: a detached Run (OME-1837). STORY: as a researcher who started a Run elsewhere, or whose
kernel restarted, I get the Report the machine that started it would have built.

INVARIANT (D14): one build for every Report of a Run: an attached evaluation's, with the results
its follow fetched, and `Run.report()`'s on any machine, through a `Client` or an `AsyncClient`
(whose form only fetches on the event loop before handing the same build its results). Each
Candidate's outcome comes from its record and its result from the same transport (a result
already saved here with the record's checksum is not fetched again), then the same
`completed_report`, or `candidates_failed` with the Partial Report. So they are all equal by
construction.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Mapping
from concurrent.futures import ThreadPoolExecutor
from typing import TYPE_CHECKING, cast

from screamingface._core.ports import (
    _AsyncRunReattaching,
    _EndedRun,
    _RunOutcome,
    _RunReattaching,
)
from screamingface._evaluation.model import Candidate, _Evaluation
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

#: Results the build fetches at once, of those not already here.
_DOWNLOADS = 4

if TYPE_CHECKING:
    from screamingface.report import Report


def engine_report(transport: object, run_id: str, ended: _EndedRun) -> Report:
    """The ended Run's Report, from its context, its Candidates' records and their results.
    The caller reads ``ended`` from the Engine (core imports no adapter)."""
    if not isinstance(transport, _RunReattaching):
        raise results_not_local(run_id)
    evaluation, candidates = evaluation_from_context(ended.context, ended.starts)
    if evaluation is None:
        return _url4_report(settled_from_records(transport, candidates, ended.outcomes), run_id)
    from screamingface._evaluation.runner import _prepared_results

    # The saved results are kept under the Run's id, as the attached evaluation keeps them.
    transport.adopt_run(run_id, candidates)
    with _prepared_results(transport, evaluation, candidates):
        settled = settled_from_records(transport, candidates, ended.outcomes)
        report = _completed(evaluation, settled, run_id)
    if report is not None:
        return report
    raise_candidates_failed(evaluation, settled, run_id)


async def engine_report_async(transport: object, run_id: str, ended: _EndedRun) -> Report:
    """The async twin of ``engine_report``, for an `AsyncClient`'s Run: its results are fetched
    on the event loop, then the same build takes them."""
    if not isinstance(transport, _AsyncRunReattaching):
        raise results_not_local(run_id)
    evaluation, candidates = evaluation_from_context(ended.context, ended.starts)
    if evaluation is None:
        return _url4_report(await _settled_async(transport, candidates, ended.outcomes), run_id)
    from screamingface._evaluation.runner import _prepared_results

    transport.adopt_run(run_id, candidates)
    with _prepared_results(transport, evaluation, candidates):
        settled = await _settled_async(transport, candidates, ended.outcomes)
        report = _completed(evaluation, settled, run_id)
    if report is not None:
        return report
    raise_candidates_failed(evaluation, settled, run_id)


async def _settled_async(
    transport: object,
    candidates: tuple[Candidate, ...],
    outcomes: tuple[_RunOutcome | Exception, ...],
) -> _Settled:
    fetched, kept = await refetched_async(transport, candidates, outcomes, {})
    return settled_from_records(transport, candidates, fetched, kept)


def _completed(evaluation: _Evaluation, settled: _Settled, run_id: str) -> Report | None:
    """The completed Report, or None when a Candidate did not succeed. WHY None and not the
    raise: `candidates_failed` is raised outside the `except`, and outside the results' context,
    so the error keeps no private carrier as its `__context__`."""
    try:
        return completed_report(evaluation, settle(settled), run_id)
    except _CandidatesFailed:
        return None


def _url4_report(settled: _Settled, run_id: str) -> Report:
    from screamingface._evaluation.results import report_from_url4_outcome
    from screamingface._evaluation.url4 import _require_replay_statement

    ((candidate, outcome),) = settled
    assert isinstance(outcome, _RunOutcome)
    report = with_run_id(report_from_url4_outcome(candidate, outcome), run_id)
    # INVARIANT (OME-1307): a replay's Report, wherever it is built, proves it replayed.
    _require_replay_statement(candidate.replay_frozen_copy, outcome, report)
    return report


def settled_from_records(
    transport: object,
    candidates: tuple[Candidate, ...],
    outcomes: tuple[_RunOutcome | Exception, ...],
    kept: Mapping[int, _RunOutcome] | None = None,
) -> _Settled:
    """Each Candidate's outcome for the Report, once the Run has ended (D14): the result
    ``kept`` holds (an attached follow's), else fetched now; a Candidate that did not succeed
    keeps its error. A transport that cannot fetch (a test fake) hands its outcomes in whole."""
    have = kept or {}
    save = transport.save_result if isinstance(transport, _RunReattaching) else None
    results: dict[int, _RunOutcome | _Failed] = {}
    fetch: list[int] = []
    for index, outcome in enumerate(outcomes):
        if isinstance(outcome, Exception):
            results[index] = _Failed(outcome)
        elif index in have or save is None:
            results[index] = have.get(index, outcome)
        else:
            fetch.append(index)
    if save is not None and fetch:
        # WHY side by side: a Run read on another machine fetches every result.
        pool = ThreadPoolExecutor(max_workers=_DOWNLOADS, thread_name_prefix="sf-result")
        try:
            fetched = pool.map(
                lambda index: _saved(save, candidates[index], outcomes[index]), fetch
            )
            results.update(zip(fetch, fetched, strict=True))
        except BaseException:
            # WHY not a `with` block (#1878 review): leaving one waits for every running
            # download, so Ctrl-C would seem to hang until they finished.
            pool.shutdown(wait=False, cancel_futures=True)
            raise
        pool.shutdown()
    return _lone_raised(tuple((c, results[i]) for i, c in enumerate(candidates)))


async def refetched_async(
    transport: object,
    candidates: tuple[Candidate, ...],
    outcomes: tuple[_RunOutcome | Exception, ...],
    kept: Mapping[int, _RunOutcome],
) -> tuple[tuple[_RunOutcome | Exception, ...], dict[int, _RunOutcome]]:
    """For an async evaluation: fetch, before the build, each result its follow could not, so
    ``settled_from_records`` (which fetches with a sync transport only) gets them all kept
    (spec D14). A transport that cannot fetch (a test fake) hands its outcomes in whole."""
    save = cast(
        Callable[[Candidate, _RunOutcome], Awaitable[_RunOutcome]] | None,
        getattr(transport, "save_result", None),
    )
    have = dict(kept)
    if not callable(save):
        return outcomes, have
    # WHY side by side, as many at once as the sync build: a Run read on another machine
    # fetches every result.
    slots = asyncio.Semaphore(_DOWNLOADS)

    async def fetched(index: int, outcome: _RunOutcome | Exception) -> _RunOutcome | Exception:
        if isinstance(outcome, Exception) or index in have:
            return outcome
        async with slots:
            try:
                have[index] = await save(candidates[index], outcome)
            except Exception as exc:  # noqa: BLE001 - one Candidate's failure (spec C1b)
                return exc
        return have[index]

    return tuple(await asyncio.gather(*map(fetched, range(len(outcomes)), outcomes))), have


def _saved(
    save: Callable[[Candidate, _RunOutcome], _RunOutcome],
    candidate: Candidate,
    outcome: _RunOutcome,
) -> _RunOutcome | _Failed:
    try:
        return save(candidate, outcome)
    except Exception as exc:  # noqa: BLE001 - one Candidate's failure (spec C1b)
        return _Failed(exc)


def _lone_raised(settled: _Settled) -> _Settled:
    """WHY: a one-Candidate evaluation has always raised its Candidate's own error, never
    `candidates_failed`; every Report of a Run keeps that."""
    if len(settled) == 1 and isinstance(settled[0][1], _Failed):
        raise settled[0][1].error
    return settled


def results_not_local(run_id: str) -> ExecutionError:
    return ExecutionError(
        f"The results of Run {run_id} are not on this machine",
        code="results_not_local",
        permanent=True,
        hint="Open the report on the machine that ran the evaluation.",
    )


__all__ = [
    "engine_report",
    "engine_report_async",
    "results_not_local",
    "refetched_async",
    "settled_from_records",
]
