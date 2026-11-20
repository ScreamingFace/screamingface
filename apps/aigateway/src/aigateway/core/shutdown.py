"""One shutdown close that a cancelled shutdown cannot cut short.

FEATURE: Router Recipe extension Unit 5.1 (contract C7) — the app-lifetime attempt handler and
the usage accounting handler each own a connection pool the lifespan closes.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable


async def close_through_cancellation(
    close: Callable[[], Awaitable[None]], logger: logging.Logger, failure: str
) -> None:
    """Run ``close`` to its end in its own task; a failed close logs ``failure``.

    WHY: the shutdown drops a handler before it closes it, so a close cut short by a cancelled
    shutdown (a reload, a stopped server) would leave its pool open with no one left to close it.
    INVARIANT: every cancellation of the caller waits for the close to end, then the first one is
    raised. Only the end of the event loop itself (a second Ctrl+C, a killed process) can stop
    the close, and no cancellation of this wait is that. A close that itself raises a
    cancellation is raised at once (``test_app_shutdown.py``).
    WHY not hand the close to a detached task after a second cancellation: the loop cancels
    every pending task when it ends, which follows a cancelled shutdown at once.
    """
    closing = asyncio.ensure_future(close())
    cancelled: asyncio.CancelledError | None = None
    while not closing.done():
        try:
            # WHY ``wait``: it neither cancels the close nor raises the close's own error.
            await asyncio.wait({closing})
        except asyncio.CancelledError as error:
            cancelled = cancelled or error
    try:
        closing.result()
    except Exception:
        logger.warning(failure)
    if cancelled is not None:
        raise cancelled
