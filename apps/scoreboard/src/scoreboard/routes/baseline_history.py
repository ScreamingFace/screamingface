"""Public history for already-public external observations, including on private boards."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, ConfigDict
from tortoise.transactions import in_transaction

from scoreboard.db import DEFAULT_CONNECTION
from scoreboard.scores.baseline_metadata import BaselineObservation
from scoreboard.scores.models import Baseline, BaselineRevision

router = APIRouter(prefix="/v1")


class ObservationVersion(BaselineObservation):
    model_config = ConfigDict(extra="forbid")

    revision: int
    recorded_at: datetime | None
    score: float
    source_url: str | None
    metadata: dict[str, Any] | None


class BaselineHistoryResponse(BaseModel):
    baseline_id: UUID
    benchmark_id: str
    model_name: str
    source: str
    current_revision: int
    versions: list[ObservationVersion]
    next_before: int | None


@router.get(
    "/leaderboard/{benchmark_id}/external-results/{baseline_id}/history",
    response_model=BaselineHistoryResponse,
    tags=["leaderboard"],
)
async def get_baseline_history(
    benchmark_id: str,
    baseline_id: UUID,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    before: Annotated[int | None, Query(ge=1, le=2147483647)] = None,
) -> BaselineHistoryResponse:
    # WHY: lock the current row while reading its immutable versions so the
    # current-version label and page boundary agree during a concurrent import.
    async with in_transaction(connection_name=DEFAULT_CONNECTION) as connection:
        baseline = (
            await Baseline.filter(id=baseline_id, benchmark_id=benchmark_id)
            .using_db(connection)
            .select_for_update()
            .first()
        )
        if baseline is None:
            raise HTTPException(status_code=404, detail="External result history not found")
        query = BaselineRevision.filter(baseline_id=baseline_id).using_db(connection)
        if before is not None:
            query = query.filter(revision__lt=before)
        versions = await query.order_by("-revision").limit(limit + 1)
        page = versions[:limit]
        return BaselineHistoryResponse(
            baseline_id=baseline.id,
            benchmark_id=benchmark_id,
            model_name=baseline.model_name,
            source=baseline.source,
            current_revision=baseline.observation_revision,
            versions=[_public_version(version) for version in page],
            next_before=page[-1].revision if len(versions) > limit else None,
        )


def _public_version(version: BaselineRevision) -> ObservationVersion:
    data = version.observation
    # INVARIANT: never serialize the ORM model or splat arbitrary stored keys.
    return ObservationVersion(
        revision=version.revision,
        recorded_at=version.recorded_at,
        score=data["score"],
        source_url=data.get("source_url"),
        metric_name=data.get("metric_name"),
        observed_at=data.get("observed_at"),
        metadata=data.get("metadata"),
    )
