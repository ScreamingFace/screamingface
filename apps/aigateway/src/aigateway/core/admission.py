"""Independent provider admission and execution budgets (OME-886).

Engine declares budgets in headers, never provider parameters. Callers can shorten
operator limits, not raise them. Logs inherit the existing call/trace scope.
"""

from __future__ import annotations

import asyncio
import logging
import math
import time
from collections.abc import Awaitable, Callable
from typing import Any, cast

from fastapi import HTTPException, Request

from .concurrency import effective_provider_limit, provider_slot

logger = logging.getLogger(__name__)
EXECUTION_HEADER = "x-aigw-execution-timeout-s"
QUEUE_HEADER = "x-aigw-queue-timeout-s"
REMAINING_HEADER = "x-aigw-remaining-timeout-s"


class ProviderExecutionTimeout(HTTPException):
    """Safe wire error retaining timeout identity for attempt accounting."""

    def __init__(self) -> None:
        # Accounting classifies transport failures by exception type. A plain
        # HTTPException would erase timeout evidence before the route finalizes it.
        super().__init__(
            status_code=504,
            detail={
                "code": "provider_execution_timeout",
                "message": "Provider execution timed out.",
            },
        )


def _budget(request: Request, header: str, maximum: float) -> float:
    raw = request.headers.get(header)
    if raw is None:
        return maximum
    try:
        value = float(raw)
    except ValueError:
        value = float("nan")
    if not math.isfinite(value) or value <= 0:
        raise HTTPException(
            400,
            detail={
                "code": "invalid_timeout_budget",
                "message": "Timeout budgets must be finite and positive.",
            },
        )
    return min(value, maximum)


def _timeout(code: str, message: str) -> HTTPException:
    return HTTPException(
        503 if code == "provider_queue_timeout" else 504,
        detail={"code": code, "message": message},
        headers={"Retry-After": "1"} if code == "provider_queue_timeout" else None,
    )


def _check_caller_deadline(overall: asyncio.Timeout) -> None:
    # WHY: acquiring capacity can beat an overdue timer callback. The caller's
    # deadline must still prevent dispatch and classify an expired waiter correctly.
    deadline = overall.when()
    if deadline is not None and asyncio.get_running_loop().time() >= deadline:
        raise _timeout("caller_deadline_exceeded", "The caller's request budget expired.")


async def _dispatch(request: Request, provider: str, call: Callable[[], Awaitable[Any]]) -> Any:
    settings = request.app.state.settings
    execution = _budget(request, EXECUTION_HEADER, settings.provider_execution_timeout_s)
    queue = _budget(request, QUEUE_HEADER, settings.provider_queue_timeout_s or execution)
    # Only an explicit caller deadline wraps both phases. Otherwise their independent
    # timers determine the error, even when admission consumes its entire allowance.
    remaining = (
        _budget(request, REMAINING_HEADER, queue + execution)
        if REMAINING_HEADER in request.headers
        else None
    )
    limit = effective_provider_limit(settings, provider)
    started = time.monotonic()
    admitted: float | None = None
    outcome = "error"
    try:
        async with asyncio.timeout(remaining) as overall:
            try:
                async with provider_slot(request.app, provider, limit, timeout_s=queue):
                    _check_caller_deadline(overall)
                    admitted = time.monotonic()
                    async with asyncio.timeout(execution):
                        result = await call()
                    outcome = "success"
                    return result
            except TimeoutError:
                if overall.expired():
                    raise
                _check_caller_deadline(overall)
                if admitted is None:
                    raise _timeout(
                        "provider_queue_timeout", "Timed out waiting for provider capacity."
                    ) from None
                raise ProviderExecutionTimeout() from None
    except TimeoutError:
        outcome = "caller_deadline_exceeded"
        raise _timeout(outcome, "The caller's request budget expired.") from None
    except HTTPException as exc:
        detail = exc.detail
        if isinstance(detail, dict) and detail.get("code") in {
            "provider_queue_timeout",
            "provider_execution_timeout",
            "caller_deadline_exceeded",
        }:
            outcome = cast(dict[str, str], detail)["code"]
        raise
    except asyncio.CancelledError:
        outcome = "cancelled"
        raise
    finally:
        ended = time.monotonic()
        queue_ms = ((admitted if admitted is not None else ended) - started) * 1000
        execution_ms = (ended - admitted) * 1000 if admitted is not None else 0.0
        logger.info(
            "provider call finished provider=%s limit=%d queue_wait_ms=%.3f "
            "provider_execution_ms=%.3f outcome=%s",
            provider,
            limit,
            queue_ms,
            execution_ms,
            outcome,
            extra={
                "provider": provider,
                "provider_concurrency_limit": limit,
                "queue_wait_ms": queue_ms,
                "provider_execution_ms": execution_ms,
                "outcome": outcome,
            },
        )


async def dispatch_with_budgets(
    request: Request, provider: str, call: Callable[[], Awaitable[Any]]
) -> Any:
    """Cancel on disconnect; ASGI does not automatically cancel request handlers.

    The non-streaming route has consumed the complete request body before dispatch.
    """

    work = asyncio.current_task()
    assert work is not None
    request.state.provider_disconnect_cancelled = False

    async def disconnected() -> None:
        while True:
            message = await request.receive()
            if message["type"] == "http.disconnect":
                # INVARIANT: cancel at observation, before a queued semaphore
                # wakeup can dispatch. A separate coordinating task is too late.
                request.state.provider_disconnect_cancelled = True
                work.cancel()
                return

    disconnect = asyncio.create_task(disconnected())
    try:
        # WHY: dispatch in the request task so caller cancellation reaches
        # semaphore.acquire directly, without a child-task scheduling gap.
        return await _dispatch(request, provider, call)
    finally:
        disconnect.cancel()
        await asyncio.gather(disconnect, return_exceptions=True)
