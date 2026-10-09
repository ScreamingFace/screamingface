"""Reproduce a submitted score from its frozen copy and record that it reproduced (OME-1307).

FEATURE: E14 B5 (spec `02-frozen-copy-design.md` §7). The score's own url4 and answer seed run
again with the frozen copy stored with the score. The Engine answers every model and web-tool call
from the copy or fails the case, so a replay costs no provider spend. The result is judged against
the stored numbers by one pure function, and an exact one is recorded on the board.

INVARIANT: this module never starts a normal, paid run. A score that cannot name a complete frozen
copy starts no run at all, and a run the Engine did not acknowledge as a replay is stopped (the
transport) or refused (`evaluate_url4_*`) before it is judged.
"""

from __future__ import annotations

import warnings
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Literal, cast
from uuid import UUID

from screamingface._evaluation.url4 import evaluate_url4_async, evaluate_url4_sync
from screamingface._report_primitives import CaseId
from screamingface._scoreboard.leaderboards import _client_info
from screamingface.errors import ExecutionError
from screamingface.leaderboard import LeaderboardScore
from screamingface.warnings import EvaluationWarning

if TYPE_CHECKING:
    from screamingface.client import AsyncClient, Client
    from screamingface.report import CandidateResult

type ReproductionOutcome = Literal["exact", "failed", "not_reproducible"]


@dataclass(frozen=True, slots=True)
class Reproduction:
    """What `reproduce` found when it ran a score again from its frozen copy.

    `outcome` is `exact` (the replay gave the stored score and case count on the same benchmark
    revision), `failed` (it ran or tried to, with `reason` saying why) or `not_reproducible` (the
    score has no complete frozen copy, so no run started). `missed_cases` lists the cases the
    frozen copy could not answer. `recorded` says whether the board stored an exact reproduction,
    and `record_error` says why not when an exact replay could not be recorded.
    """

    outcome: ReproductionOutcome
    reason: str | None = None
    missed_cases: tuple[CaseId, ...] = ()
    result: CandidateResult | None = None
    recorded: bool = False
    record_error: str | None = None


def _classify(
    score: LeaderboardScore, result: CandidateResult
) -> tuple[ReproductionOutcome, str | None, tuple[CaseId, ...]]:
    """Judge one replay against the stored score; a pure function of the two.

    INVARIANT: the order of `checks` is the contract (spec §7). A replay code outranks everything,
    since a run that missed the copy has nothing to compare. Then a run failure, then the benchmark
    revision (a changed exam makes the score meaningless to compare), then the numbers, compared
    exactly (one ulp is a different result).
    """
    missed = tuple(
        dict.fromkeys(
            case.case_id
            for case in result.cases
            if any(failure.code == "frozen_copy_miss" for failure in case.failures)
        )
    )
    failures = (*result.failures, *(f for case in result.cases for f in case.failures))
    checks = (
        ("frozen_copy_miss", bool(missed)),
        ("frozen_copy_unavailable", any(f.code == "frozen_copy_unavailable" for f in failures)),
        ("run_failed", bool(result.failures)),
        ("benchmark_revision_changed", result.benchmark.revision != score.benchmark_revision),
        (
            "score_differs",
            result.score != score.score or len(result.cases) != score.total_questions,
        ),
    )
    reason = next((name for name, failed in checks if failed), None)
    return (
        ("exact" if reason is None else "failed"),
        reason,
        missed if reason == "frozen_copy_miss" else (),
    )


def _not_reproducible(score: LeaderboardScore) -> Reproduction | None:
    """The refusal for a score with no complete frozen copy, before any run.

    INVARIANT: a score that cannot name everything a replay needs is `unknown`. A `complete` score
    with no copy id would run without `X-Replay-Frozen-Copy`, which is a normal, paid run, and a
    score with no benchmark revision could never match one.
    """
    if score.capture_status == "partial":
        return Reproduction(outcome="not_reproducible", reason="partial")
    if (
        score.capture_status is None
        or score.frozen_copy_id is None
        or score.benchmark_revision is None
    ):
        return Reproduction(outcome="not_reproducible", reason="unknown")
    return None


