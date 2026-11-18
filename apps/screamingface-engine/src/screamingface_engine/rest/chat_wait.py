"""Stage 6 of POST /v1/chat/completions: wait for the run's terminal frame.

The route scans the topic itself (contracts C9): the existing wait helper keeps only the result
and terminal frames, and this route also needs the root cost-usage frame. The scan races the
time limit, the caller leaving and the App drain; the first one to end the wait wins.
"""

from __future__ import annotations

import asyncio

from starlette.types import Receive

from screamingface_engine.rest.chat_drain import ChatDrain
from screamingface_engine.rest.chat_frames import RunFrames, WaitEnd
from url4.streaming.interfaces import EventConsumer
from url4.streaming.protocol import CostUsageEvent, ResultEvent, TerminatedEvent
from url4.streaming.protocol.signals import CostUsageData

__all__ = ["scan_run", "wait_for_run"]

_ROOT_SCOPE = "subtree"


async def scan_run(stream: EventConsumer, topic: str) -> RunFrames:
    """Read the topic from its start to the terminal frame, keeping the last result frame and
    the last root cost-usage frame (scope "subtree")."""
    result: ResultEvent | None = None
    root_cost: CostUsageData | None = None
    async for event in stream.subscribe(topic, from_sequence=None):
        if isinstance(event, ResultEvent):
            result = event
        elif isinstance(event, CostUsageEvent) and event.data.scope == _ROOT_SCOPE:
            root_cost = event.data
        elif isinstance(event, TerminatedEvent):
            return RunFrames(terminated=event, result=result, root_cost=root_cost)
    # AIDEV-NOTE: an EventConsumer stream always ends in a terminal frame (spec §5).
    raise RuntimeError("stream ended before a terminal frame")


async def wait_for_run(
    stream: EventConsumer,
    topic: str,
    bound_s: float,
    receive: Receive,
    drain: ChatDrain,
) -> RunFrames | WaitEnd:
    """The run's frames, or why the wait ended first. Each helper task is reaped on every exit.

    `receive` is the ASGI receive of the request, whose body was read in full before the wait.
    """
    scan = asyncio.ensure_future(asyncio.wait_for(scan_run(stream, topic), bound_s))
    gone = asyncio.ensure_future(_disconnected(receive))
    drained = asyncio.ensure_future(drain.wait())
    tasks = (scan, gone, drained)
    try:
        # WHY a watch task on receive() and no Request.is_disconnected() poll: is_disconnected()
        # opens an anyio cancel scope, and a cancel of the request task that lands inside that
        # scope is swallowed (review F4). Here the request task awaits only asyncio.wait, which
        # passes each cancel on; the finally below then cancels and awaits each helper task.
        await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
    return _outcome(scan, gone)


async def _disconnected(receive: Receive) -> None:
    """Return when the client is gone: the body is read, so the next message is the disconnect."""
    while (await receive())["type"] != "http.disconnect":
        pass


def _outcome(scan: asyncio.Future[RunFrames], gone: asyncio.Future[None]) -> RunFrames | WaitEnd:
    """The scan's frames or its time-out; a scan that did not end lost to the caller or the
    drain."""
    if not scan.cancelled():
        return WaitEnd.TIMEOUT if isinstance(scan.exception(), TimeoutError) else scan.result()
    return WaitEnd.DRAINED if gone.cancelled() else WaitEnd.GONE
