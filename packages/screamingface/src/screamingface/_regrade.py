"""Re-grade a published score from its pinned cache under its Benchmark's current revision.

FEATURE: OME-1909 — when a Benchmark's revision moves (its grading changed, its Cases did not), its
old entries stop ranking. `Client.regrade(score_id)` rebuilds the entry's url4 against the current
catalogue, replays it from the entry's pinned cache with the entry's answer seed, and posts the
result to the board's re-grade route (`POST /v1/scores/{source}/regrades`), which stores a new
entry credited to the source's submitter.
STORY: as a ScreamingFace team member, I move an old entry onto the bumped revision at no
Candidate cost, and its submitter keeps the credit.

INVARIANT: a re-grade makes no model call. Every refusal before the run (the score, its
capture, the revision) happens before a run is scheduled; the run always carries the pinned
cache, so the Engine answers every call, Candidate and judge, from the copy or fails the Case;
and a run where any call missed the copy submits nothing.
LIMIT (OME-1909): a judge whose request changed (a raised `max_tokens`, a new prompt) misses the
copy, because its key hashes the whole request, so such a Benchmark cannot be re-graded yet;
sending chosen judge calls live is OME-1979.
INVARIANT: a re-grade is not a reproduction. It never calls `_reproduction._classify` and never
records a reproduction: its grades are meant to differ from the source's.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING
from uuid import UUID

from url4 import Url4Error, build

from screamingface._evaluation.url4 import (
    _REPLAY_FAILURE_CODES,
    _candidate_text,
    evaluate_url4_async,
    evaluate_url4_sync,
)
from screamingface._replay import _not_reproducible
from screamingface._replay_partial import _linked
from screamingface.errors import ExecutionError, PlanningError, ReproductionError

if TYPE_CHECKING:
    from screamingface._evaluation.benchmark import _BenchmarkResource
    from screamingface._report_primitives import CaseId
    from screamingface._reproduction import Reproduction
    from screamingface._scoreboard.replay_reads import PublishedScore
    from screamingface.client import AsyncClient, Client
    from screamingface.events import Event
    from screamingface.leaderboard import LeaderboardScore
    from screamingface.report import CandidateResult, Report


@dataclass(frozen=True, slots=True)
class _Regrade:
    """What a re-grade runs, decided before any run: the rebuilt url4 and the copy."""

    url4: str
    pinned_cache: str


def _not_a_regrade(source: PublishedScore) -> None:
    """Refuse a re-grade of a re-grade, naming the root score to re-grade instead.

    FEATURE (OME-1909): a re-graded entry has no pinned cache of its own (the copy stays with the
    score it was re-graded from), so only that root can be replayed again. The board allows one
    re-grade per source and revision, so the root moves onto each later revision in its turn.
    Example: `3c9a…` re-grades `af95…`; `regrade("3c9a…")` is refused naming `af95…`.
    """

    if source.regraded_from is not None:
        raise PlanningError(
            f"Score {source.score_id} is itself a re-grade of score {source.regraded_from} and has "
            f"no pinned cache of its own; re-grade {source.regraded_from} instead",
            code="regrade_the_source",
            permanent=True,
            details={"root_score_id": str(source.regraded_from)},
        )


def _replayable(source: PublishedScore) -> str:
    """The source's pinned cache, or the refusal of a capture a replay cannot name (Q14)."""

    refused: Reproduction | None = _not_reproducible(source)
    if refused is not None:
        raise ReproductionError(
            f"Score {source.score_id} cannot be re-graded: its capture is {refused.reason}",
            reproduction=refused,
            code="not_reproducible",
        )
    assert source.pinned_cache is not None  # checked by `_not_reproducible`
    return source.pinned_cache


def _planned(
    source: PublishedScore,
    pinned_cache: str,
    resource: _BenchmarkResource,
) -> _Regrade:
    """The re-grade's run, only if the current revision may re-grade the source's.

    INVARIANT (OME-1909): only the Benchmark part of the url4 is rebuilt. The Candidate part is the
    published text, unchanged, so every Candidate call is the request the copy holds; a Fusion's
    members and synthesiser included.
    WHY `regradable_from` and not a Case comparison here: each listed old revision is declared with
    a Case Digest, and the Engine checks that digest against the row's current Cases when it
    builds the catalogue, a tripwire for a later Case change. It does not prove an old entry ran
    on those Cases: an entry whose Cases differed is refused at replay, because its pinned cache
    misses (`regrade_incomplete`). The score's own `case_digest` hashes grades and is never read.
    """

    current: str = resource.info.revision
    if source.benchmark_revision == current:
        raise PlanningError(
            f"Score {source.score_id} is already on {source.benchmark_id}'s current revision "
            f"{current}; there is nothing to re-grade",
            code="already_current",
            permanent=True,
        )
    if source.benchmark_revision not in resource.regradable_from:
        raise PlanningError(
            f"{source.benchmark_id} at revision {current} does not list revision "
            f"{source.benchmark_revision} as one it may be re-graded from, so score "
            f"{source.score_id} needs a fresh run",
            code="not_regradable",
            permanent=True,
        )
    try:
        candidate: str = _candidate_text(build(source.url4))
    except (Url4Error, ValueError) as exc:
        # WHY its own code: the board sent a url4 with no ScreamingFace Candidate part, a contract
        # problem with the score, not a revision the Benchmark does not list.
        raise PlanningError(
            f"The published url4 of score {source.score_id} has no Candidate part a re-grade can "
            f"keep: {exc}",
            code="invalid_published_url4",
            permanent=True,
        ) from exc
    return _Regrade(_linked(resource.url4, candidate), pinned_cache)


