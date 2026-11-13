"""Making a Run's owed stops: what a cancel and the Engine's driver both do (E5 P1 spec D12; E5 P2
spec R9).

FEATURE: a detached Run (OME-1837). `RunRegistry.stop` records the stop and owes one to every live
Candidate that has a topic; this makes them. `DELETE /runs/{id}` makes them at once and answers
with what failed; the driver's tick makes whatever is still owed.

INVARIANT: an obligation is cleared only after its stop succeeded, so a failed stop stays owed and
the next caller makes it again.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Sequence
from typing import Protocol

# How many of a Run's topics are stopped at once: each stop may wait on the runner's control asks,
# so one at a time would take N times as long; unbounded, a 256-Candidate Run would open 256 asks
# on the broker together.
STOP_CONCURRENCY = 16


class _StopsDone(Protocol):
    def stop_done(self, topic: str) -> Awaitable[None]: ...


async def make_stops(
    registry: _StopsDone,
    stop: Callable[[str], Awaitable[None]],
    topics: Sequence[str],
) -> list[tuple[str, Exception]]:
    """Stop each topic, `STOP_CONCURRENCY` at a time, and clear each obligation once its stop
    succeeded. Every stop is tried even when one fails; the failures are returned, in order. A
    cancellation is never swallowed."""
    gate = asyncio.Semaphore(STOP_CONCURRENCY)

    async def stop_one(topic: str) -> None:
        async with gate:
            await stop(topic)
        await registry.stop_done(topic)

    results = await asyncio.gather(*(stop_one(t) for t in topics), return_exceptions=True)
    failed: list[tuple[str, Exception]] = []
    for topic, result in zip(topics, results, strict=True):
        if isinstance(result, Exception):
            failed.append((topic, result))
        elif isinstance(result, BaseException):
            raise result
    return failed


__all__ = ["STOP_CONCURRENCY", "make_stops"]
