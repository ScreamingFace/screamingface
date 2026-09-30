"""One send-and-settle loop for the sync and async twins of a re-sendable request.

WHY a driver and not a loop at each call site: the part that differs between a sync and an async
caller is only `await`. The decision (done, or send again after how long) is a pure function the
caller supplies, so the twins cannot drift and the decision is testable without a clock or a
socket. Same idiom as `_RetryPlan` in `retry.py`.

INVARIANT: this module sees `httpx` only. It knows no SDK error, no status table and no policy.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

import httpx


@dataclass(frozen=True, slots=True)
class _Again:
    """Send once more. `delay` is the seconds to wait first; `None` means send at once."""

    delay: float | None


@dataclass(frozen=True, slots=True)
class _Done[T]:
    value: T


type _Step[T] = _Done[T] | _Again
type _Attempt = httpx.Response | Exception


def drive_sync[T](
    send: Callable[[], httpx.Response],
    settle: Callable[[int, _Attempt], _Step[T]],
    sleep: Callable[[float], object],
    catch: tuple[type[Exception], ...],
) -> T:
    """Send, hand the response or the caught error to `settle`, and send again when it says so.

    `settle` is pure: it returns the next step, or raises the terminal error itself. `attempt` is
    the number of attempts already settled, so the first call sees 0. An exception that is not in
    `catch` leaves the loop untouched.
    """
    attempt = 0
    while True:
        try:
            outcome: _Attempt = send()
        except catch as exc:
            outcome = exc
        step = settle(attempt, outcome)
        if isinstance(step, _Done):
            return step.value
        attempt += 1
        if step.delay is not None:
            sleep(step.delay)


async def drive_async[T](
    send: Callable[[], Awaitable[httpx.Response]],
    settle: Callable[[int, _Attempt], _Step[T]],
    sleep: Callable[[float], Awaitable[None]],
    catch: tuple[type[Exception], ...],
) -> T:
    """Async twin of `drive_sync`."""
    attempt = 0
    while True:
        try:
            outcome: _Attempt = await send()
        except catch as exc:
            outcome = exc
        step = settle(attempt, outcome)
        if isinstance(step, _Done):
            return step.value
        attempt += 1
        if step.delay is not None:
            await sleep(step.delay)


__all__: list[str] = []
