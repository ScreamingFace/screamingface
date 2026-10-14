"""Discovery for flat, Engine-owned executable Benchmark resources."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Header, Path, Query, Request
from fastapi.responses import Response

from screamingface_engine.auth import ProblemException
from screamingface_engine.benchmarks import BenchmarkRegistry
from screamingface_engine.rest.conditional import conditional_json_response

router = APIRouter()


def _registry(request: Request) -> BenchmarkRegistry:
    return request.app.state.benchmarks


@router.get(
    "/v1/benchmarks",
    tags=["Catalog"],
    summary="List the installed Benchmarks",
)
async def list_benchmarks(
    request: Request,
    if_none_match: Annotated[str | None, Header(alias="If-None-Match")] = None,
) -> Response:
    return conditional_json_response(
        {"object": "list", "data": [benchmark.catalog_entry() for benchmark in _registry(request)]},
        if_none_match,
    )


@router.get(
    "/v1/benchmarks/{benchmark_id}",
    tags=["Catalog"],
    summary="Fetch one Engine-owned Benchmark expression",
)
async def get_benchmark(
    request: Request,
    benchmark_id: Annotated[str, Path(description="An explicit installed Benchmark id.")],
    limit: Annotated[int | None, Query(ge=1, description="Exact selected case count.")] = None,
    if_none_match: Annotated[str | None, Header(alias="If-None-Match")] = None,
) -> Response:
    benchmark = _registry(request).get(benchmark_id)
    if benchmark is None:
        raise ProblemException(
            status=404,
            title="Unknown benchmark",
            detail=f"no Benchmark is installed under {benchmark_id!r}",
        )
    if limit is not None and limit > benchmark.case_count:
        raise ProblemException(
            status=422,
            title="Invalid benchmark selection",
            detail=f"limit must be between 1 and {benchmark.case_count} for {benchmark.id!r}",
        )
    return conditional_json_response(benchmark.resource(limit), if_none_match)


__all__ = ["router"]
