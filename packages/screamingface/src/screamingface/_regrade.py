"""Re-grade a published score from its pinned cache under its Benchmark's current revision.

FEATURE: OME-1909 — when a Benchmark's revision moves (its grading changed, its Cases did not), its
old entries stop ranking. `Client.regrade(score_id)` rebuilds the entry's url4 against the current
catalogue, replays it from the entry's pinned cache with the entry's answer seed, and posts the
result to the board's re-grade route (`POST /v1/scores/{source}/regrades`), which stores a new
entry credited to the source's submitter.
STORY: as a ScreamingFace team member, I move an old entry onto the bumped revision at no
Candidate cost, and its submitter keeps the credit.

INVARIANT: a re-grade makes no Candidate model call. Every refusal before the run (live judge
Cases, the score, its capture, the revision) happens before a run is scheduled; the run always
carries the pinned cache, so the Engine answers every Candidate call from the copy or fails the
Case; and a run where any call missed the copy submits nothing.
INVARIANT: a re-grade is not a reproduction. It never calls `_reproduction._classify` and never
records a reproduction: its grades are meant to differ from the source's.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
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
    from screamingface._scoreboard.replay_reads import PublishedScore
    from screamingface.client import AsyncClient, Client
    from screamingface.events import Event
    from screamingface.leaderboard import LeaderboardScore
    from screamingface.report import CandidateResult, Report

# The Engine's word for "every judge call of the replay goes live" (`job_env.LIVE_JUDGE_ALL`).
_LIVE_JUDGE_ALL = "all"


@dataclass(frozen=True, slots=True)
class _Regrade:
    """What a re-grade runs, decided before any run: the source, the rebuilt url4, the live set."""

    source: PublishedScore
    url4: str
    pinned_cache: str
    live_judge: str | None


def _live_judge_text(value: object) -> str | None:
    """The live judge Cases in the Engine's canonical header text: `all`, or sorted unique ids.

    WHY refused here and not left to the Engine: each refusal is one the Engine would answer only
    after the score and catalogue reads, and two would be silent. `"ALL"` or `["all", "3"]` read as
    Case ids would re-judge almost nothing for a caller who meant every Case, and a bare string
    like `"3"` would be iterated into its characters.
    WHY canonical: the Engine echoes the set in this exact text, and the transport refuses any
    other echo (`_require_replay_ack`), so the two ends must spell one set one way.
    """

    if value is None:
        return None
    if value == _LIVE_JUDGE_ALL:
        return _LIVE_JUDGE_ALL
    if isinstance(value, str) or not isinstance(value, Sequence):
        raise TypeError("live_judge must be 'all' or a sequence of Case id strings")
    ids: set[str] = {_live_case_id(item) for item in value}
    if not ids:
        raise ValueError("live_judge must name at least one Case id, or be 'all'")
    return ",".join(sorted(ids))


def _live_case_id(item: object) -> str:
    """One live judge Case id, trimmed as the Engine trims it, or the reason it is refused."""

    if not isinstance(item, str):
        raise TypeError("each live_judge Case id must be a string, like '7'")
    case_id: str = item.strip()
    if not case_id or "," in case_id:
        raise ValueError("each live_judge Case id must be non-blank and contain no comma")
    if case_id.lower() == _LIVE_JUDGE_ALL:
        raise ValueError("pass live_judge='all' on its own, not inside a list")
    return case_id


def _replayable(source: PublishedScore) -> str:
    """The source's pinned cache, or the refusal of a capture a replay cannot name (Q14)."""

    refused = _not_reproducible(source)
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
    live_judge: str | None,
) -> _Regrade:
    """The re-grade's run, only if the current revision may re-grade the source's.

    INVARIANT (OME-1909): only the Benchmark part of the url4 is rebuilt. The Candidate part is the
    published text, unchanged, so every Candidate call is the request the copy holds; a Fusion's
    members and synthesiser included.
    WHY `regradable_from` and not a Case comparison here: the Engine lists an old revision only when
    that revision's Case Digest is the one its Cases compute now (checked at assembly), so a listed
    revision means "the same Cases". The score's own `case_digest` hashes grades and is never read.
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
        raise PlanningError(
            f"The published url4 of score {source.score_id} does not parse: {exc}",
            code="not_regradable",
            permanent=True,
        ) from exc
    return _Regrade(source, _linked(resource.url4, candidate), pinned_cache, live_judge)


def _complete(report: Report, source: PublishedScore) -> CandidateResult:
    """The replayed result, only if every call of every Case came from the pinned cache.

    INVARIANT (OME-1909): one miss refuses the whole re-grade, on a Candidate call or a judge call.
    In replay-only mode every call must come from the copy; with live judges the Candidate calls
    still must. A score over the Cases that did replay would rank a run that never happened.
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
    live_judge: object,
    on_event: Callable[[Event], None] | None,
    progress: bool | None,
) -> LeaderboardScore:
    """Re-grade one score; the stages are those of `Client.regrade`'s docstring."""

    # Stage 1 — the live judge Cases, refused before any request.
    live: str | None = _live_judge_text(live_judge)
    # Stage 2 — read the source score (public, then gated for a private one the caller submitted).
    source: PublishedScore = client.leaderboards._published_score(score_id)
    # Stage 3 — a capture a replay cannot name starts nothing, not even the catalogue read.
    pinned_cache: str = _replayable(source)
    # Stage 4 — the current Benchmark, built at the published Case count.
    resource: _BenchmarkResource = client._benchmark_resources.load(
        source.benchmark_id, source.total_questions
    )
    # Stage 5 — refuse a current or unlisted revision; rebuild the Benchmark part only.
    plan: _Regrade = _planned(source, pinned_cache, resource, live)
    # Stage 6 — replay from the copy with the published seed; never capture.
    report: Report = evaluate_url4_sync(
        client._transport,
        plan.url4,
        on_event,
        progress,
        answer_seed=source.answer_seed,
        # The Engine refuses X-Capture with X-Replay-Frozen-Copy (S6).
        capture=False,
        replay_frozen_copy=plan.pinned_cache,
        replay_live_judge=plan.live_judge,
    )
    # Stage 7 — one cache miss anywhere submits nothing.
    result: CandidateResult = _complete(report, source)
    # Stage 8 — post to the source's re-grade route; the board credits the source's submitter.
    return client.leaderboards._submit_regrade(source.score_id, result)


