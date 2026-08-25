from __future__ import annotations

from datetime import datetime
from typing import Annotated, cast
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict

from scoreboard.routes.dependencies import ReadIdentity
from scoreboard.scores.baseline_store import BaselineStore
from scoreboard.scores.frontier import compute_frontier
from scoreboard.scores.models import Benchmark
from scoreboard.scores.schemas import (
    BaselineSchema,
    BenchmarkSchema,
    FrontierResponse,
    LeaderboardEntry,
    RunCostUsd,
    ScoreSchema,
    SubmittedBy,
)
from scoreboard.scores.store import ScoreStore, benchmark_to_schema

MAX_LEADERBOARD_TOP = 200
MAX_HISTORY_LIMIT = 100

# INVARIANT (OME-894): ONE detail for every history miss on a private board. Another
# participant's spec and a spec that never existed must be indistinguishable — a differing status
# or body would let a caller enumerate specs, which are guessable model names.
HISTORY_NOT_FOUND_DETAIL = "History not found"

router = APIRouter(prefix="/v1")


class BenchmarksResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    benchmarks: list[BenchmarkSchema]


class RankedLeaderboardEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rank: int
    spec_id: str
    # WHY: the board ranks best-per-spec PER REVISION (OME-775), so one spec can legitimately
    # appear twice. Without this field a client cannot tell why the two are not competing.
    benchmark_revision: str | None
    score: float
    total_questions: int
    ran_with_providers: list[str]
    submitted_at: datetime
    submitted_by: SubmittedBy
    verified_by_screamingface: bool
    url4_expression: str
    # AIDEV-NOTE: this class mirrors LeaderboardEntry field-for-field plus `rank`,
    # and `_ranked_entry` splats one into the other. Because both set
    # extra="forbid", a field added to LeaderboardEntry and not here raises at
    # runtime rather than at import — a 500 on the read path, not a type error.
    # Keep the two in step.
    #
    # RunCostUsd, not a bare Decimal | None: the shared type carries the
    # fixed-6dp JSON serializer, so the wire form cannot drift between the DTOs
    # (spec 2.4).
    run_cost_usd: RunCostUsd


class LeaderboardResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    benchmark: BenchmarkSchema
    entries: list[RankedLeaderboardEntry]
    # FEATURE: OME-894 — the caller's own submissions on a private board.
    # WHY a separate key rather than a nulled `rank` inside `entries`: on a private board there IS
    # no ranking, so `entries` being empty is the truthful answer, and a participant's own rows are
    # a different concept that never had a rank to suppress. Keeping them here leaves the
    # `entries` contract untouched — no nullable rank, no SDK or portal change, and an older
    # client sees an empty leaderboard rather than raising.
    # Typed as LeaderboardEntry, which is RankedLeaderboardEntry minus `rank` — the shape already
    # existed, so no fourth mirrored DTO is introduced.
    my_submissions: list[LeaderboardEntry]
    # WHY this is not redundant with `benchmark.visibility` (OME-894): visibility says what the
    # BOARD is; this says whether THIS listing was filtered to the caller. Without it an empty
    # list is indistinguishable from "nobody has submitted", which is the difference between
    # hidden-by-design and silently broken.
    scoped_to_caller: bool
    # FEATURE: OME-322 — imported single-model "line to beat" baselines (LMArena /
    # Artificial Analysis), surfaced alongside community entries. Empty until a
    # baseline is imported via `python -m scoreboard.import_baselines`.
    baselines: list[BaselineSchema]


