"""AI Gateway adapter for the SF Engine cache-version freeze port.

FEATURE: OME-1307 (E14), contract C2b (engine -> gateway): one ``POST /v1/cache-versions`` per
freeze, with the caller identity, relaying the gateway's signed receipt.

INVARIANT: no retry (the SDK owns it); the receipt is opaque and never decoded or logged; an
upstream error ``message`` or body is never copied into an error or a log line.
"""

from __future__ import annotations

import dataclasses
import logging
import re
from typing import Any, cast

import httpx

from screamingface_engine.cache_versions.port import (
    CacheVersionBadResponse,
    CacheVersionError,
    CacheVersionForbidden,
    CacheVersionRateLimited,
    CacheVersionsUnavailable,
    CacheVersionTimeout,
    CacheVersionTooLarge,
    CacheVersionUnauthorized,
    CaptureDisabled,
    CoverageStatus,
    FrozenCacheVersion,
    TraceNotCaptured,
)
from screamingface_engine.connections.port import Caller
from screamingface_engine.connections.uuid_text import is_uuid

logger = logging.getLogger(__name__)

_FREEZE_PATH = "/v1/cache-versions"
_SHA256_HEX = re.compile(r"[0-9a-f]{64}")
_COVERAGE: tuple[CoverageStatus, ...] = ("complete", "partial")
# WHY derived: the gateway body is exactly the frozen version less `created`, which is the HTTP
# status (201 vs 200) and never a body key.
_BODY_KEYS = frozenset(field.name for field in dataclasses.fields(FrozenCacheVersion)) - {"created"}


class AigatewayCacheVersions:
    """Freeze one captured run trace through AI Gateway's cache-version route."""

    def __init__(self, client: httpx.AsyncClient) -> None:
        self._client = client

    async def freeze(self, caller: Caller, trace_id: str) -> FrozenCacheVersion:
        try:
            response = await self._client.post(
                _FREEZE_PATH,
                json={"trace_id": trace_id},
                headers=caller.upstream_headers(),
            )
        except httpx.TimeoutException as exc:
            logger.warning("AI Gateway cache version request timed out")
            raise CacheVersionTimeout() from exc
        except httpx.HTTPError as exc:
            logger.warning("AI Gateway cache version transport failure (%s)", type(exc).__name__)
            raise CacheVersionsUnavailable() from exc
        _raise_for_status(response)
        if response.status_code not in (200, 201):
            raise CacheVersionBadResponse()
        return _decode(response)

    async def aclose(self) -> None:
        await self._client.aclose()


def _raise_for_status(response: httpx.Response) -> None:
    if response.status_code < 300:
        return
    status = response.status_code
    error: type[CacheVersionError]
    if status == 503:
        # WHY the code decides: only `capture_disabled` is a named, actionable 503; any other
        # 503 is plain unavailability.
        error = (
            CaptureDisabled
            if _error_code(response) == "capture_disabled"
            else (CacheVersionsUnavailable)
        )
    else:
        error = {
            401: CacheVersionUnauthorized,
            403: CacheVersionForbidden,
            404: TraceNotCaptured,
            413: CacheVersionTooLarge,
            429: CacheVersionRateLimited,
            504: CacheVersionTimeout,
        }.get(status, CacheVersionBadResponse)
    raise error()


def _error_code(response: httpx.Response) -> str | None:
    """The gateway's stable code from `{"detail": {"code": ...}}`; None for any other shape.

    INVARIANT: never raises — an unreadable error body means "no code".
    """
    try:
        body: object = response.json()
    except ValueError:
        return None
    detail = cast(dict[str, Any], body).get("detail") if isinstance(body, dict) else None
    code = cast(dict[str, Any], detail).get("code") if isinstance(detail, dict) else None
    return code if isinstance(code, str) else None


def _decode(response: httpx.Response) -> FrozenCacheVersion:
    try:
        body = response.json()
    except ValueError as exc:
        raise CacheVersionBadResponse() from exc
    if not isinstance(body, dict) or set(cast(dict[str, Any], body)) != _BODY_KEYS:
        raise CacheVersionBadResponse()
    fields = cast(dict[str, Any], body)
    receipt = fields["receipt"]
    coverage = fields["coverage_status"]
    sha = fields["archive_sha256"]
    if (
        not isinstance(receipt, str)
        or not receipt.strip()
        or not is_uuid(fields["cache_version_id"])
        or not all(_is_count(fields[key]) for key in ("entry_count", "call_count", "missing_count"))
        or coverage not in _COVERAGE
        or not isinstance(sha, str)
        or _SHA256_HEX.fullmatch(sha) is None
    ):
        raise CacheVersionBadResponse()
    return FrozenCacheVersion(
        receipt=receipt,
        cache_version_id=fields["cache_version_id"],
        entry_count=fields["entry_count"],
        call_count=fields["call_count"],
        missing_count=fields["missing_count"],
        coverage_status=coverage,
        archive_sha256=sha,
        created=response.status_code == 201,
    )


def _is_count(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


__all__ = ["AigatewayCacheVersions"]
