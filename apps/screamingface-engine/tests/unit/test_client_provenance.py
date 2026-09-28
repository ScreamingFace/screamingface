"""Caller-reported version evidence follows the ordinary ephemeral run stream."""

from collections.abc import AsyncIterator

import pytest

from screamingface_engine.client_provenance import ProvenanceExecutor, parse_user_agent
from screamingface_engine.testing import InMemoryEventStream
from url4.streaming.interfaces import ExecStep, Executor, TraceContext
from url4.streaming.lifecycle import run
from url4.streaming.protocol import LogData, LogEvent, StartedEvent, TerminatedEvent


@pytest.mark.parametrize("version", ["0.1.1.post8", "0.0.0+source", "9.8.7+local", "a" * 128])
def test_product_version_is_preserved(version: str) -> None:
    assert parse_user_agent(f"screamingface/{version}") == version
    assert parse_user_agent(f"other/1 screamingface/{version}") == version


@pytest.mark.parametrize(
    "header",
    [
        None,
        "",
        "python-httpx/1",
        "screamingface/",
        "screamingface/1/2",
        "screamingface/1 screamingface/2",
        "screamingface/1\n",
        "screamingface/é",
        "(screamingface/1)",
        "screamingface/" + "a" * 129,
        "x" * 512 + " screamingface/1",
        "screamingface/1;secret=value",
    ],
)
def test_unusable_headers_are_unknown_without_raising(header: str | None) -> None:
    assert parse_user_agent(header) is None


class _FailingExecutor(Executor):
    def __init__(self) -> None:
        self.closed = False

    async def execute(
        self, url4: str, *, trace: TraceContext | None = None
    ) -> AsyncIterator[ExecStep]:
        try:
            yield LogData.at("INFO", "inner evidence")
            raise ValueError("run failed")
        finally:
            self.closed = True


async def _frames(stream: InMemoryEventStream, topic: str) -> list:
    frames = []
    async for event in stream.subscribe(topic):
        frames.append(event)
        if isinstance(event, TerminatedEvent):
            break
    return frames


@pytest.mark.asyncio
async def test_evidence_is_sequenced_replayed_and_purged_even_when_execution_fails() -> None:
    stream = InMemoryEventStream()
    inner = _FailingExecutor()
    await run(stream, ProvenanceExecutor(inner, "0.0.0+source"), "topic", "'hi'")
    frames = await _frames(stream, "topic")
    assert isinstance(frames[0], StartedEvent)
    assert isinstance(frames[1], LogEvent)
    assert frames[1].data.attributes == {"screamingface.client.version": "0.0.0+source"}
    assert frames[1].subject == frames[0].subject
    assert frames[1].traceparent == frames[0].traceparent
    assert [int(event.sequence) for event in frames] == list(range(1, len(frames) + 1))
    assert frames[-1].data.status == "failed"
    assert inner.closed
    assert await _frames(stream, "topic") == frames
    await stream.purge("topic")
    await stream.publish("topic", frames[-1])
    assert len(await _frames(stream, "topic")) == 1


@pytest.mark.asyncio
async def test_unknown_version_does_not_add_an_event() -> None:
    stream = InMemoryEventStream()
    await run(stream, ProvenanceExecutor(_FailingExecutor(), None), "old-client", "'hi'")
    frames = await _frames(stream, "old-client")
    assert frames[1].data.body == "inner evidence"


@pytest.mark.asyncio
async def test_closing_the_wrapper_closes_inner_iteration() -> None:
    inner = _FailingExecutor()
    iterator = ProvenanceExecutor(inner, "1").execute("'hi'")
    await anext(iterator)
    await anext(iterator)
    await iterator.aclose()
    assert inner.closed
