"""Judge a pinned-cache replay and record an exact one on the board (OME-1307, OME-1613).

FEATURE: E14 B5 (spec `02-frozen-copy-design.md` §7) and OME-1613 (spec §5). A replay of a
published score is judged against the published numbers by one pure function, `_classify`, and an
exact replay is recorded on the board. `_replay.py` runs the replay; this module only judges and
records it.

The `Reproduction` value is what `CandidateResult.reproduction` carries, and what
`sf.ReproductionError` carries when a replay cannot start.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Literal, cast

from screamingface._case_digest import case_digest
from screamingface._report_primitives import CaseId
from screamingface._scoreboard.leaderboards import _client_info

if TYPE_CHECKING:
    from screamingface._scoreboard.replay_reads import PublishedScore
    from screamingface.client import AsyncClient, Client
    from screamingface.report import CandidateResult

type ReproductionOutcome = Literal["exact", "failed", "not_reproducible"]


@dataclass(frozen=True, slots=True)
class Reproduction:
    """The verdict of a replay from a pinned cache, against the published score.

    `outcome` is `exact` (the replay gave the published score and case count on the same benchmark
    revision), `failed` (it ran or tried to, with `reason` saying why) or `not_reproducible` (the
    published capture is partial or unknown, so no run started). `missed_cases` lists the cases
    the pinned cache could not answer. `recorded` says whether the board stored an exact
    reproduction, and `record_error` says why not when an exact replay could not be recorded.
    """

    outcome: ReproductionOutcome
    reason: str | None = None
    missed_cases: tuple[CaseId, ...] = ()
    recorded: bool = False
    record_error: str | None = None


def _classify(
    published: PublishedScore, result: CandidateResult
) -> tuple[ReproductionOutcome, str | None, tuple[CaseId, ...]]:
    """Judge one replay against the published score; a pure function of the two.

    INVARIANT: the order of `checks` is the contract (spec §7). A replay code outranks everything,
    since a run that missed the copy has nothing to compare. Then a run failure, then the benchmark
    revision (a changed exam makes the score meaningless to compare), then the numbers, compared
    exactly (one ulp is a different result). Then the case digest, only when the score has one
    (Q29).
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
        ("benchmark_revision_changed", result.benchmark.revision != published.benchmark_revision),
        (
            "score_differs",
            result.score != published.score or len(result.cases) != published.total_questions,
        ),
        # Q29: the same score over other cases is not exact. Only a score with a digest is checked.
        (
            "cases_differ",
            published.case_digest is not None
            and case_digest(result.cases) != published.case_digest,
        ),
    )
    reason = next((name for name, failed in checks if failed), None)
    return (
        ("exact" if reason is None else "failed"),
        reason,
        missed if reason == "frozen_copy_miss" else (),
    )


def _record_sync(
    client: Client,
    published: PublishedScore,
    result: CandidateResult,
    reproduction: Reproduction,
) -> Reproduction:
    # WHY the login happens here and nowhere earlier (Q1): recording posts to the gated
    # `/v1/scores/{id}/reproductions`, so an exact verdict is the only point a replay of a public
    # score asks for a leaderboard login.
    try:
        client.leaderboards._record_reproduction(
            published.score_id,
            run_id=result.run_id,
            # The replay's own numbers. The board compares them with the stored score exactly.
            score=cast(float, result.score),
            total_questions=len(result.cases),
            frozen_copy_id=published.pinned_cache,
            # The replay's own cases, for the board to compare with the stored digest (Q29).
            case_digest=case_digest(result.cases),
            client=_client_info(),
        )
    except Exception as exc:  # noqa: BLE001 - a failed record never undoes an exact replay
        return replace(reproduction, record_error=str(exc))
    return replace(reproduction, recorded=True)


async def _record_async(
    client: AsyncClient,
    published: PublishedScore,
    result: CandidateResult,
    reproduction: Reproduction,
) -> Reproduction:
    try:
        await client.leaderboards._record_reproduction(
            published.score_id,
            run_id=result.run_id,
            score=cast(float, result.score),
            total_questions=len(result.cases),
            frozen_copy_id=published.pinned_cache,
            # The replay's own cases, for the board to compare with the stored digest (Q29).
            case_digest=case_digest(result.cases),
            client=_client_info(),
        )
    except Exception as exc:  # noqa: BLE001 - see the sync twin
        return replace(reproduction, record_error=str(exc))
    return replace(reproduction, recorded=True)


__all__ = ["Reproduction", "ReproductionOutcome"]