class HistorySubmission(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    # WHY: a spec's history can span benchmark revisions, and two entries measured against
    # different revisions are not comparable to each other (OME-775).
    benchmark_revision: str | None
    score: float
    total_questions: int
    correct_questions: int | None
    submitted_at: datetime
    submitted_by: SubmittedBy
    verified_by_screamingface: bool
    run_cost_usd: RunCostUsd


class HistoryResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    spec_id: str
    benchmark_id: str
    submissions: list[HistorySubmission]


def _score_store(request: Request) -> ScoreStore:
    return cast(ScoreStore, request.app.state.score_store)


def _baseline_store(request: Request) -> BaselineStore:
    return cast(BaselineStore, request.app.state.baseline_store)


async def _get_benchmark_or_404(benchmark_id: str) -> BenchmarkSchema:
    benchmark = await Benchmark.get_or_none(id=benchmark_id)
    if benchmark is None:
        raise HTTPException(status_code=404, detail="Benchmark not found")

    # INVARIANT: use the store's single mapper, never a second hand-written projection here.
    # This function used to carry its own copy; adding `focus` (OME-874) broke that copy while
    # the store's stayed correct, which is the OME-852 shape exactly.
    return benchmark_to_schema(benchmark)


def _ranked_entry(rank: int, entry: LeaderboardEntry) -> RankedLeaderboardEntry:
    return RankedLeaderboardEntry(rank=rank, **entry.model_dump())


def _history_submission(score: ScoreSchema) -> HistorySubmission:
    return HistorySubmission(
        id=score.id,
        benchmark_revision=score.benchmark_revision,
        score=score.score,
        total_questions=score.total_questions,
        correct_questions=score.correct_questions,
        submitted_at=score.submitted_at,
        submitted_by=score.submitted_by,
        verified_by_screamingface=score.verified_by_screamingface,
        run_cost_usd=score.run_cost_usd,
    )


@router.get("/benchmarks", response_model=BenchmarksResponse, tags=["benchmarks"])
async def list_benchmarks(request: Request) -> BenchmarksResponse:
    """List registered public benchmarks. This endpoint is public and has no auth."""
    benchmarks = await _score_store(request).list_benchmarks()
    return BenchmarksResponse(benchmarks=benchmarks)


@router.get("/leaderboard/{benchmark_id}", response_model=LeaderboardResponse, tags=["leaderboard"])
async def get_leaderboard(
    benchmark_id: str,
    request: Request,
    identity: ReadIdentity,
    top: Annotated[
        int,
        Query(
            ge=1,
            description="Maximum entries to return. Values above 200 are clamped.",
        ),
    ] = 50,
) -> LeaderboardResponse:
    """Return the best-per-spec leaderboard for a registered benchmark.

    The response shape is stable for portal clients. Unknown benchmarks return 404,
    and requests above the public maximum are silently clamped to 200 entries.
    """
    benchmark = await _get_benchmark_or_404(benchmark_id)
    is_private = benchmark.visibility == "private"
    # Baselines stay visible on a private board: imported LMArena / Artificial Analysis
    # single-model numbers are public third-party data, not participant submissions, and a
    # participant needs the line to beat.
    baselines = await _baseline_store(request).list_baselines(benchmark_id)

    if is_private:
        # INVARIANT: `entries` is the public RANKING, and a private board has none — so it is empty
        # for everyone, including a participant. Their own rows are a different concept and go to
        # `my_submissions`, which is why nothing here has a rank to suppress.
        #
        # Sourced from list_owned_entries and NOT from leaderboard(): the ranking query collapses
        # to best-per-spec and is bounded by `top`, so it would silently drop a participant's
        # earlier submission to the same spec — the invisible-submission failure this ticket
        # exists to avoid, one level down (found in review).
        #
        # Both cases return from inside this branch: no code below may run for a private
        # benchmark, and an absent identity must yield nothing rather than falling through.
        mine = (
            []
            if identity is None
            else await _score_store(request).list_owned_entries(
                benchmark_id=benchmark_id, owner=identity
            )
        )
        return LeaderboardResponse(
            benchmark=benchmark,
            entries=[],
            my_submissions=mine,
            baselines=baselines,
            scoped_to_caller=True,
        )

    rows = await _score_store(request).leaderboard(
        benchmark_id=benchmark_id,
        top_n=min(top, MAX_LEADERBOARD_TOP),
    )

    return LeaderboardResponse(
        benchmark=benchmark,
        entries=[_ranked_entry(index, row) for index, row in enumerate(rows, start=1)],
        my_submissions=[],
        baselines=baselines,
        scoped_to_caller=False,
    )


@router.get(
    "/leaderboard/{benchmark_id}/{spec_id}/history",
    response_model=HistoryResponse,
    tags=["leaderboard"],
)
async def get_spec_history(
    benchmark_id: str,
    spec_id: str,
    request: Request,
    identity: ReadIdentity,
    limit: Annotated[
        int,
        Query(
            ge=1,
            description="Maximum submissions to return. Values above 100 are clamped.",
        ),
    ] = 20,
) -> HistoryResponse:
    """Return newest-first submissions for a spec under a registered benchmark.

    The response shape is stable for portal clients. Unknown benchmarks return 404,
    while unknown specs under known benchmarks return an empty submissions list.
    Requests above the public maximum are silently clamped to 100 submissions.
    """
    benchmark = await _get_benchmark_or_404(benchmark_id)
    is_private = benchmark.visibility == "private"
    if is_private and identity is None:
        raise HTTPException(status_code=404, detail=HISTORY_NOT_FOUND_DETAIL)

    submissions = await _score_store(request).list_for_spec(
        benchmark_id=benchmark_id,
        spec_id=spec_id,
        limit=min(limit, MAX_HISTORY_LIMIT),
        owner=identity if is_private else None,
    )
    if is_private and not submissions:
        # INVARIANT: 404, not 403, and the SAME 404 a nonexistent spec gets. A 403 would confirm
        # the spec exists; a 200-with-empty-list (what a PUBLIC board returns for an unknown spec)
        # would make "someone else's" distinguishable from "no such spec". Either one lets a
        # caller enumerate other participants' spec ids, which are guessable model names.
        raise HTTPException(status_code=404, detail=HISTORY_NOT_FOUND_DETAIL)

    return HistoryResponse(
        spec_id=spec_id,
        benchmark_id=benchmark_id,
        submissions=[_history_submission(score) for score in submissions],
    )


@router.get(
    "/leaderboard/{benchmark_id}/frontier",
    response_model=FrontierResponse,
    tags=["leaderboard"],
)
async def get_frontier(benchmark_id: str, request: Request) -> FrontierResponse:
    """How much of `benchmark_id`'s score frontier is held by open-reproducible
    stacks vs. proprietary ones (OME-323) — the current split plus the trend over
    time. Unknown benchmarks return 404. Deliberately benchmark-wide across every
    spec, not scoped per-spec like the ranked leaderboard above (spec §6).
    """
    benchmark = await _get_benchmark_or_404(benchmark_id)
    if benchmark.visibility == "private":
        # An aggregate over every participant by definition. It publishes the running-best score
        # and when it changed, which is most of what a private challenge hides — so it is
        # unavailable to participants too, not merely scoped. Nothing here to scope: a
        # single-participant "frontier" would just restate their own best score under a name that
        # implies a field.
        raise HTTPException(
            status_code=404, detail="Frontier is not available for a private benchmark"
        )
    scores = await _score_store(request).list_all_for_benchmark(benchmark_id)
    baselines = await _baseline_store(request).list_baselines(benchmark_id)
    result = compute_frontier(scores=scores, baselines=baselines)
    return FrontierResponse(benchmark_id=benchmark_id, **result.model_dump())
