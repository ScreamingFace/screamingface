"""``GET /v1/cache/entries``: the community cache, proxied to the gateway (epic OME-1311).

FEATURE: community cache, available to a local engine (epic OME-1311).
STORY: as a signed-in user of a local engine, I page through the hosted community cache via the
hosted Engine, which is the only door to the gateway that has one.

The gateway owns the contract (NDJSON pages, the cursor, validation, who may read); this route
forwards the caller and streams the page back unchanged. Authentication is the gateway's: it
answers 401 to a caller without a verified identity, and that answer is passed through.

INVARIANT: the page is never decoded or held. A gzip page is passed through still compressed,
with its ``Content-Encoding``, one upstream chunk at a time.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from typing import Annotated, Any

from fastapi import APIRouter, Query, Request
from fastapi.responses import StreamingResponse

from screamingface_engine import job_env
from screamingface_engine.auth import PROBLEM_MEDIA_TYPE, ProblemException
from screamingface_engine.community_cache.port import (
    CachePage,
    CachePageRequest,
    CommunityCache,
    CommunityCacheError,
)
from screamingface_engine.connections.port import Caller
from url4.streaming.trace import valid_traceparent

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Community cache"])

_ERROR_DESCRIPTIONS = {
    401: "The caller has no verified identity, or AI Gateway rejected it.",
    422: "A query parameter is invalid.",
    502: "AI Gateway returned an unusable response.",
    503: "The community cache or AI Gateway is unavailable.",
    504: "AI Gateway did not respond in time.",
}


def _error_responses() -> dict[int | str, dict[str, Any]]:
    return {
        status: {
            "description": description,
            "content": {PROBLEM_MEDIA_TYPE: {"schema": {"$ref": "#/components/schemas/Problem"}}},
        }
        for status, description in _ERROR_DESCRIPTIONS.items()
    }


def _service(request: Request) -> CommunityCache:
    service = getattr(request.app.state, "community_cache", None)
    if service is None:
        raise ProblemException(
            status=503,
            title="Service Unavailable",
            detail="the community cache is not configured on this Engine",
        )
    return service


def _caller(request: Request) -> Caller:
    # WHY `valid_traceparent` (OME-1119): a malformed value forwarded upstream is worse than
    # none; invalid degrades to absent, never to an error.
    return Caller(
        job_env.identity_from_headers(request.headers),
        traceparent=valid_traceparent(request.headers.get("traceparent")),
    )


def _accepts_gzip(request: Request) -> bool:
    accepted = request.headers.get("accept-encoding", "")
    return any(part.split(";")[0].strip() == "gzip" for part in accepted.split(","))


async def _body(page: CachePage) -> AsyncIterator[bytes]:
    # INVARIANT: the upstream response is closed however the stream ends — finished, failed,
    # or abandoned by a client that went away (the generator is closed then).
    try:
        async for chunk in page.aiter_raw():
            yield chunk
    finally:
        await page.aclose()


@router.get(
    "/v1/cache/entries",
    summary="Read one page of the community cache",
    description=(
        "Proxies AI Gateway's `GET /v1/cache/entries`: one NDJSON page of the shareable "
        "community request cache (a header line, one line per row, a trailer line with the "
        "next cursor), passed through unchanged and still compressed when gzip was accepted."
    ),
    response_class=StreamingResponse,
    responses=_error_responses(),
)
async def community_cache_entries(
    request: Request,
    after: str | None = None,
    limit: int | None = None,
    count: bool = False,
    model: Annotated[list[str], Query()] = [],  # noqa: B006 — FastAPI copies defaults
) -> StreamingResponse:
    service = _service(request)
    page_request = CachePageRequest(
        after=after, limit=limit, count=count, models=tuple(model), gzip=_accepts_gzip(request)
    )
    try:
        page = await service.open_page(_caller(request), page_request)
    except CommunityCacheError as exc:
        logger.info("community-cache page request failed: %s", type(exc).__name__)
        raise ProblemException(status=exc.status, title=exc.title, detail=exc.detail) from exc
    headers = {"Cache-Control": "private, no-store", "Vary": "Accept-Encoding, X-User-Email"}
    if page.content_encoding:
        headers["Content-Encoding"] = page.content_encoding
    return StreamingResponse(_body(page), media_type=page.content_type, headers=headers)


__all__ = ["router"]
