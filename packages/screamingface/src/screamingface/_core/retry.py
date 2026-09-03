"""Retry a request the caller declared replay-safe, when the failure is transient.

WHY a transport and not a helper at each call site: the policy that matters here is a SAFETY
policy — which requests may be re-sent — and a rule enforced in one place cannot be forgotten
by the next call site added. The transport sees every request the client makes.

INVARIANT — the whole point of this module: retry is gated on the `_REPLAY_SAFE` request
extension and NEVER on the HTTP method. `GET /?q=` starts billable work despite being a GET
(see `_core.wire._REPLAY_SAFE`), so a layer that assumed GETs were replayable would double-fire
paid Runs. Replay safety is a property of the REQUEST — does re-sending duplicate a side
effect — not of the response status, which is why the same marker answers both "safe to
re-send after an Access login" and "safe to re-send after a transient edge failure".

FEATURE (OME-1107): a single Cloudflare 520 on one `POST /token` ended an evaluation of 8
candidates after 7 had already completed. The origin was healthy throughout; the blip lived
above it, in the tunnel.
"""

from __future__ import annotations

import asyncio
import random
import time
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime

import httpx

from screamingface._core.wire import _REPLAY_SAFE

# Statuses worth a second attempt: gateway/edge failures, an explicit "slow down", and a
# timeout the origin never saw.
#
# WHY 500 is ABSENT: an application error is deterministic — repeating it wastes the caller's
# time and hides the defect. 520-524 are Cloudflare's own "origin misbehaved" family, which is
# exactly the class that produced the incident this module exists for.
_RETRYABLE_STATUS = frozenset({408, 429, 502, 503, 504, 520, 521, 522, 523, 524})

_DEFAULT_ATTEMPTS = 3
_DEFAULT_BASE_DELAY_S = 0.25
_DEFAULT_MAX_DELAY_S = 4.0
# An honest ceiling on obedience: a server may ask for an hour, and silently sleeping that long
# is indistinguishable from a hang. Past this bound the response is surfaced so the CALLER
# decides — see `_RetryPlan.wait_for`.
_DEFAULT_MAX_RETRY_AFTER_S = 30.0


def _replay_safe(request: httpx.Request) -> bool:
    return bool(request.extensions.get(_REPLAY_SAFE, False))


def _http_date(text: str) -> datetime | None:
    """The HTTP-date form of `Retry-After`, normalised to UTC, or None if it is not one."""
    try:
        when = parsedate_to_datetime(text)
    except (TypeError, ValueError):
        return None
    return when if when.tzinfo is not None else when.replace(tzinfo=UTC)


def _retry_after_seconds(response: httpx.Response) -> float | None:
    """`Retry-After` as seconds, accepting both wire forms, or None when absent/unparsable."""
    raw = response.headers.get("retry-after")
    if not raw:
        return None
    text = raw.strip()
    try:
        return max(0.0, float(int(text)))
    except ValueError:
        pass
    when = _http_date(text)
    return None if when is None else max(0.0, (when - datetime.now(UTC)).total_seconds())


class _RetryPlan:
    """The policy half, shared by the sync and async transports so they cannot drift."""

    def __init__(
        self,
        *,
        attempts: int,
        base_delay: float,
        max_delay: float,
        max_retry_after: float,
        jitter: Callable[[], float],
    ) -> None:
        if attempts < 1:
            raise ValueError(f"attempts must be >= 1, got {attempts}")
        self.attempts = attempts
        self._base_delay = base_delay
        self._max_delay = max_delay
        self._max_retry_after = max_retry_after
        self._jitter = jitter

    def backoff(self, attempt: int) -> float:
        """Bounded exponential backoff with jitter — a tight loop against a struggling edge is
        a second outage, not a recovery, and unjittered retries from many clients resynchronise
        into one."""
        raw = min(self._max_delay, self._base_delay * (2 ** (attempt - 1)))
        return raw * (1.0 + 0.25 * self._jitter())

    def wait_for(self, response: httpx.Response, attempt: int) -> float | None:
        """Seconds to wait before re-sending, or None to stop and surface this response.

        An explicit `Retry-After` is obeyed verbatim rather than jittered — the server named a
        number, and second-guessing it is how a thundering herd starts — but only up to the
        cap, past which stopping is more honest than an unbounded sleep.
        """
        requested = _retry_after_seconds(response)
        if requested is None:
            return self.backoff(attempt)
        if requested > self._max_retry_after:
            return None
        return requested


