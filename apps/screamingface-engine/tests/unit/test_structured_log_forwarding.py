"""Generic endpoint activity survives real Engine execution and wire publication."""

import asyncio

import pytest

from screamingface_engine.runner.executor import Url4Executor, _log_frame
from screamingface_engine.testing import InMemoryEventStream
from url4.io.static import StaticIOLayer
from url4.observe import Log, current_log_sink
from url4.streaming.interfaces import Completed, Traced
from url4.streaming.lifecycle import run as publish_run
from url4.streaming.protocol import LogData, LogEvent, SpanEvent, TerminatedEvent


@pytest.mark.parametrize("severity", ["DEBUG", "INFO", "WARN", "ERROR", "custom"])
def test_conversion_preserves_attributes_and_existing_severity_fallback(severity):
    attributes = {"count": 2, "duration": 1.25, "ok": True, "unknown": None, "text": "x"}
    frame = _log_frame(Log("a" * 16, severity, "activity", attributes))
    assert frame.attributes == attributes
    assert frame.severity_text == (severity if severity != "custom" else "INFO")
    assert _log_frame(Log(None, severity, "old style")).attributes == {}


async def _published_activity(marker):
    attrs = {"marker": marker, "count": 2, "ok": True, "unknown": None}

    async def endpoint(context, intent):
        sink = current_log_sink()
        assert sink is not None
        sink("operation activity", attrs, severity="WARN")
        attrs["count"] = 99
        return "finished"

    stream = InMemoryEventStream()
    await publish_run(
        stream,
        Url4Executor(StaticIOLayer(routes={"/operation": endpoint})),
        marker,
        "/operation()!go",
    )
    frames = []
    async for frame in stream.subscribe(marker, from_sequence=1):
        frames.append(frame)
        if isinstance(frame, TerminatedEvent):
            break
    return frames


@pytest.mark.asyncio
async def test_concurrent_endpoint_logs_keep_attributes_node_attachment_and_wire_order():
    runs = await asyncio.gather(_published_activity("one"), _published_activity("two"))
    traceparents = []
    for marker, frames in zip(("one", "two"), runs, strict=True):
        logs = [
            f for f in frames if isinstance(f, LogEvent) and f.data.body == "operation activity"
        ]
        assert len(logs) == 1
        log = logs[0]
        assert log.data.attributes == {"marker": marker, "count": 2, "ok": True, "unknown": None}
        assert log.data.severity_text == "WARN"
        assert LogEvent.model_validate_json(log.model_dump_json()) == log
        assert any(isinstance(f, SpanEvent) and f.traceparent == log.traceparent for f in frames)
        assert [int(f.sequence) for f in frames] == list(range(1, len(frames) + 1))
        assert frames[-1].data.status == "succeeded"
        traceparents.append(log.traceparent)
    assert traceparents[0] != traceparents[1]


@pytest.mark.asyncio
async def test_activity_streams_before_endpoint_completion():
    release = asyncio.Event()

    async def endpoint(context, intent):
        sink = current_log_sink()
        assert sink is not None
        sink("waiting", {"elapsed_seconds": 30})
        await release.wait()
        return "finished"

    executor = Url4Executor(StaticIOLayer(routes={"/operation": endpoint}))
    steps = executor.execute("/operation()!go")
    first = None
    try:
        async with asyncio.timeout(2):
            async for first in steps:
                if isinstance(first, Traced) and isinstance(first.payload, LogData):
                    break
        assert isinstance(first, Traced) and isinstance(first.payload, LogData)
        assert first.payload.body == "waiting"
        assert first.payload.attributes == {"elapsed_seconds": 30}
        assert first.span is not None
        assert not release.is_set()
    finally:
        release.set()
        rest = [step async for step in steps]
    assert isinstance(rest[-1], Completed)
    assert rest[-1].result.body == "finished"


@pytest.mark.asyncio
async def test_existing_client_decodes_real_serialized_engine_lifecycle():
    # WHY: protocol model round-trips alone cannot prove the independent Client accepts it.
    import os
    import subprocess
    import sys
    from pathlib import Path

    frames = await _published_activity("client")
    client_src = Path(__file__).resolve().parents[4] / "packages/screamingface/src"
    script = """
import sys
from screamingface._engine.contract import _RunState
from screamingface.events import Log
state = _RunState("/operation()!go")
logs = []
for line in sys.stdin:
    accepted = state.accept(line)
    if isinstance(accepted.event, Log) and accepted.event.body == "operation activity":
        logs.append(accepted.event)
assert len(logs) == 1
assert logs[0].attributes == {"marker": "client", "count": 2, "ok": True, "unknown": None}
assert logs[0].traceparent
assert accepted.outcome is not None
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        input="\n".join(frame.model_dump_json(by_alias=True) for frame in frames),
        text=True,
        capture_output=True,
        timeout=15,
        env={**os.environ, "PYTHONPATH": str(client_src)},
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("soft,hard", [(2, 8), (8, 8), (100, 8)])
@pytest.mark.parametrize("fails", [False, True])
@pytest.mark.asyncio
async def test_real_endpoint_lifecycle_is_unchanged_by_log_pressure(soft, hard, fails):
    from screamingface_engine.runner.executor import EVENT_SIZE_ESTIMATE_BYTES
    from url4.core.errors import ResolutionError
    from url4.streaming.protocol import ResultEvent

    outcomes = []
    for noisy in (False, True):

        async def endpoint(context, intent):
            sink = current_log_sink()
            assert sink is not None
            if noisy:
                for i in range(40):
                    sink("optional burst", {"index": i})
            if fails:
                raise ResolutionError("original endpoint error")
            return "finished"

        executor = Url4Executor(
            StaticIOLayer(routes={"/operation": endpoint}),
            queue_cap=soft,
            memory_budget=hard * EVENT_SIZE_ESTIMATE_BYTES,
        )
        stream = InMemoryEventStream()
        await publish_run(stream, executor, "pressure", "/operation()!go")
        frames = []
        async for frame in stream.subscribe("pressure", from_sequence=1):
            frames.append(frame)
            if isinstance(frame, TerminatedEvent):
                break
        delivered = sum(isinstance(f, LogEvent) and f.data.body == "optional burst" for f in frames)
        summary = executor.last_summary()
        assert summary is not None
        assert summary.dropped_logs == (40 if noisy else 0) - delivered
        assert summary.high_water <= hard
        outcomes.append(
            (
                frames[-1].data.model_dump(),
                [f.data.model_dump() for f in frames if isinstance(f, ResultEvent)],
                [(f.data.name, f.data.status) for f in frames if isinstance(f, SpanEvent)],
            )
        )
    assert outcomes[0] == outcomes[1]
    assert outcomes[0][0]["status"] == ("failed" if fails else "succeeded")
