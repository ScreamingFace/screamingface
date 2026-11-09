"""Discovery for flat, Engine-owned executable Benchmark resources."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Header, Path, Query, Request
from fastapi.responses import JSONResponse, Response

from screamingface_engine.auth import ProblemException
from screamingface_engine.benchmarks import BenchmarkRegistry
from screamingface_engine.benchmarks.selection import MAX_SELECTED_CASE_IDS, CaseSelection
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
    # INVARIANT (OME-1714): this listing is the one root every catalogue reader uses (the SDK's
    # `sf.benchmarks.list()`, the Scoreboard seed), so an Unlisted Benchmark skipped here is off
    # every public index. `get_benchmark` below still serves it by id — unlisted, not removed.
    return conditional_json_response(
        {
            "object": "list",
            "data": [
                benchmark.catalog_entry()
                for benchmark in _registry(request)
                if not benchmark.unlisted
            ],
        },
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


_SELECTION_BODY: dict[str, object] = {
    "required": True,
    "content": {
        "application/json": {
            "schema": {
                "type": "object",
                "additionalProperties": False,
                "required": ["cases"],
                "properties": {
                    "cases": {
                        "type": "array",
                        "items": {"type": "integer", "minimum": 1},
                        "minItems": 1,
                        "maxItems": MAX_SELECTED_CASE_IDS,
                        "uniqueItems": True,
                        "description": "Case ids: positions in the pinned order, 1..case_count.",
                    }
                },
            },
            "example": {"cases": [3, 17, 42]},
        }
    },
}


@router.post(
    "/v1/benchmarks/{benchmark_id}/selection",
    tags=["Catalog"],
    summary="Fetch one Benchmark expression for a fixed list of Case ids",
    openapi_extra={"requestBody": _SELECTION_BODY},
)
async def select_benchmark_cases(
    request: Request,
    benchmark_id: Annotated[str, Path(description="An explicit installed Benchmark id.")],
) -> Response:
    """The resource whose recipe serves and grades only the posted Case ids (OME-1739).

    FEATURE (OME-1739): a researcher's development and held-out sets, e.g. ``[3, 17, 42]``.
    WHY a body, not a query string: a 40-id list stays readable and out of access logs.
    The resource echoes ``selected_case_ids`` so the SDK can refuse an Engine that ignored it.

    INVARIANT: the recipe is written from the checked integers (``CaseSelection``), never from
    the client's text, so nothing the client sends can reach the recipe as written.
    """

    benchmark = _registry(request).get(benchmark_id)
    if benchmark is None:
        raise ProblemException(
            status=404,
            title="Unknown benchmark",
            detail=f"no Benchmark is installed under {benchmark_id!r}",
        )
    try:
        body: object = await request.json()
        if not isinstance(body, dict) or set(body) != {"cases"}:
            raise ValueError('the body must be {"cases": [<Case id>, ...]}')
        cases: object = body["cases"]
        if not isinstance(cases, list):
            raise ValueError('"cases" must be a list of Case ids')
        selection: CaseSelection = CaseSelection.of(cases).require_within(benchmark.case_count)
    except ValueError as exc:  # json.JSONDecodeError is a ValueError
        raise ProblemException(
            status=422,
            title="Invalid benchmark selection",
            detail=f"{benchmark.id!r}: {exc}",
        ) from None
    # WHY no ETag or public cache header: a POST answer is per request, never a shared copy.
    return JSONResponse(benchmark.resource(cases=selection))


__all__ = ["router"]
