"""The community cache's Engine-facing port (epic OME-1311).

FEATURE: community cache, available to a local engine (epic OME-1311).
Spec: ``docs/spec/2026-10-15-community-cache.md`` (decision 6, PR 2 of the plan).

The Engine is a door, not a reader: it opens one page from the gateway and hands its bytes back
as they arrive. So the port's value is an open stream (``CachePage``), never a decoded page — a
page of the heaviest model is ~235 MB of rows, and nothing on the Engine may hold one.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from screamingface_engine.connections.port import Caller


@dataclass(frozen=True, slots=True)
class CachePageRequest:
    """One page's query, as the caller stated it; the gateway validates the values."""

    after: str | None = None
    limit: int | None = None
    count: bool = False
    models: tuple[str, ...] = ()
    # Whether the caller accepts a gzip body. The Engine asks the gateway for exactly that, so it
    # never has to decode or re-encode the page itself.
    gzip: bool = False


class CachePage(Protocol):
    """An open, successful upstream page. ``aclose`` must be called once it is done with."""

    content_type: str
    content_encoding: str | None

    def aiter_raw(self) -> AsyncIterator[bytes]: ...

    async def aclose(self) -> None: ...


@runtime_checkable
class CommunityCache(Protocol):
    async def open_page(self, caller: Caller, request: CachePageRequest) -> CachePage: ...

    async def aclose(self) -> None: ...


class CommunityCacheError(Exception):
    """A safe community-cache failure with its public HTTP mapping.

    WHY class-level details only: the upstream body is never repeated to the caller, the same
    rule ``connections.port.ConnectionError`` applies.
    """

    status = 502
    title = "Bad Gateway"
    detail = "AI Gateway returned an unusable community-cache response"


class CommunityCacheBadResponse(CommunityCacheError):
    pass


class CommunityCacheRejected(CommunityCacheError):
    status = 401
    title = "Unauthorized"
    detail = "the caller identity was rejected"


class CommunityCacheInvalidRequest(CommunityCacheError):
    status = 422
    title = "Unprocessable Content"
    detail = "the community-cache page request is invalid"


class CommunityCacheUnavailable(CommunityCacheError):
    status = 503
    title = "Service Unavailable"
    detail = "AI Gateway is unavailable"


class CommunityCacheTimeout(CommunityCacheError):
    status = 504
    title = "Gateway Timeout"
    detail = "AI Gateway did not respond in time"


__all__ = [
    "CachePage",
    "CachePageRequest",
    "CommunityCache",
    "CommunityCacheBadResponse",
    "CommunityCacheError",
    "CommunityCacheInvalidRequest",
    "CommunityCacheRejected",
    "CommunityCacheTimeout",
    "CommunityCacheUnavailable",
]
