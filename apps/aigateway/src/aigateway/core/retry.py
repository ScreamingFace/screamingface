"""Reactive backpressure: retry rate-limited / overloaded upstream dispatches.

Status-code driven (duck-typed on ``status_code``), so it covers LiteLLM's
``RateLimitError`` / ``ServiceUnavailableError`` (which carry ``status_code``)
and any exception exposing one of the retryable codes. Stdlib-only.
"""

from __future__ import annotations

import asyncio
import logging
import random
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ..config import Settings

logger = logging.getLogger(__name__)

# 429 rate-limited, 503 service-unavailable, 529 overloaded (Anthropic).
RETRYABLE_STATUS_CODES = frozenset({429, 503, 529})
_MAX_RETRY_AFTER_SECONDS = (1 << 63) - 1
_MAX_RETRY_AFTER_TEXT = str(_MAX_RETRY_AFTER_SECONDS)


def _safe_getattr(obj: Any, name: str) -> Any:
    """Read an untrusted exception attribute without escaping the error path."""
    try:
        return getattr(obj, name, None)
    except Exception:
        return None


@dataclass(frozen=True)
class RetryPolicy:
    max_retries: int = 3
    backoff_base_seconds: float = 0.5
    backoff_max_seconds: float = 8.0
    max_total_wait_seconds: float = 30.0
    jitter_seconds: float = 0.25

    @classmethod
    def from_settings(cls, settings: Settings) -> RetryPolicy:
        return cls(
            max_retries=settings.retry_max_attempts,
            backoff_base_seconds=settings.retry_backoff_base_seconds,
            backoff_max_seconds=settings.retry_backoff_max_seconds,
            max_total_wait_seconds=settings.retry_max_total_wait_seconds,
            jitter_seconds=settings.retry_jitter_seconds,
        )


def _status_code(exc: BaseException) -> int | None:
    code = _safe_getattr(exc, "status_code")
    # bool is an int subclass; reject it explicitly.
    if isinstance(code, bool) or not isinstance(code, int):
        return None
    return code


def is_retryable_status(exc: BaseException) -> bool:
    # WHY (OME-428 CODE-2): errors manufactured from an already-returned
    # upstream payload (core.provider_errors.NonRetryableProviderError) carry
    # a retryable-looking status_code but the upstream call already happened —
    # retrying would re-dispatch a possibly-billed request. Duck-typed so this
    # module stays stdlib-only.
    if _safe_getattr(exc, "aigw_non_retryable") is True:
        return False
    return _status_code(exc) in RETRYABLE_STATUS_CODES


def _seconds_from_headers(headers: Any) -> int | None:
    if headers is None:
        return None
    raw = case_insensitive_header(headers, "retry-after")
    if raw is None:
        return None
    # RFC 9110 delay-seconds = 1*DIGIT: ASCII, unsigned, integral. HTTP-date
    # remains unsupported and falls through to the next source/backoff.
    if not isinstance(raw, str) or not raw or not raw.isascii() or not raw.isdecimal():
        return None
    normalized = raw.lstrip("0") or "0"
    if len(normalized) > len(_MAX_RETRY_AFTER_TEXT) or (
        len(normalized) == len(_MAX_RETRY_AFTER_TEXT) and normalized > _MAX_RETRY_AFTER_TEXT
    ):
        # Keep a syntactically valid but absurd hint valid and budget-exceeding;
        # never let Python's integer digit limit turn it into fallback/retry.
        return _MAX_RETRY_AFTER_SECONDS
    return int(normalized)


def case_insensitive_header(headers: Any, name: str) -> Any:
    """Read ``name`` from ``headers`` regardless of key casing.

    ``httpx.Headers`` is case-insensitive natively, but FastAPI's
    ``HTTPException`` stores ``headers`` as the literal dict passed in
    (so the key is whatever the caller wrote, typically ``"Retry-After"``).
    A plain ``dict.get("retry-after")`` would miss it and silently drop the
    hint.
    """
    if not isinstance(headers, Mapping):
        return None
    target = name.lower()
    try:
        value = headers.get(name)
        if value is not None:
            return value
        for key, val in headers.items():
            if isinstance(key, str) and key.lower() == target:
                return val
    except Exception:
        return None
    return None


def parse_retry_after_seconds(exc: BaseException) -> int | None:
    """Read an integer ``Retry-After`` (delta-seconds) off the exception.

    # WHY (blocker C): litellm 1.87.0 surfaces an OpenRouter transport 429/503's
    # wire header on ``exc.litellm_response_headers`` — ``exc.response.headers``
    # is empty there — so that source must be read or the validated hint is lost.
    # Precedence is fixed and total: ``response.headers`` (httpx canonical) →
    # ``litellm_response_headers`` (litellm's extracted wire headers) →
    # ``exc.headers`` (FastAPI ``HTTPException`` — how the plugins surface upstream
    # 429s, e.g. the Gemini reset hint). The first source yielding a valid integer
    # wins; that single value drives both the retry sleep and the response header.
    # Returns ``None`` for absent/invalid/HTTP-date values so the
    # caller falls back to exponential backoff. Never raises.
    """
    response_headers = _safe_getattr(_safe_getattr(exc, "response"), "headers")
    for headers in (
        response_headers,
        _safe_getattr(exc, "litellm_response_headers"),
        _safe_getattr(exc, "headers"),
    ):
        seconds = _seconds_from_headers(headers)
        if seconds is not None:
            return seconds
    return None


async def with_overload_retry[T](
    dispatch: Callable[[], Awaitable[T]],
    *,
    policy: RetryPolicy,
    sleep: Callable[[float], Awaitable[Any]] = asyncio.sleep,
) -> T:
    """Run ``dispatch``; retry on retryable overload statuses with backoff.

    Honors ``Retry-After`` when present, else exponential backoff + jitter.
    Bounded by ``max_retries`` and a cumulative ``max_total_wait_seconds``
    budget. Re-raises the original exception on exhaustion or non-retryable
    errors.
    """
    attempt = 0
    total_waited = 0.0
    while True:
        try:
            return await dispatch()
        except Exception as exc:
            if not is_retryable_status(exc) or attempt >= policy.max_retries:
                raise
            retry_after = parse_retry_after_seconds(exc)
            delay: int | float
            if retry_after is None:
                delay = min(
                    policy.backoff_base_seconds * 2**attempt,
                    policy.backoff_max_seconds,
                )
            else:
                delay = retry_after
            remaining_budget = policy.max_total_wait_seconds - total_waited
            # Check an integer provider hint before adding float jitter: a very
            # large but syntactically valid delta-seconds must re-raise the
            # original overload, not overflow during int-to-float conversion.
            if delay > remaining_budget:
                raise
            # Jitter both paths (backoff *and* honored Retry-After): concurrent
            # siblings handed the same reset window must de-synchronise, else
            # they wake in lockstep and re-collide on the next window.
            delay += random.uniform(0.0, policy.jitter_seconds)
            if delay > remaining_budget:
                raise
            attempt += 1
            total_waited += delay
            logger.warning(
                "aigw upstream overload (status=%s); retry %d/%d after %.2fs",
                _status_code(exc),
                attempt,
                policy.max_retries,
                delay,
            )
            await sleep(delay)
