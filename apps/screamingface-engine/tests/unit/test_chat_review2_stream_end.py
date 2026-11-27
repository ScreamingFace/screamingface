"""Tests of the end of a streamed answer (review round 2, findings F4 and F5).

F4: end() stops the task that reads the result before the cleanup runs, so a client that leaves
does not keep the read going during the stop and the delete. F5: the streamed route awaits the
end of its run once, with RunWait.ended(), and does not poll in steps.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Any, cast

import pytest
from _chat_app import cost_frame, result_frame, terminated_frame

from screamingface_engine.artifacts.ports import ArtifactContent, RemoteStream
from screamingface_engine.chat.sse import KEEP_ALIVE
from screamingface_engine.rest.chat_drain import ChatDrain
from screamingface_engine.rest.chat_frames import RunFrames, WaitEnd
from screamingface_engine.rest.chat_observe import RequestFacts
from screamingface_engine.rest.chat_stream import ChatStream, StreamPlan
from screamingface_engine.rest.chat_wait import RunWait
from screamingface_engine.testing import InMemoryEventStream
from url4.streaming.protocol.signals import ResultArtifact

pytestmark = pytest.mark.asyncio

ARTIFACT = ResultArtifact(id="ab" * 32, size_bytes=10, sha256="ab" * 32)


class _StuckRead:
    """A result store whose remote stream never gives its first chunk."""

    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.closed = False

    async def _chunks(self) -> AsyncIterator[bytes]:
        try:
            self.started.set()
            await asyncio.Event().wait()
            yield b""
        finally:
            self.closed = True

    def content(self, artifact_id: str) -> ArtifactContent | None:
        return RemoteStream(stream=self._chunks(), size_bytes=10)

    def delete(self, artifact_id: str) -> None:
        return None

    def sweep(self, ttl_seconds: float, *, now: float | None = None) -> int:
        return 0


class _Cleanup:
    """A cleanup that notes if the result read was closed when it started."""

    def __init__(self, store: _StuckRead) -> None:
        self._store = store
        self.finished = False
        self.closed_at_run: bool | None = None

    async def run(self) -> None:
        self.closed_at_run = self._store.closed


async def _ended_stream(topic: str) -> InMemoryEventStream:
    stream = InMemoryEventStream()
    await stream.publish(topic, cost_frame(topic))
    await stream.publish(topic, result_frame(topic, artifact=ARTIFACT))
    await stream.publish(topic, terminated_frame(topic))
    return stream


async def test_end_cancels_the_prepare_task_before_the_cleanup() -> None:
    store = _StuckRead()
    plan = StreamPlan(
        events=await _ended_stream("t1"),
        topic="t1",
        model="m",
        include_usage=False,
        max_wait_s=5.0,
        keepalive_s=0.01,
        drain=ChatDrain(),
        artifacts=store,
    )
    cleanup = _Cleanup(store)
    chat = ChatStream(plan, cast(Any, cleanup), RequestFacts())
    gen = chat.events()
    try:
        assert await anext(gen) == KEEP_ALIVE
        # WHY: the prepare task must be in the remote read before the client leaves.
        while not store.started.is_set():
            assert await anext(gen) == KEEP_ALIVE
        await chat.end(None)
        assert cleanup.closed_at_run is True
    finally:
        await gen.aclose()


async def test_prepare_awaits_the_run_end_with_one_wait() -> None:
    wait = RunWait(await _ended_stream("t1"), "t1", 5.0, ChatDrain())
    try:
        assert isinstance(await wait.ended(), RunFrames)
    finally:
        await wait.close()

    drain = ChatDrain()
    drain.request()
    wait = RunWait(InMemoryEventStream(), "t1", 5.0, drain)
    try:
        assert await wait.ended() is WaitEnd.DRAINED
    finally:
        await wait.close()
