"""Stage 6 of POST /v1/chat/completions: wait for the run's terminal frame.

The route scans the topic itself (contracts C9): the existing wait helper keeps only the result
and terminal frames, and this route also needs the root cost-usage frame. The scan races the
time limit, the caller leaving and the App drain; the first one to end the wait wins. The
streamed route polls a RunWait in steps instead, because it has no watch on the caller.
"""

from __future__ import annotations

import asyncio

from starlette.types import Receive

from screamingface_engine.rest.chat_cleanup import ChatCleanup
from screamingface_engine.rest.chat_drain import ChatDrain
from screamingface_engine.rest.chat_errors import ChatError, restart_retry_after
from screamingface_engine.rest.chat_frames import RunFrames, WaitEnd
from screamingface_engine.rest.chat_observe import RequestFacts
from url4.streaming.interfaces import EventConsumer
from url4.streaming.protocol import CostUsageEvent, ResultEvent, TerminatedEvent
from url4.streaming.protocol.signals import CostUsageData
from url4.streaming.trace import parse_traceparent

__all__ = ["WAIT_ROWS", "RunWait", "scan_run", "settle_wait", "wait_for_run"]

_ROOT_SCOPE = "subtree"
# INVARIANT: (HTTP status, body code, x-should-retry) of a wait that ended with no terminal frame.
WAIT_ROWS: dict[WaitEnd, tuple[int, str, bool]] = {
    WaitEnd.TIMEOUT: (504, "timeout", False),
    WaitEnd.DRAINED: (503, "server_restarting", True),
    # WHY: nobody reads this answer; the status only names the outcome in the metrics.
    WaitEnd.GONE: (499, "client_disconnected", False),
}


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


class RunWait:
    """The scan of one run raced against its time limit and the App drain, with no watch on the
    caller leaving.

    WHY no watch on receive(): the streamed answer runs inside Starlette's StreamingResponse, which
    already reads receive() for the disconnect; two readers of receive() lose messages.
    """

    def __init__(self, stream: EventConsumer, topic: str, bound_s: float, drain: ChatDrain) -> None:
        self._scan: asyncio.Future[RunFrames] = asyncio.ensure_future(
            asyncio.wait_for(scan_run(stream, topic), bound_s)
        )
        self._drained: asyncio.Future[None] = asyncio.ensure_future(drain.wait())

    async def next(self, every_s: float) -> RunFrames | WaitEnd | None:
        """The frames or why the wait ended; None when every_s passed first."""
        await asyncio.wait(
            (self._scan, self._drained), timeout=every_s, return_when=asyncio.FIRST_COMPLETED
        )
        if self._scan.done():
            return _scan_outcome(self._scan)
        return WaitEnd.DRAINED if self._drained.done() else None

    def cancel(self) -> None:
        """Cancel both tasks now; safe to call more than once and from a finally block."""
        for task in (self._scan, self._drained):
            task.cancel()

    async def close(self) -> None:
        """Cancel both tasks and wait until they end."""
        self.cancel()
        await asyncio.gather(self._scan, self._drained, return_exceptions=True)


def _scan_outcome(scan: asyncio.Future[RunFrames]) -> RunFrames | WaitEnd:
    """The frames, or TIMEOUT; any other error of the scan is raised again."""
    return WaitEnd.TIMEOUT if isinstance(scan.exception(), TimeoutError) else scan.result()


def _outcome(scan: asyncio.Future[RunFrames], gone: asyncio.Future[None]) -> RunFrames | WaitEnd:
    """The scan's frames or its time-out; a scan that did not end lost to the caller or the
    drain."""
    if not scan.cancelled():
        return _scan_outcome(scan)
    return WaitEnd.DRAINED if gone.cancelled() else WaitEnd.GONE


def settle_wait(ended: RunFrames | WaitEnd, cleanup: ChatCleanup, facts: RequestFacts) -> RunFrames:
    """The frames of a run that reached its terminal frame; the ChatError of a wait that ended
    first.

    INVARIANT: a terminal frame marks the cleanup finished, so the run is not stopped, and gives
    the trace id of the request line. The plain and the streamed answer both end their wait here.
    """
    if isinstance(ended, WaitEnd):
        status, code, should_retry = WAIT_ROWS[ended]
        raise ChatError(
            status,
            code,
            retry_after=restart_retry_after(status, should_retry),
            should_retry=should_retry,
        )
    cleanup.finished = True
    facts.trace_id = parse_traceparent(ended.terminated.traceparent) or facts.trace_id
    return ended