def _score_argument(score: object) -> LeaderboardScore | UUID | str:
    if not isinstance(score, LeaderboardScore | UUID | str):
        raise TypeError("score must be an sf.LeaderboardScore, a UUID or a score id string")
    return score


def _warn_if_still_running(exc: ExecutionError) -> None:
    """Tell the user when the stop of an unacknowledged replay failed (its run may still go on)."""
    if exc.hint is not None:
        warnings.warn(exc.user_message, EvaluationWarning, stacklevel=4)


def reproduce_sync(
    client: Client, score: LeaderboardScore | UUID | str, record: bool
) -> Reproduction:
    selected = _score_argument(score)
    if not isinstance(selected, LeaderboardScore):
        selected = client.leaderboards.get_score(selected)
    reproduction = _not_reproducible(selected) or _replayed_sync(client, selected)
    result = reproduction.result
    if record and reproduction.outcome == "exact" and result is not None:
        reproduction = _record_sync(client, selected, result, reproduction)
    return reproduction


def _replayed_sync(client: Client, score: LeaderboardScore) -> Reproduction:
    try:
        report = evaluate_url4_sync(
            client._transport,
            score.url4,
            None,
            None,
            answer_seed=score.answer_seed,
            # The Engine refuses X-Capture with X-Replay-Frozen-Copy.
            capture=False,
            replay_frozen_copy=score.frozen_copy_id,
        )
    except ExecutionError as exc:
        if exc.code != "replay_unsupported":
            raise
        _warn_if_still_running(exc)
        return Reproduction(outcome="failed", reason="replay_unsupported")
    result = report.candidates[0]
    outcome, reason, missed = _classify(score, result)
    return Reproduction(outcome=outcome, reason=reason, missed_cases=missed, result=result)


def _record_sync(
    client: Client,
    score: LeaderboardScore,
    result: CandidateResult,
    reproduction: Reproduction,
) -> Reproduction:
    try:
        client.leaderboards._record_reproduction(
            score.id,
            run_id=result.run_id,
            # The replay's own numbers. The board compares them with the stored score exactly.
            score=cast(float, result.score),
            total_questions=len(result.cases),
            frozen_copy_id=score.frozen_copy_id,
            client=_client_info(),
        )
    except Exception as exc:  # noqa: BLE001 - a failed record never undoes an exact replay
        return replace(reproduction, record_error=str(exc))
    return replace(reproduction, recorded=True)


async def reproduce_async(
    client: AsyncClient, score: LeaderboardScore | UUID | str, record: bool
) -> Reproduction:
    selected = _score_argument(score)
    if not isinstance(selected, LeaderboardScore):
        selected = await client.leaderboards.get_score(selected)
    reproduction = _not_reproducible(selected) or await _replayed_async(client, selected)
    result = reproduction.result
    if record and reproduction.outcome == "exact" and result is not None:
        reproduction = await _record_async(client, selected, result, reproduction)
    return reproduction


async def _replayed_async(client: AsyncClient, score: LeaderboardScore) -> Reproduction:
    try:
        report = await evaluate_url4_async(
            client._transport,
            score.url4,
            None,
            None,
            answer_seed=score.answer_seed,
            # The Engine refuses X-Capture with X-Replay-Frozen-Copy.
            capture=False,
            replay_frozen_copy=score.frozen_copy_id,
        )
    except ExecutionError as exc:
        if exc.code != "replay_unsupported":
            raise
        _warn_if_still_running(exc)
        return Reproduction(outcome="failed", reason="replay_unsupported")
    result = report.candidates[0]
    outcome, reason, missed = _classify(score, result)
    return Reproduction(outcome=outcome, reason=reason, missed_cases=missed, result=result)


async def _record_async(
    client: AsyncClient,
    score: LeaderboardScore,
    result: CandidateResult,
    reproduction: Reproduction,
) -> Reproduction:
    try:
        await client.leaderboards._record_reproduction(
            score.id,
            run_id=result.run_id,
            score=cast(float, result.score),
            total_questions=len(result.cases),
            frozen_copy_id=score.frozen_copy_id,
            client=_client_info(),
        )
    except Exception as exc:  # noqa: BLE001 - see the sync twin
        return replace(reproduction, record_error=str(exc))
    return replace(reproduction, recorded=True)


__all__ = ["Reproduction", "ReproductionOutcome"]
