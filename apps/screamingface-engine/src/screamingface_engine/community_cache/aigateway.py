"""AI Gateway adapter for the Engine's community-cache port (epic OME-1311).

FEATURE: community cache, available to a local engine (epic OME-1311).

One streamed ``GET /v1/cache/entries`` per page. The response is handed back open, and its body
is read raw: a gzip page stays compressed all the way to the caller.

INVARIANT: the gateway sees the caller's verified identity and trace context and nothing else of
the caller's — the same forwarding rule ``connections.aigateway`` applies.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator

import httpx

from screamingface_engine import job_env
from screamingface_engine.community_cache.port import (
    CachePage,
    CachePageRequest,
    CommunityCacheBadResponse,
    CommunityCacheError,
    CommunityCacheInvalidRequest,
    CommunityCacheRejected,
    CommunityCacheTimeout,
    CommunityCacheUnavailable,
)
from screamingface_engine.connections.port import Caller

logger = logging.getLogger(__name__)

_ENTRIES_PATH = "/v1/cache/entries"
_ERRORS: dict[int, type[CommunityCacheError]] = {
    400: CommunityCacheInvalidRequest,
    401: CommunityCacheRejected,
    403: CommunityCacheRejected,
    422: CommunityCacheInvalidRequest,
    503: CommunityCacheUnavailable,
    504: CommunityCacheTimeout,
}


class _HttpxPage:
    def __init__(self, response: httpx.Response) -> None:
        self._response = response
        self.content_type = response.headers.get("content-type", "application/x-ndjson")
        self.content_encoding = response.headers.get("content-encoding")

    async def aiter_raw(self) -> AsyncIterator[bytes]:
        # WHY raw: `aiter_bytes` would decode a gzip body, holding the Engine's CPU and handing
        # the caller bytes the `Content-Encoding` header no longer describes.
        async for chunk in self._response.aiter_raw():
            yield chunk

    async def aclose(self) -> None:
        await self._response.aclose()


class AigatewayCommunityCache:
    def __init__(self, client: httpx.AsyncClient) -> None:
        self._client = client

    async def open_page(self, caller: Caller, request: CachePageRequest) -> CachePage:
        upstream = self._client.build_request(
            "GET", _ENTRIES_PATH, params=_params(request), headers=_headers(caller, request)
        )
        try:
            response = await self._client.send(upstream, stream=True)
        except httpx.TimeoutException as exc:
            logger.warning("AI Gateway community-cache request timed out")
            raise CommunityCacheTimeout() from exc
        except httpx.HTTPError as exc:
            logger.warning("AI Gateway community-cache transport failure (%s)", type(exc).__name__)
            raise CommunityCacheUnavailable() from exc
        if response.status_code != 200:
            await response.aclose()
            logger.info("AI Gateway community-cache request failed: %s", response.status_code)
            raise _ERRORS.get(response.status_code, CommunityCacheBadResponse)()
        return _HttpxPage(response)

    async def aclose(self) -> None:
        await self._client.aclose()


def _params(request: CachePageRequest) -> httpx.QueryParams:
    params: dict[str, str | list[str]] = {}
    if request.after is not None:
        params["after"] = request.after
    if request.limit is not None:
        params["limit"] = str(request.limit)
    if request.count:
        params["count"] = "true"
    if request.models:
        params["model"] = list(request.models)
    return httpx.QueryParams(params)


def _headers(caller: Caller, request: CachePageRequest) -> dict[str, str]:
    # INVARIANT: the Engine-owned headers are written LAST, so nothing in `caller.identity` can
    # displace them (the rule `connections.aigateway._headers` documents).
    headers = job_env.identity_for_forwarding(caller.identity)
    if caller.traceparent is not None:
        headers["traceparent"] = caller.traceparent
    headers["Accept-Encoding"] = "gzip" if request.gzip else "identity"
    return headers


__all__ = ["AigatewayCommunityCache"]
