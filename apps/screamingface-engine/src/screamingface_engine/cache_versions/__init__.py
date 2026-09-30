"""Cache-version freeze subsystem and production composition helper (RED stub)."""

from __future__ import annotations

from collections.abc import Callable
from typing import Protocol

import httpx

from screamingface_engine.cache_versions.aigateway import AigatewayCacheVersions
from screamingface_engine.cache_versions.port import (
    CacheVersionBadResponse,
    CacheVersionError,
    CacheVersionForbidden,
    CacheVersionRateLimited,
    CacheVersions,
    CacheVersionsUnavailable,
    CacheVersionTimeout,
    CacheVersionTooLarge,
    CacheVersionUnauthorized,
    CaptureDisabled,
    CoverageStatus,
    FrozenCacheVersion,
    TraceNotCaptured,
)

_UPSTREAM_TIMEOUT_S = 55.0


class _CacheVersionSettings(Protocol):
    aigateway_base_url: str | None


def _default_client(base_url: str) -> httpx.AsyncClient:
    return httpx.AsyncClient(base_url=base_url, timeout=_UPSTREAM_TIMEOUT_S)


def build_cache_versions(
    settings: _CacheVersionSettings,
    *,
    client_factory: Callable[[str], httpx.AsyncClient] = _default_client,
) -> CacheVersions | None:
    if not settings.aigateway_base_url:
        return None
    return AigatewayCacheVersions(client_factory(settings.aigateway_base_url))


__all__ = [
    "CacheVersionBadResponse",
    "CacheVersionError",
    "CacheVersionForbidden",
    "CacheVersionRateLimited",
    "CacheVersionTimeout",
    "CacheVersionTooLarge",
    "CacheVersionUnauthorized",
    "CacheVersions",
    "CacheVersionsUnavailable",
    "CaptureDisabled",
    "CoverageStatus",
    "FrozenCacheVersion",
    "TraceNotCaptured",
    "build_cache_versions",
]
