"""Every revision a leaderboard has had, for the revision selector (OME-1708)."""

from __future__ import annotations

from typing import cast

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict

from scoreboard.routes.dependencies import PRIVATE_CACHE_HEADERS, turned_private
from scoreboard.scores.models import Benchmark
from scoreboard.scores.revisions import RevisionSummary, list_revisions
from scoreboard.scores.store import ScoreStore

router = APIRouter(prefix="/v1")

REVISIONS_NOT_AVAILABLE_DETAIL = "Revisions are not available for a private benchmark"


class RevisionsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    benchmark_id: str
    revisions: list[RevisionSummary]


async def _known_or_404(benchmark_id: str) -> None:
    if not await Benchmark.exists(id=benchmark_id):
        raise HTTPException(status_code=404, detail="Benchmark not found")


@router.get(
    "/leaderboard/{benchmark_id}/revisions",
    response_model=RevisionsResponse,
    tags=["leaderboard"],
)
async def get_revisions(
    benchmark_id: str, request: Request, response: Response
) -> RevisionsResponse:
    """Every revision of `benchmark_id`'s leaderboard, newest first.

    Each carries when the board first saw it, its Case count (both marked when inferred from
    results), and how many results its board shows. Unknown benchmarks return 404; private
    boards return 404 (OME-894), because per-revision result counts describe every participant.
    """
    await _known_or_404(benchmark_id)
    store = cast(ScoreStore, request.app.state.score_store)
    # One snapshot: the registered revision, the revision rows and each board count must agree.
    async with store.read_snapshot() as snapshot:
        registered, count = await store.benchmark_scope(benchmark_id, connection=snapshot)
        revisions = await list_revisions(
            store,
            benchmark_id,
            registered_revision=registered,
            registered_case_count=count,
            connection=snapshot,
        )
    # INVARIANT (OME-894): visibility is read FRESH after the counts were computed and before
    # anything leaves, so a board private at the start, or flipped during the read, answers 404.
    if await turned_private(benchmark_id):
        raise HTTPException(
            status_code=404,
            detail=REVISIONS_NOT_AVAILABLE_DETAIL,
            headers=PRIVATE_CACHE_HEADERS,
        )
    # INVARIANT: a new submission or a bump must show on the next request.
    response.headers["Cache-Control"] = "no-store"
    return RevisionsResponse(benchmark_id=benchmark_id, revisions=revisions)
