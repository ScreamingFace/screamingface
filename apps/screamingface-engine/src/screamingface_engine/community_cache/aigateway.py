"""AI Gateway adapter for the Engine's community-cache port (epic OME-1311).

FEATURE: community cache, available to a local engine (epic OME-1311).

One streamed ``GET /v1/cache/entries`` per page. The response is handed back open, and its body
is read raw: a gzip page stays compressed all the way to the caller.

INVARIANT: the gateway sees the caller's verified identity and trace context and nothing else of
the caller's — the same forwarding rule ``connections.aigateway`` applies.
"""

from __future__ import annotations

import logging
import re
from collections.abc import AsyncIterator

import anyio
import httpx

from screamingface_engine import job_env
from screamingface_engine.community_cache.port import (
    CachePage,
    CachePageRequest,
    CommunityCacheBadResponse,
    CommunityCacheError,
    CommunityCacheInvalidRequest,
    CommunityCacheRateLimited,
    CommunityCacheRejected,
    CommunityCacheTimeout,
    CommunityCacheUnavailable,
)
from screamingface_engine.connections.port import Caller

logger = logging.getLogger(__name__)

_ENTRIES_PATH = "/v1/cache/entries"
# WHY bounded: `int()` refuses more than 4,300 digits with a ValueError, and no real delay needs
# more than nine.
_RETRY_AFTER = re.compile(r"[0-9]{1,9}")
# WHY local, not `connections.upstream_errors`: the same statuses mean different things here —
# 400/422 are the page query, 403 is the gateway refusing this Engine (502), and 429 carries its
# `Retry-After` — so one shared table would be a parameter per difference. The transport
# handling in `open_page` stays local for the same reason: it raises this surface's own errors.
_ERRORS: dict[int, type[CommunityCacheError]] = {
    400: CommunityCacheInvalidRequest,
    401: CommunityCacheRejected,
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
        try:
            async for chunk in self._response.aiter_raw():
                yield chunk
        except httpx.TimeoutException as exc:
            logger.warning("AI Gateway community-cache page timed out mid-stream")
            raise CommunityCacheTimeout() from exc
        except httpx.HTTPError as exc:
            logger.warning(
                "AI Gateway community-cache page failed mid-stream (%s)", type(exc).__name__
            )
            raise CommunityCacheUnavailable() from exc

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
            status, retry_after = response.status_code, _retry_after(response)
            await _close(response)
            logger.info("AI Gateway community-cache request failed: %s", status)
            if status == 403:
                # WHY not 401: the gateway answers 403 only to a peer it does not trust (or a
                # non-loopback caller when its auth is disabled) — this Engine's deployment, not
                # the user's identity. It falls through to 502.
                logger.warning(
                    "AI Gateway refused this Engine as a peer (403) — check its trusted networks"
                )
            if status == 429:
                raise CommunityCacheRateLimited(retry_after)
            raise _ERRORS.get(status, CommunityCacheBadResponse)()
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


async def _close(response: httpx.Response) -> None:
    # INVARIANT: closing a refused response never replaces the typed error the caller gets. WHY
    # shielded: a cancelled request would otherwise skip the close and leak the connection.
    with anyio.CancelScope(shield=True):
        try:
            await response.aclose()
        except Exception as exc:  # noqa: BLE001 — logged; the status is what the caller needs
            logger.warning(
                "AI Gateway community-cache response failed to close (%s)", type(exc).__name__
            )


def _retry_after(response: httpx.Response) -> int | None:
    # WHY whole seconds only: an HTTP-date or a malformed value is not passed on unchecked; the
    # caller just gets no hint.
    value = response.headers.get("retry-after", "").strip()
    return int(value) if _RETRY_AFTER.fullmatch(value) else None


def _headers(caller: Caller, request: CachePageRequest) -> dict[str, str]:
    # INVARIANT: written after the caller's headers, so nothing in `caller.identity` can displace
    # it (the rule `job_env.upstream_headers` documents).
    headers = job_env.upstream_headers(caller.identity, caller.traceparent)
    headers["Accept-Encoding"] = "gzip" if request.gzip else "identity"
    return headers


__all__ = ["AigatewayCommunityCache"]
