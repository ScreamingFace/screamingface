"""The Evaluation outcome when one or more Candidates fail (spec 2026-09-28 §5, ADR-0002).

FEATURE: OME-1071 / OME-1067 — one failed Candidate does not stop its siblings. The runner
lets every sibling end, then this module turns the settled Candidates into ONE public
`ExecutionError(code="candidates_failed")` that carries a Partial Report.
AIDEV-NOTE: both runner twins settle through `settle`, so sync and async cannot drift.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import NoReturn

from screamingface._core.ports import _RunOutcome
from screamingface._evaluation.model import Candidate, _Evaluation
from screamingface._evaluation.results import report_from_outcomes
from screamingface.errors import ExecutionError, ScreamingFaceError
from screamingface.report import CandidateResult, Report

# WHY a fixed code: `details["failed"]` is machine-read, so a failure outside the SDK's
# error classes (a defect, a library error) still needs one stable value to match on.
_FALLBACK_CODE = "unexpected_error"
_logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class _Failed:
    """One Candidate whose `transport.run()` raised an ordinary `Exception` (spec C1b)."""

    error: Exception


type _Settled = tuple[tuple[Candidate, _RunOutcome | _Failed], ...]


class _CandidatesFailed(Exception):  # noqa: N818 - a private carrier, not a public error
    """Carries every settled Candidate from the runner to `evaluate_*`.

    INVARIANT: it never reaches the caller — `evaluate_sync/_async` turn it into
    `candidates_failed` at once, because only they hold the `_Evaluation` that decodes
    the Partial Report.
    """

    def __init__(self, settled: _Settled) -> None:
        super().__init__("one or more Candidates failed")
        self.settled = settled


def settle(settled: _Settled) -> tuple[tuple[Candidate, _RunOutcome], ...]:
    """The outcomes when every Candidate succeeded; else raise `_CandidatesFailed`."""
    outcomes = tuple(
        (candidate, outcome) for candidate, outcome in settled if isinstance(outcome, _RunOutcome)
    )
    if len(outcomes) != len(settled):
        raise _CandidatesFailed(settled)
    return outcomes


def failure_code(error: BaseException) -> str:
    """The code a caller matches on: the SDK's own, else the stable fallback."""
    return error.code if isinstance(error, ScreamingFaceError) else _FALLBACK_CODE


def raise_candidates_failed(evaluation: _Evaluation, settled: _Settled) -> NoReturn:
    """Raise `candidates_failed` from the first failure, with the Partial Report (§5.2).

    AIDEV-NOTE: call it OUTSIDE the `except _CandidatesFailed` block, so the raised error's
    `__context__` does not keep the carrier (and every settled result body) alive.
    """
    successes, failures = _decode_candidates(evaluation, settled)
    _raise_failed(evaluation, len(settled), successes, failures)


def completed_report(
    evaluation: _Evaluation, outcomes: tuple[tuple[Candidate, _RunOutcome], ...]
) -> Report:
    # INVARIANT: completed transports still settle indexing/decoding per candidate.
    successes, failures = _decode_candidates(evaluation, outcomes)
    if failures:
        _raise_failed(evaluation, len(outcomes), successes, failures)
    return Report(
        benchmark=evaluation.benchmark, case_count=evaluation.case_count, candidates=successes
    )


def _decode_candidates(
    evaluation: _Evaluation, settled: _Settled
) -> tuple[list[CandidateResult], list[tuple[Candidate, Exception]]]:
    successes: list[CandidateResult] = []
    failures: list[tuple[Candidate, Exception]] = []
    for candidate, outcome in settled:
        if isinstance(outcome, _Failed):
            failures.append((candidate, outcome.error))
            continue
        try:
            successes.append(_decoded(evaluation, candidate, outcome))
        except Exception as exc:  # noqa: BLE001 - any decode failure fails this Candidate only
            # WHY: a Run that succeeded but whose result does not decode has no Candidate
            # Result; it is named as failed rather than hiding its siblings' results.
            failures.append((candidate, exc))
    return successes, failures


def _raise_failed(
    evaluation: _Evaluation,
    count: int,
    successes: list[CandidateResult],
    failures: list[tuple[Candidate, Exception]],
) -> NoReturn:
    partial, unavailable = _partial_report(evaluation, successes)
    named = ", ".join(f"{candidate.name} ({failure_code(exc)})" for candidate, exc in failures)
    error = ExecutionError(
        f"{len(failures)} of {count} Candidates failed: {named}",
        code="candidates_failed",
        details={"failed": {candidate.name: failure_code(exc) for candidate, exc in failures}},
        # WHY a hint: IPython shows only message, hint and code, so it must say where the
        # paid results of the Candidates that succeeded are.
        hint=(
            "The Candidates that succeeded are in `error.partial_report`; "
            "`error.details['failed']` names each failed Candidate and its code."
            if partial is not None
            else "No Candidate succeeded; `error.details['failed']` names each failed "
            "Candidate and its code."
        ),
        partial_report=partial,
    )
    if unavailable is not None:
        error.add_note(f"The Partial Report could not be built: {unavailable}")
    raise error from failures[0][1]


def _partial_report(
    evaluation: _Evaluation, successes: list[CandidateResult]
) -> tuple[Report | None, Exception | None]:
    """The Partial Report, or `None` with the reason it could not be built.

    INVARIANT: the Partial Report names only Candidates that succeeded; `None` when none
    did, because a Report requires at least one Candidate.
    WHY a guard: every Candidate already passed its own one-Candidate Report, so only a
    cross-Candidate rule (for example two equal names) can fail here. That failure must not
    replace `candidates_failed` — the caller still learns which Candidates failed; the
    reason is logged and noted on the error.
    """
    if not successes:
        return None, None
    try:
        return (
            Report(
                benchmark=evaluation.benchmark,
                case_count=evaluation.case_count,
                candidates=successes,
            ),
            None,
        )
    except (TypeError, ValueError) as exc:
        _logger.exception("ScreamingFace could not build the Partial Report")
        return None, exc


def _decoded(
    evaluation: _Evaluation, candidate: Candidate, outcome: _RunOutcome
) -> CandidateResult:
    # WHY the one-Candidate Report (and not `results._candidate_result` alone): the Report
    # adds the per-Candidate Benchmark and Case-count checks, so a bad Candidate is named
    # by itself here. `completion.py` validates live rows the same way.
    return report_from_outcomes(evaluation, ((candidate, outcome),)).candidates[0]


__all__: list[str] = []
