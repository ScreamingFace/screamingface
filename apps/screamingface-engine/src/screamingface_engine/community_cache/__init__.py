"""Community-cache subsystem and production composition helper (epic OME-1311)."""

from __future__ import annotations

from collections.abc import Callable
from typing import Protocol

import httpx

from screamingface_engine.community_cache.aigateway import AigatewayCommunityCache
from screamingface_engine.community_cache.port import CommunityCache

# WHY a per-phase timeout and no total one: httpx's `read` timeout bounds the gap between chunks,
# not the whole response, so a large page that keeps flowing is never cut. `read` also covers
# the wait for the first byte, which can include the gateway's `count(*)` on `count=true`.
_TIMEOUT = httpx.Timeout(10.0, read=60.0)


class _CommunityCacheSettings(Protocol):
    aigateway_base_url: str | None


def _default_client(base_url: str) -> httpx.AsyncClient:
    return httpx.AsyncClient(base_url=base_url, timeout=_TIMEOUT)


def build_community_cache(
    settings: _CommunityCacheSettings,
    *,
    client_factory: Callable[[str], httpx.AsyncClient] = _default_client,
) -> CommunityCache | None:
    """Build the AI Gateway adapter, or disable the route when no upstream is configured."""
    if not settings.aigateway_base_url:
        return None
    return AigatewayCommunityCache(client_factory(settings.aigateway_base_url))


__all__ = ["CommunityCache", "build_community_cache"]