class RetryingTransport(httpx.BaseTransport):
    """Wraps a transport, re-sending replay-safe requests that fail transiently."""

    def __init__(
        self,
        inner: httpx.BaseTransport,
        *,
        attempts: int = _DEFAULT_ATTEMPTS,
        base_delay: float = _DEFAULT_BASE_DELAY_S,
        max_delay: float = _DEFAULT_MAX_DELAY_S,
        max_retry_after: float = _DEFAULT_MAX_RETRY_AFTER_S,
        sleep: Callable[[float], object] = time.sleep,
        jitter: Callable[[], float] = random.random,
    ) -> None:
        self._inner = inner
        self._sleep = sleep
        self._plan = _RetryPlan(
            attempts=attempts,
            base_delay=base_delay,
            max_delay=max_delay,
            max_retry_after=max_retry_after,
            jitter=jitter,
        )

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        if not _replay_safe(request):
            return self._inner.handle_request(request)
        # Materialise the body before the first attempt: a stream can only be consumed once,
        # so a request that was never read cannot be re-sent.
        request.read()
        for attempt in range(1, self._plan.attempts + 1):
            last = attempt == self._plan.attempts
            try:
                response = self._inner.handle_request(request)
            except httpx.TransportError:
                if last:
                    raise
                self._sleep(self._plan.backoff(attempt))
                continue
            if response.status_code not in _RETRYABLE_STATUS or last:
                return response
            delay = self._plan.wait_for(response, attempt)
            if delay is None:
                return response
            # Release the connection before re-sending; a discarded body would otherwise hold
            # it for the life of the pool.
            response.read()
            response.close()
            self._sleep(delay)
        raise AssertionError("unreachable: the final attempt returns or raises")

    def close(self) -> None:
        self._inner.close()


class RetryingAsyncTransport(httpx.AsyncBaseTransport):
    """The async twin of `RetryingTransport`; same policy object, same invariant."""

    def __init__(
        self,
        inner: httpx.AsyncBaseTransport,
        *,
        attempts: int = _DEFAULT_ATTEMPTS,
        base_delay: float = _DEFAULT_BASE_DELAY_S,
        max_delay: float = _DEFAULT_MAX_DELAY_S,
        max_retry_after: float = _DEFAULT_MAX_RETRY_AFTER_S,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        jitter: Callable[[], float] = random.random,
    ) -> None:
        self._inner = inner
        self._sleep = sleep
        self._plan = _RetryPlan(
            attempts=attempts,
            base_delay=base_delay,
            max_delay=max_delay,
            max_retry_after=max_retry_after,
            jitter=jitter,
        )

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        if not _replay_safe(request):
            return await self._inner.handle_async_request(request)
        await request.aread()
        for attempt in range(1, self._plan.attempts + 1):
            last = attempt == self._plan.attempts
            try:
                response = await self._inner.handle_async_request(request)
            except httpx.TransportError:
                if last:
                    raise
                await self._sleep(self._plan.backoff(attempt))
                continue
            if response.status_code not in _RETRYABLE_STATUS or last:
                return response
            delay = self._plan.wait_for(response, attempt)
            if delay is None:
                return response
            await response.aread()
            await response.aclose()
            await self._sleep(delay)
        raise AssertionError("unreachable: the final attempt returns or raises")

    async def aclose(self) -> None:
        await self._inner.aclose()


__all__ = ["RetryingAsyncTransport", "RetryingTransport"]
