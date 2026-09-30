"""SF Engine cache-version freeze adapter (contracts.md C2a).

FEATURE: OME-1307 (E14) reproducible submissions. The adapter of the freeze port in
`_core/ports.py`. `_scoreboard/leaderboards.py` sees only the port, never this module.
"""

from __future__ import annotations

import asyncio
import random
import re
import time
from collections.abc import Awaitable, Callable
from functools import partial
from typing import Final, Literal
from uuid import UUID

import httpx

from screamingface._core.attempts import (
    _Again,
    _Attempt,
    _Done,
    _Step,
    drive_async,
    drive_sync,
)
from screamingface._core.ports import _FreezeOutcome, _FreezeUnavailable, _FrozenCacheVersion
from screamingface._core.wire import detail_code
from screamingface.errors import AuthenticationError, EngineUnavailableError

_PATH: Final = "/v1/cache-versions"
_TIMEOUT_S: Final = 60.0  # C2a
_RETRY_STATUS: Final = frozenset({502, 503, 504})  # C2a
_ATTEMPTS: Final = 2  # C2a: one retry
# WHY these three: the engine request can fail with an `httpx` error that is not a transport
# error (`DecodingError`, `TooManyRedirects`) and with an SDK error from the Access auth flow.
# None of them may leave `freeze`: a failed freeze never stops a submit (SC-E1).
_UNRETRIED: Final = (httpx.HTTPError, AuthenticationError, EngineUnavailableError)
# INVARIANT: a reason goes into a log line and a user-visible warning, so it is always a token
# that matches this pattern, never text from a server body.
_REASON: Final = re.compile(r"^[a-z0-9_]{1,64}$")
_SHA256: Final = re.compile(r"^[0-9a-f]{64}$")


def _jitter() -> float:
    return random.uniform(1.0, 3.0)  # C2a: 1-3 s


class EngineCacheVersions:
    """Synchronous freeze adapter bound to one Client's engine request."""

    def __init__(
        self,
        request: Callable[..., httpx.Response],
        *,
        sleep: Callable[[float], None] = time.sleep,
        jitter: Callable[[], float] = _jitter,
    ) -> None:
        self._request = request
        self._sleep = sleep
        self._jitter = jitter

    def freeze(self, trace_id: str) -> _FreezeOutcome:
        """Freeze one trace. INVARIANT: never raises for a network or HTTP failure."""
        return drive_sync(
            partial(_send_freeze, self._request, trace_id),
            partial(_freeze_step, jitter=self._jitter),
            self._sleep,
            _UNRETRIED,
        )


class AsyncEngineCacheVersions:
    """Asynchronous freeze adapter bound to one AsyncClient's engine request."""

    def __init__(
        self,
        request: Callable[..., Awaitable[httpx.Response]],
        *,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        jitter: Callable[[], float] = _jitter,
    ) -> None:
        self._request = request
        self._sleep = sleep
        self._jitter = jitter

    async def freeze(self, trace_id: str) -> _FreezeOutcome:
        """Freeze one trace. INVARIANT: never raises for a network or HTTP failure."""
        return await drive_async(
            partial(_send_freeze, self._request, trace_id),
            partial(_freeze_step, jitter=self._jitter),
            self._sleep,
            _UNRETRIED,
        )


def _send_freeze[R](request: Callable[..., R], trace_id: str) -> R:
    return request("POST", _PATH, json={"trace_id": trace_id}, timeout=_TIMEOUT_S)


def _freeze_step(
    attempt: int, outcome: _Attempt, jitter: Callable[[], float]
) -> _Step[_FreezeOutcome]:
    """Settle one attempt (C2a): done, or one retry after a jittered wait. Pure but for `jitter`."""
    result: _FreezeOutcome
    if isinstance(outcome, httpx.TransportError):
        result, retry = _transport_failure(outcome), True
    elif isinstance(outcome, Exception):
        return _Done(_unretried_failure(outcome))
    else:
        result, retry = _outcome(outcome)
    if retry and attempt + 1 < _ATTEMPTS:
        return _Again(jitter())
    return _Done(result)


def _transport_failure(exc: httpx.TransportError) -> _FreezeUnavailable:
    return _FreezeUnavailable(
        "timeout" if isinstance(exc, httpx.TimeoutException) else "unreachable"
    )


def _unretried_failure(exc: Exception) -> _FreezeUnavailable:
    """A failure that is not a transient network fault, so C2a gives it no retry."""
    return _FreezeUnavailable(
        "engine_auth_failed" if isinstance(exc, AuthenticationError) else "unreachable"
    )


def _outcome(response: httpx.Response) -> tuple[_FreezeOutcome, bool]:
    """The outcome of one attempt, and whether C2a allows a retry after it."""
    status = response.status_code
    if status in _RETRY_STATUS:
        return _FreezeUnavailable(f"http_{status}"), True
    if status in (200, 201):
        return _decode_freeze(response), False
    return _FreezeUnavailable(_error_reason(response)), False


def _error_reason(response: httpx.Response) -> str:
    """The server's own code when it is a safe token, else `http_<status>` (D7 X-8).

    The engine uses a top-level `code`. A gateway body that the engine passes through carries
    `detail.code`.
    """
    fallback = f"http_{response.status_code}"
    try:
        body = response.json()
    except ValueError:
        return fallback
    code = _first_code(body)
    return code if code is not None and _REASON.fullmatch(code) else fallback


def _first_code(body: object) -> str | None:
    if not isinstance(body, dict):
        return None
    top = body.get("code")
    if isinstance(top, str) and top.strip():
        return top.strip()
    return detail_code(body)


def _decode_freeze(response: httpx.Response) -> _FreezeOutcome:
    """Strict C2a decode. Any doubt gives `invalid_response`: a bad body carries no receipt."""
    try:
        return _parse_frozen(response.json())
    except ValueError:
        return _FreezeUnavailable("invalid_response")


def _parse_frozen(body: object) -> _FrozenCacheVersion:
    if not isinstance(body, dict):
        raise ValueError("cache version body must be an object")
    return _FrozenCacheVersion(
        receipt=_receipt(body.get("receipt")),
        cache_version_id=_uuid(body.get("cache_version_id")),
        entry_count=_count(body.get("entry_count")),
        call_count=_count(body.get("call_count")),
        missing_count=_count(body.get("missing_count")),
        coverage_status=_coverage(body.get("coverage_status")),
        archive_sha256=_digest(body.get("archive_sha256")),
    )


def _receipt(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("receipt must be non-blank text")
    return value


def _uuid(value: object) -> UUID:
    if not isinstance(value, str):
        raise ValueError("cache_version_id must be a UUID string")
    return UUID(value)


def _count(value: object) -> int:
    # WHY `bool` is refused: it is an `int` in Python, and `true` is not a count.
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError("a count must be a non-negative integer")
    return value


def _coverage(value: object) -> Literal["complete", "partial"]:
    if value == "complete":
        return "complete"
    if value == "partial":
        return "partial"
    raise ValueError("coverage_status must be complete or partial")


def _digest(value: object) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise ValueError("archive_sha256 must be 64 lowercase hex characters")
    return value


__all__ = ["AsyncEngineCacheVersions", "EngineCacheVersions"]
