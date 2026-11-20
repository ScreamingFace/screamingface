"""Race a wait against the disconnect of the caller (PRD 02 §4).

FEATURE: the sync `GET /?q=` and the mount calls hold a request until the run ends. A caller that
is gone must release that hold promptly, so a poll task watches the connection during the wait.

WHY a module of its own: the poll calls code that the Engine does not own (the disconnect check
of the ASGI server), and that code can swallow a cancel. The rules that keep the wait bounded
are here, in one place, and `rest/routes.py` only says what to wait for.
"""

import asyncio
import logging
from collections.abc import Awaitable, Callable, Coroutine
from typing import Any

_logger = logging.getLogger(__name__)

DISCONNECT_POLL_S = 0.5
"""How often a sync wait checks that its caller is still connected (PRD 02 §4: the hold is
released within 1 s of a disconnect)."""

_REAP_CANCELS = 4
_REAP_ROUND_S = 0.25
"""The reap of the poll task: at most `_REAP_CANCELS` cancels, each followed by a wait of at
most `_REAP_ROUND_S`. A poll that honours a cancel ends in one event-loop turn."""

WAIT_GONE = object()
"""`first_or_gone`'s answer when the caller disconnected first."""


async def _until_disconnected(
    is_disconnected: Callable[[], Awaitable[bool]], released: asyncio.Event
) -> None:
    while not await is_disconnected():
        # WHY: Starlette's `Request.is_disconnected` awaits `receive()` in an
        # `anyio.CancelScope` that is already cancelled. A cancel of this task that arrives in
        # that scope is swallowed when the scope exits: the check answers False and no
        # `CancelledError` is raised here. `released` tells this loop that the wait is over.
        if released.is_set():
            return
        await asyncio.sleep(DISCONNECT_POLL_S)


def _retrieve_exception(task: asyncio.Future[Any]) -> None:
    # WHY: a task that failed and that nobody awaited makes asyncio log "Task exception was
    # never retrieved". An exit that does not await the task to its end must stay silent too.
    if not task.cancelled():
        task.exception()


async def _reap_poll(gone: asyncio.Future[None]) -> None:
    """Cancel the poll task and wait for its end, for a bounded time.

    INVARIANT: this returns in at most `_REAP_CANCELS * _REAP_ROUND_S` seconds.
    WHY bounded: the poll awaits a callable that the Engine does not own. One that swallows a
    cancel and does not return would hold the request open after the run ended, and in a test
    (no disconnect) the test would not end. WHY more than one cancel: a callable that swallows
    one cancel ends on the next one.
    """
    for _ in range(_REAP_CANCELS):
        if gone.done():
            return
        gone.cancel()
        await asyncio.wait({gone}, timeout=_REAP_ROUND_S)
    if not gone.done():
        # The task is abandoned, not leaked for ever: it ends when the disconnect check returns,
        # because `released` is set.
        _logger.warning(
            "the disconnect check ignored %d cancels; the wait continues without it",
            _REAP_CANCELS,
        )


async def first_or_gone[T](
    work: Coroutine[Any, Any, T], is_disconnected: Callable[[], Awaitable[bool]]
) -> T | object:
    """Race `work` against the caller leaving: the result of `work`, or `WAIT_GONE`.

    INVARIANT: both tasks are cancelled on every exit, the poll task is reaped in bounded time,
    and a cancel of the calling task is passed on. A second cancel of the calling task ends
    the reap at once: the two tasks have their cancel and end by themselves.
    """
    released = asyncio.Event()
    wait = asyncio.ensure_future(work)
    gone = asyncio.ensure_future(_until_disconnected(is_disconnected, released))
    for task in (wait, gone):
        task.add_done_callback(_retrieve_exception)
    try:
        await asyncio.wait({wait, gone}, return_when=asyncio.FIRST_COMPLETED)
    finally:
        released.set()
        wait.cancel()
        await _reap_poll(gone)
        # WHY no bound here: `work` is Engine code. It honours a cancel, and its cleanup (the
        # stream subscription) must be complete before the handler answers.
        await asyncio.gather(wait, return_exceptions=True)
    if wait.cancelled():
        return WAIT_GONE
    return wait.result()