def _complete(report: Report, source: PublishedScore) -> CandidateResult:
    """The replayed result, only if every call came from the copy.

    INVARIANT (OME-1909): one miss refuses the whole re-grade, on a Candidate call or a judge call.
    A score over the Cases that did replay would rank a run that never happened.
    """

    (result,) = report.candidates
    missed: list[CaseId] = [
        case.case_id
        for case in result.cases
        if any(failure.code in _REPLAY_FAILURE_CODES for failure in case.failures)
    ]
    run_missed: bool = any(failure.code in _REPLAY_FAILURE_CODES for failure in result.failures)
    if missed or run_missed:
        raise ExecutionError(
            f"The re-grade of score {source.score_id} did not replay from its pinned cache "
            f"({len(missed)} of {len(result.cases)} Cases missed it), so nothing was submitted",
            code="regrade_incomplete",
            permanent=True,
            details={"missed_cases": missed},
        )
    return result


def regrade_sync(
    client: Client,
    score_id: UUID | str,
    *,
    on_event: Callable[[Event], None] | None,
    progress: bool | None,
) -> LeaderboardScore:
    """Re-grade one score; the stages are those of `Client.regrade`'s docstring."""

    # Stage 1 — the source's PUBLIC read only: the board refuses to re-grade a private score, so
    # a private one is refused here, before a run.
    source: PublishedScore = client.leaderboards._public_score(score_id)
    # Stage 2 — a re-grade of a re-grade names its root; a capture a replay cannot name starts
    # nothing, not even the catalogue read.
    _not_a_regrade(source)
    pinned_cache: str = _replayable(source)
    # Stage 3 — the current Benchmark, built at the published Case count.
    resource: _BenchmarkResource = client._benchmark_resources.load(
        source.benchmark_id, source.total_questions
    )
    # Stage 4 — refuse a current or unlisted revision; rebuild the Benchmark part only.
    plan: _Regrade = _planned(source, pinned_cache, resource)
    # Stage 5 — replay from the copy with the published seed; never capture.
    report: Report = evaluate_url4_sync(
        client._transport,
        plan.url4,
        on_event,
        progress,
        answer_seed=source.answer_seed,
        # The Engine refuses X-Capture with X-Replay-Frozen-Copy (S6).
        capture=False,
        replay_frozen_copy=plan.pinned_cache,
    )
    # Stage 6 — one cache miss anywhere submits nothing.
    result: CandidateResult = _complete(report, source)
    # Stage 7 — post to the source's re-grade route; the board credits the source's submitter.
    return client.leaderboards._submit_regrade(source.score_id, result)


async def regrade_async(
    client: AsyncClient,
    score_id: UUID | str,
    *,
    on_event: Callable[[Event], None | Awaitable[None]] | None,
    progress: bool | None,
) -> LeaderboardScore:
    """Async twin of `regrade_sync`: the same stages and checks, awaited."""

    # Stage 1 — the source's public read only.
    source: PublishedScore = await client.leaderboards._public_score(score_id)
    # Stage 2 — a re-grade of a re-grade names its root; a capture a replay cannot name starts
    # nothing.
    _not_a_regrade(source)
    pinned_cache: str = _replayable(source)
    # Stage 3 — the current Benchmark, built at the published Case count.
    resource: _BenchmarkResource = await client._benchmark_resources.load(
        source.benchmark_id, source.total_questions
    )
    # Stage 4 — refuse a current or unlisted revision; rebuild the Benchmark part only.
    plan: _Regrade = _planned(source, pinned_cache, resource)
    # Stage 5 — replay from the copy with the published seed; never capture.
    report: Report = await evaluate_url4_async(
        client._transport,
        plan.url4,
        on_event,
        progress,
        answer_seed=source.answer_seed,
        capture=False,
        replay_frozen_copy=plan.pinned_cache,
    )
    # Stage 6 — one cache miss anywhere submits nothing.
    result: CandidateResult = _complete(report, source)
    # Stage 7 — post to the source's re-grade route.
    return await client.leaderboards._submit_regrade(source.score_id, result)


__all__ = ["regrade_async", "regrade_sync"]
