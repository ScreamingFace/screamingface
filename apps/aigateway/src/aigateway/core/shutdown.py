"""One shutdown close that a cancelled shutdown cannot cut short.

FEATURE: Router Recipe extension Unit 5.1 (contract C7) — the app-lifetime attempt handler and
the usage accounting handler each own a connection pool the lifespan closes.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Awaitable, Callable

# WHY a module set: the event loop keeps only a weak reference to a task no one awaits, and a
# close that a second cancellation left behind must still run to its end.
_UNFINISHED: set[asyncio.Future[None]] = set()


async def close_through_cancellation(
    close: Callable[[], Awaitable[None]], logger: logging.Logger, failure: str
) -> None:
    """Run ``close`` to its end in its own task; a failed close logs ``failure``.

    WHY: the shutdown drops a handler before it closes it, so a close cut short by a cancelled
    shutdown (a reload, a stopped server) would leave its pool open with no one left to close it.
    INVARIANT: a cancellation of the caller waits once more for the close, then is raised. A
    second cancellation stops that wait, so shutdown cannot hang, but never stops the close. A
    close that itself raises a cancellation is raised at once (``test_app_shutdown.py``).
    """
    closing = asyncio.ensure_future(close())
    try:
        await asyncio.shield(closing)
    except asyncio.CancelledError:
        if not closing.done():
            # WHY ``wait``: it neither cancels the close nor raises the close's own error.
            with contextlib.suppress(asyncio.CancelledError):
                await asyncio.wait({closing})
        _report_when_done(closing, logger, failure)
        raise
    except Exception:
        logger.warning(failure)


def _report_when_done(closing: asyncio.Future[None], logger: logging.Logger, failure: str) -> None:
    def report(done: asyncio.Future[None]) -> None:
        _UNFINISHED.discard(done)
        # WHY read the error here: no caller awaits it any more, and asyncio would print it.
        if not done.cancelled() and done.exception() is not None:
            logger.warning(failure)

    if closing.done():
        report(closing)
    else:
        _UNFINISHED.add(closing)
        closing.add_done_callback(report)
