"""The Evaluation outcome when one or more Candidates fail (spec 2026-09-28 §5, ADR-0002).

FEATURE: OME-1071 / OME-1067 — one failed Candidate does not stop its siblings. The runner
lets every sibling end, then this module turns the settled Candidates into ONE public
`ExecutionError(code="candidates_failed")` that carries a Partial Report.
AIDEV-NOTE: both runner twins settle through `settle`, so sync and async cannot drift.
"""

from __future__ import annotations

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


def raise_candidates_failed(evaluation: _Evaluation, failed: _CandidatesFailed) -> NoReturn:
    """Raise `candidates_failed` from the first failure, with the Partial Report (§5.2)."""
    successes: list[CandidateResult] = []
    failures: list[tuple[Candidate, Exception]] = []
    for candidate, outcome in failed.settled:
        if isinstance(outcome, _Failed):
            failures.append((candidate, outcome.error))
            continue
        try:
            successes.append(_decoded(evaluation, candidate, outcome))
        except Exception as exc:  # noqa: BLE001 - any decode failure fails this Candidate only
            # WHY: a Run that succeeded but whose result does not decode has no Candidate
            # Result; it is named as failed rather than hiding its siblings' results.
            failures.append((candidate, exc))
    named = ", ".join(f"{candidate.name} ({failure_code(exc)})" for candidate, exc in failures)
    raise ExecutionError(
        f"{len(failures)} of {len(failed.settled)} Candidates failed: {named}",
        code="candidates_failed",
        details={"failed": {candidate.name: failure_code(exc) for candidate, exc in failures}},
        # INVARIANT: the Partial Report names only Candidates that succeeded; `None` when
        # none did, because a Report requires at least one Candidate.
        partial_report=(
            Report(
                benchmark=evaluation.benchmark,
                case_count=evaluation.case_count,
                candidates=successes,
            )
            if successes
            else None
        ),
    ) from failures[0][1]


def _decoded(
    evaluation: _Evaluation, candidate: Candidate, outcome: _RunOutcome
) -> CandidateResult:
    # WHY the one-Candidate Report: it applies exactly the final Report's validation.
    return report_from_outcomes(evaluation, ((candidate, outcome),)).candidates[0]


__all__: list[str] = []
