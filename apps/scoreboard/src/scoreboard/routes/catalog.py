"""The homepage's compact public catalog; SDK discovery remains /benchmarks."""

from fastapi import APIRouter, Response
from pydantic import BaseModel

from scoreboard.scores.catalog import BenchmarkSummary, list_benchmark_summaries

router = APIRouter(prefix="/v1")


class CatalogResponse(BaseModel):
    benchmarks: list[BenchmarkSummary]


@router.get("/benchmarks/summary", response_model=CatalogResponse, tags=["benchmarks"])
async def catalog_summary(response: Response) -> CatalogResponse:
    # INVARIANT: score and visibility changes must be observed on the next request.
    response.headers["Cache-Control"] = "no-store"
    return CatalogResponse(benchmarks=await list_benchmark_summaries())