async def regrade_async(
    client: AsyncClient,
    score_id: UUID | str,
    *,
    live_judge: object,
    on_event: Callable[[Event], None | Awaitable[None]] | None,
    progress: bool | None,
) -> LeaderboardScore:
    """Async twin of `regrade_sync`: the same stages and checks, awaited."""

    # Stage 1 — the live judge Cases, refused before any request.
    live: str | None = _live_judge_text(live_judge)
    # Stage 2 — read the source score.
    source: PublishedScore = await client.leaderboards._published_score(score_id)
    # Stage 3 — a capture a replay cannot name starts nothing.
    pinned_cache: str = _replayable(source)
    # Stage 4 — the current Benchmark, built at the published Case count.
    resource: _BenchmarkResource = await client._benchmark_resources.load(
        source.benchmark_id, source.total_questions
    )
    # Stage 5 — refuse a current or unlisted revision; rebuild the Benchmark part only.
    plan: _Regrade = _planned(source, pinned_cache, resource, live)
    # Stage 6 — replay from the copy with the published seed; never capture.
    report: Report = await evaluate_url4_async(
        client._transport,
        plan.url4,
        on_event,
        progress,
        answer_seed=source.answer_seed,
        capture=False,
        replay_frozen_copy=plan.pinned_cache,
        replay_live_judge=plan.live_judge,
    )
    # Stage 7 — one cache miss anywhere submits nothing.
    result: CandidateResult = _complete(report, source)
    # Stage 8 — post to the source's re-grade route.
    return await client.leaderboards._submit_regrade(source.score_id, result)


__all__ = ["regrade_async", "regrade_sync"]
