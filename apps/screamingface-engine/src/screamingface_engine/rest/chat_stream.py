"""The streamed answer of POST /v1/chat/completions (U5, prd/streaming.md).

FEATURE: OpenAI-compatible Engine API, unit U5. The stream is buffered (owner decision): the
route answers 200 `text/event-stream` at once, sends a keep-alive comment each
`chat_keepalive_s` while the run works, and then sends the whole answer as chunks
(`chat.sse.frames`). An error after the start is one error event and no `[DONE]` (ST-S6).

INVARIANT: one reader of receive(). Starlette's StreamingResponse watches the disconnect, so this
module never reads receive() and never starts the watcher of `rest.chat_wait.wait_for_run`.

AIDEV-NOTE: a disconnect cancels the stream at once only on an ASGI spec 2.3 server (uvicorn
with h11 or httptools today), where StreamingResponse watches receive(). On an ASGI 2.4 server
Starlette sees the disconnect only at the next write, so the run can stop up to
`chat_keepalive_s` late.

INVARIANT: once the response exists, it owns the cleanup of its request. Its `__call__` runs the
cleanup and the observation on every exit, also when the body never started.
"""

from __future__ import annotations

import logging
import time
from collections.abc import AsyncGenerator, Callable
from dataclasses import dataclass

from starlette.responses import StreamingResponse
from starlette.types import Receive, Scope, Send

from screamingface_engine.artifacts.ports import ArtifactReader
from screamingface_engine.chat.sse import KEEP_ALIVE, ChunkMeta, error_event, frames
from screamingface_engine.rest.chat_answer import completion_id, completion_parts, read_result
from screamingface_engine.rest.chat_cleanup import ChatCleanup
from screamingface_engine.rest.chat_drain import ChatDrain
from screamingface_engine.rest.chat_errors import ChatError, error_type
from screamingface_engine.rest.chat_frames import RunFrames, WaitEnd
from screamingface_engine.rest.chat_observe import RequestFacts
from screamingface_engine.rest.chat_wait import WAIT_ROWS, RunWait, settle_wait
from url4.streaming.interfaces import EventConsumer

__all__ = ["STREAM_HEADERS", "ChatStream", "ChatStreamResponse", "StreamPlan", "stream_answer"]

_logger = logging.getLogger(__name__)

STREAM_HEADERS: dict[str, str] = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
_MEDIA_TYPE = "text/event-stream"
# INVARIANT: the outcome of a stream that ended before its last line was taken.
_DISCONNECTED = WAIT_ROWS[WaitEnd.GONE][1]
_STATUS = 200

Finish = Callable[[str, int], None]


@dataclass(frozen=True)
class StreamPlan:
    """What the stream of one request needs after its run is scheduled."""

    events: EventConsumer
    topic: str
    model: str
    include_usage: bool
    max_wait_s: float
    keepalive_s: float
    drain: ChatDrain
    artifacts: ArtifactReader | None


class ChatStream:
    """The lines of one streamed answer, and the end of its request."""

    def __init__(self, plan: StreamPlan, cleanup: ChatCleanup, facts: RequestFacts) -> None:
        self._plan, self._cleanup, self._facts = plan, cleanup, facts
        self._wait: RunWait | None = None
        self.outcome = _DISCONNECTED

    async def events(self) -> AsyncGenerator[bytes]:
        """Keep-alive comments while the run works, then the answer or one error event."""
        plan = self._plan
        # WHY here and not in __init__: a body that never starts owns no task.
        wait = self._wait = RunWait(plan.events, plan.topic, plan.max_wait_s, plan.drain)
        try:
            step = await self._step(wait)
            while step is None:
                yield KEEP_ALIVE
                step = await self._step(wait)
            lines, outcome = step
            for line in lines:
                yield line
            # INVARIANT: the outcome is set only after the client took the last line.
            self.outcome = outcome
        finally:
            await wait.close()

    async def end(self, on_end: Finish | None) -> None:
        """Stop the wait, run the cleanup, then count and log the request once."""
        if self._wait is not None:
            self._wait.cancel()
        try:
            await self._cleanup.run()
        finally:
            if on_end is not None:
                on_end(self.outcome, _STATUS)

    async def _step(self, wait: RunWait) -> tuple[list[bytes], str] | None:
        """None while the run works; else the lines that end the stream and the outcome."""
        try:
            ended = await wait.next(self._plan.keepalive_s)
            step = None if ended is None else (await self._answer_lines(ended), "ok")
        except ChatError as exc:
            step = [error_event(exc.message, error_type(exc.status), exc.code)], exc.code
        # WHY: the stream already started, so an error that no stage expected still ends it with
        # the error event. Only the class name is logged, as the message can quote a request or a
        # provider. A cancel is a BaseException and passes.
        except Exception as exc:
            _logger.error(
                "chat stream failed trace_id=%s: %s",
                self._facts.trace_id or "-",
                type(exc).__name__,
            )
            failed = ChatError(500, "internal_error")
            step = [error_event(failed.message, error_type(500), failed.code)], failed.code
        return step

    async def _answer_lines(self, ended: RunFrames | WaitEnd) -> list[bytes]:
        """The answer as data lines ending with [DONE]; the ChatError of a run that failed."""
        settled = settle_wait(ended, self._cleanup, self._facts)
        plan = self._plan
        result = await read_result(settled, plan.artifacts)
        usage, info = completion_parts(result, settled)
        meta = ChunkMeta(id=completion_id(), created=int(time.time()), model=plan.model)
        return frames(result, meta, info, usage if plan.include_usage else None)


class ChatStreamResponse(StreamingResponse):
    """The 200 event stream of one request; it runs the end of its request on every exit."""

    def __init__(self, chat: ChatStream) -> None:
        self._chat = chat
        self._lines = chat.events()
        # WHY: the route sets it; it counts and logs the request once, at the end of the stream.
        self.on_end: Finish | None = None
        super().__init__(self._lines, media_type=_MEDIA_TYPE, headers=STREAM_HEADERS)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        try:
            await super().__call__(scope, receive, send)
        finally:
            try:
                await self._chat.end(self.on_end)
            finally:
                # WHY: a body cut at a yield stays open until the loop collects it; close it now
                # so its wait is reaped with the request.
                await self._lines.aclose()


def stream_answer(
    plan: StreamPlan, cleanup: ChatCleanup, facts: RequestFacts
) -> ChatStreamResponse:
    """The streamed answer of a scheduled run; it owns the cleanup from now on."""
    return ChatStreamResponse(ChatStream(plan, cleanup, facts))
