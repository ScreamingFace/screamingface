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
    INVARIANT: delivered shutdown cancellations are deferred until the close completes, then the
    first one is raised. Only external process termination (such as SIGKILL) can stop an
    unfinished close. Under Uvicorn a second Ctrl+C only sets ``force_exit``, which the server no
    longer reads once its lifespan shutdown has begun, so it does not. A close that itself raises
    a cancellation is raised at once (``test_app_shutdown.py``).
    WHY no timeout: the owner chose a close that always ends; a bounded close is another contract.
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
