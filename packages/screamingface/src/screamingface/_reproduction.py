"""Reproduce a submitted score from its cache version and record that it reproduced (OME-1307).

FEATURE: E14 B5 (spec `prd/reproduce.md`, contracts K3 and K7). The score's own url4 and answer
seed run again with the cache revision stored with the score. The Engine answers every call from
the cache or fails the case, so a replay costs no provider spend. The result is judged against the
stored numbers by one pure function, and an exact one is recorded on the board.

INVARIANT: this module never starts a normal, paid run. A score that cannot name a cache version
starts no run at all, and a run the Engine did not acknowledge as a replay is stopped (the
transport) or refused (`evaluate_url4_*`) before it is judged.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Literal
from uuid import UUID

from screamingface._evaluation.url4 import evaluate_url4_async, evaluate_url4_sync
from screamingface._report_primitives import CaseId
from screamingface._scoreboard.leaderboards import _client_info
from screamingface.errors import ExecutionError

if TYPE_CHECKING:
    from screamingface.client import AsyncClient, Client
    from screamingface.leaderboard import LeaderboardScore
    from screamingface.report import CandidateResult

type ReproductionOutcome = Literal["exact", "failed", "not_reproducible"]


@dataclass(frozen=True, slots=True)
class Reproduction:
    """What `reproduce` found when it ran a score again from its cache version.

    `outcome` is `exact` (the replay gave the stored score and case count on the same benchmark
    revision), `failed` (it ran or tried to, with `reason` saying why) or `not_reproducible` (the
    score has no complete cache version, so no run started). `missed_cases` lists the cases the
    cache could not answer. `recorded` says whether the board stored an exact reproduction, and
    `record_error` says why not when an exact replay could not be recorded.
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

    INVARIANT: the order of `checks` is the contract. A replay code outranks everything, since a
    run that missed the cache has nothing to compare. Then a run failure, then the benchmark
    revision (a changed exam makes the score meaningless to compare), then the numbers, compared
    exactly (one ulp is a different result).
    """
    missed = tuple(
        dict.fromkeys(
            case.case_id
            for case in result.cases
            if any(failure.code == "replay_cache_miss" for failure in case.failures)
        )
    )
    failures = (*result.failures, *(f for case in result.cases for f in case.failures))
    checks = (
        ("cache_miss", bool(missed)),
        ("unknown_cache_revision", any(f.code == "unknown_cache_revision" for f in failures)),
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
        missed if reason == "cache_miss" else (),
    )


def _not_reproducible(score: LeaderboardScore) -> Reproduction | None:
    """The refusal for a score with no complete cache version, before any run (R7).

    A `complete` score with no revision is unknown too: a run without `X-Cache-Replay` would be a
    normal run, and a replay never pays.
    """
    if score.reproducible == "partial":
        return Reproduction(outcome="not_reproducible", reason="partial")
    if score.reproducible is None or score.cache_revision is None:
        return Reproduction(outcome="not_reproducible", reason="unknown")
    return None


def _unsupported(exc: ExecutionError) -> Reproduction:
    if exc.code != "replay_unsupported":
        raise exc
    return Reproduction(outcome="failed", reason="replay_unsupported")


def _judged(score: LeaderboardScore, result: CandidateResult) -> Reproduction:
    outcome, reason, missed = _classify(score, result)
    return Reproduction(outcome=outcome, reason=reason, missed_cases=missed, result=result)


def _recorded(reproduction: Reproduction, error: Exception | None) -> Reproduction:
    if error is None:
        return replace(reproduction, recorded=True)
    return replace(reproduction, record_error=str(error))


def reproduce_sync(
    client: Client, score: LeaderboardScore | UUID | str, record: bool
) -> Reproduction:
    selected = score if not isinstance(score, UUID | str) else client.leaderboards.get_score(score)
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
            cache_replay=score.cache_revision,
        )
    except ExecutionError as exc:
        return _unsupported(exc)
    return _judged(score, report.candidates[0])


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
            # Exact means the replay's numbers equal the stored ones, so these ARE the replay's.
            score=score.score,
            total_questions=score.total_questions,
            cache_revision=score.cache_revision,
            client=_client_info(),
        )
    except Exception as exc:  # noqa: BLE001 - a failed record never undoes an exact replay (R16)
        return _recorded(reproduction, exc)
    return _recorded(reproduction, None)


async def reproduce_async(
    client: AsyncClient, score: LeaderboardScore | UUID | str, record: bool
) -> Reproduction:
    selected = (
        score if not isinstance(score, UUID | str) else await client.leaderboards.get_score(score)
    )
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
            cache_replay=score.cache_revision,
        )
    except ExecutionError as exc:
        return _unsupported(exc)
    return _judged(score, report.candidates[0])


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
            score=score.score,
            total_questions=score.total_questions,
            cache_revision=score.cache_revision,
            client=_client_info(),
        )
    except Exception as exc:  # noqa: BLE001 - see the sync twin
        return _recorded(reproduction, exc)
    return _recorded(reproduction, None)


__all__ = ["Reproduction"]
