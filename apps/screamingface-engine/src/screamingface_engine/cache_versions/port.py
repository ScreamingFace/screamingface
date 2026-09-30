"""Cache-version freeze domain types and the Engine-facing port.

FEATURE: OME-1307 (E14) reproducible submissions — the SDK asks the Engine to freeze the calls of
one captured run trace; the Engine relays the request to AI Gateway and gives back its signed
receipt. The core defines this port; ``cache_versions.aigateway`` implements it.

INVARIANT: only a stable ``code`` and this module's fixed ``detail`` ever cross to the public
route. An upstream error ``message`` or body never does (same rule as ``connections.port``).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol, runtime_checkable

from screamingface_engine.connections.port import Caller

CoverageStatus = Literal["complete", "partial"]


@dataclass(frozen=True, slots=True)
class FrozenCacheVersion:
    """The gateway's freeze answer, validated, opaque receipt included."""

    # WHY opaque: the receipt is the gateway's contract with the scoreboard (C3). The Engine
    # never decodes, verifies or logs it.
    receipt: str
    cache_version_id: str
    entry_count: int
    call_count: int
    missing_count: int
    coverage_status: CoverageStatus
    archive_sha256: str
    # True when the gateway answered 201; False for 200 (an idempotent re-freeze).
    created: bool


class CacheVersionError(Exception):
    """A safe freeze failure with its public HTTP mapping. Same shape as ConnectionError."""

    status = 502
    title = "Bad Gateway"
    detail = "AI Gateway returned an unusable cache version response"
    code: str | None = None

    def __init__(self, detail: str | None = None) -> None:
        # Accepting a caller message is useful for logs/tests, but public routes always use
        # the class-level safe detail.
        self.internal_detail = detail
        super().__init__(self.detail)


class TraceNotCaptured(CacheVersionError):
    """The gateway holds no captured calls for this trace."""

    status = 404
    title = "Not Found"
    detail = "no captured calls exist for this trace"
    code = "trace_not_captured"


class CacheVersionTooLarge(CacheVersionError):
    """The trace exceeds the gateway's freeze limits."""

    status = 413
    title = "Content Too Large"
    detail = "the trace is too large to freeze as one cache version"
    code = "cache_version_too_large"


class CaptureDisabled(CacheVersionError):
    """Cache version capture is switched off on the gateway."""

    status = 503
    title = "Service Unavailable"
    detail = "cache version capture is disabled on AI Gateway"
    code = "capture_disabled"


class CacheVersionUnauthorized(CacheVersionError):
    """The gateway did not accept the caller identity."""

    status = 401
    title = "Unauthorized"
    detail = "AI Gateway did not accept the caller identity"


class CacheVersionForbidden(CacheVersionError):
    """The gateway refused the freeze for this caller."""

    status = 403
    title = "Forbidden"
    detail = "AI Gateway refused the freeze for this caller"


class CacheVersionRateLimited(CacheVersionError):
    """The gateway rate limited the freeze."""

    status = 429
    title = "Too Many Requests"
    detail = "cache version requests are temporarily rate limited"


class CacheVersionBadResponse(CacheVersionError):
    """The gateway answered with an unusable status or body (the base values: 502)."""


class CacheVersionsUnavailable(CacheVersionError):
    """The gateway could not be reached, or answered an uncoded 503."""

    status = 503
    title = "Service Unavailable"
    detail = "AI Gateway is unavailable"


class CacheVersionTimeout(CacheVersionError):
    """The gateway did not answer the freeze before the Engine timeout."""

    status = 504
    title = "Gateway Timeout"
    detail = "AI Gateway did not answer the freeze in time"


@runtime_checkable
class CacheVersions(Protocol):
    """The engine-facing freeze port."""

    async def freeze(self, caller: Caller, trace_id: str) -> FrozenCacheVersion: ...

    async def aclose(self) -> None: ...


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
]
