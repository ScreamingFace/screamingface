import asyncio
import re
from datetime import UTC, datetime

import httpx
import pytest
from _fakes import FixedGate, RecordingJobRunner, ScheduledRun
from fastapi import FastAPI
from httpx import ASGITransport

from screamingface_engine.app import create_app
from screamingface_engine.auth import JwtCodec
from screamingface_engine.config import Settings
from screamingface_engine.runner.executor import Url4Executor
from screamingface_engine.testing import InMemoryEventStream
from screamingface_engine.testing.mock_runner import build_run
from url4.io.static import StaticIOLayer
from url4.streaming.lifecycle import run as publish_run
from url4.streaming.protocol import (
    OutboundFrame,
    ResultEvent,
    SpanEvent,
    StartedEvent,
    TerminatedEvent,
)

_TP_RE = re.compile(r"^00-([0-9a-f]{32})-([0-9a-f]{16})-01$")

SECRET = "traceparent-unit-secret"
WINDOW_S = 60
LIFETIME_S = 58_800  # capability_lifetime_s (D1, OME-1016)
T0 = datetime(2026, 7, 21, 9, 0, 0, tzinfo=UTC)


async def _collect(stream: InMemoryEventStream, topic: str) -> list[OutboundFrame]:
    frames: list[OutboundFrame] = []

    async def _run() -> None:
        async for frame in stream.subscribe(topic, from_sequence=1):
            frames.append(frame)
            if isinstance(frame, TerminatedEvent):
                return

    await asyncio.wait_for(_run(), timeout=2.0)
    return frames


def _edge_shape(spans: list[SpanEvent]) -> list[str | None]:
    root = next(f for f in spans if f.tracestate is None)
    root_span_id = _TP_RE.match(root.traceparent).group(2)  # type: ignore[union-attr]
    shape: list[str | None] = []
    for f in spans:
        if f.tracestate is None:
            shape.append(None)
        else:
            parent_id = f.tracestate.removeprefix("url4.parent=")
            shape.append("root" if parent_id == root_span_id else parent_id)
    return sorted(shape, key=lambda x: (x is not None, x))


@pytest.mark.asyncio
async def test_every_frame_traceparent_matches_w3c_and_shares_one_trace_id() -> None:
    io = StaticIOLayer(fetch_map={"https://a": "A"})
    stream = InMemoryEventStream()
    topic = "trace-topic-1"

    await publish_run(stream, Url4Executor(io), topic, "https://a!go")
    frames = await _collect(stream, topic)

    trace_ids = set()
    for frame in frames:
        match = _TP_RE.match(frame.traceparent)  # type: ignore[arg-type]
        assert match is not None, frame
        trace_ids.add(match.group(1))
    assert len(trace_ids) == 1


@pytest.mark.asyncio
async def test_span_tracestate_and_non_span_tracestate_none() -> None:
    io = StaticIOLayer(fetch_map={"https://x": "X", "https://y": "Y"})
    stream = InMemoryEventStream()
    topic = "trace-topic-2"

    await publish_run(stream, Url4Executor(io), topic, "(https://x, https://y)!go")
    frames = await _collect(stream, topic)

    span_frames = [f for f in frames if isinstance(f, SpanEvent)]
    non_span_frames = [f for f in frames if not isinstance(f, SpanEvent)]
    assert non_span_frames
    for frame in non_span_frames:
        assert frame.tracestate is None

    roots = [f for f in span_frames if f.tracestate is None]
    assert len(roots) == 1
    root_span_id = _TP_RE.match(roots[0].traceparent).group(2)  # type: ignore[union-attr]

    children = [f for f in span_frames if f is not roots[0]]
    assert len(children) == 2
    for child in children:
        assert child.tracestate == f"url4.parent={root_span_id}"


@pytest.mark.asyncio
async def test_fanout_span_edge_set_matches_mock_runner_shape() -> None:
    io = StaticIOLayer(fetch_map={"https://x": "X", "https://y": "Y"})
    stream = InMemoryEventStream()
    topic = "trace-topic-3"

    await publish_run(stream, Url4Executor(io), topic, "(https://x, https://y)!go")
    frames = await _collect(stream, topic)
    real_spans = [f for f in frames if isinstance(f, SpanEvent)]
    assert len(real_spans) == 3

    mock_frames = build_run("mock-topic", "(gpt,claude)!'demo'")
    mock_spans = [f for f in mock_frames if isinstance(f, SpanEvent)]

    assert _edge_shape(real_spans) == _edge_shape(mock_spans) == [None, "root", "root"]


@pytest.mark.asyncio
async def test_malformed_inbound_traceparent_mints_a_fresh_trace() -> None:
    io = StaticIOLayer(fetch_map={"https://a": "A"})
    stream = InMemoryEventStream()
    topic = "trace-topic-4"

    await publish_run(stream, Url4Executor(io), topic, "https://a!go", traceparent="garbage")
    frames = await _collect(stream, topic)

    trace_ids = set()
    for frame in frames:
        match = _TP_RE.match(frame.traceparent)  # type: ignore[arg-type]
        assert match is not None
        trace_ids.add(match.group(1))
    assert len(trace_ids) == 1
    assert next(iter(trace_ids)) != "garbage"


@pytest.mark.asyncio
async def test_all_zero_inbound_traceparent_mints_a_fresh_trace() -> None:
    io = StaticIOLayer(fetch_map={"https://a": "A"})
    stream = InMemoryEventStream()
    topic = "trace-topic-4b"
    all_zero = f"00-{'0' * 32}-{'b' * 16}-01"

    await publish_run(stream, Url4Executor(io), topic, "https://a!go", traceparent=all_zero)
    frames = await _collect(stream, topic)

    trace_ids = set()
    for frame in frames:
        match = _TP_RE.match(frame.traceparent)  # type: ignore[arg-type]
        assert match is not None
        trace_ids.add(match.group(1))
    assert len(trace_ids) == 1
    assert next(iter(trace_ids)) != "0" * 32


def _token(topic: str) -> str:
    return JwtCodec(secret=SECRET, iat_window_s=WINDOW_S, capability_lifetime_s=LIFETIME_S).sign(topic, T0)


def _app(job_runner: RecordingJobRunner) -> FastAPI:
    settings = Settings(jwt_secret=SECRET, iat_window_s=WINDOW_S)
    return create_app(
        settings,
        stream=InMemoryEventStream(),
        job_runner=job_runner,
        clock=lambda: T0,
        interest=FixedGate(),
    )


def _client(app: FastAPI) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


@pytest.mark.asyncio
async def test_routes_valid_inbound_traceparent_forwards_into_schedule() -> None:
    topic = "trace-topic-5-valid"
    runner = RecordingJobRunner()
    app = _app(runner)
    valid_tp = f"00-{'a' * 32}-{'b' * 16}-01"

    async with _client(app) as client:
        resp = await client.get(
            "/",
            params={"q": "gpt(hi)"},
            headers={
                "URL4-Capability": _token(topic),
                "Prefer": "respond-async",
                "traceparent": valid_tp,
            },
        )
    assert resp.status_code == 202
    assert runner.scheduled == [
        ScheduledRun(
            topic=topic,
            url4="gpt(hi)",
            deadline_s=app.state.settings.job_deadline_s,
            traceparent=valid_tp,
            credential=None,
            profile=None,
        )
    ]


@pytest.mark.asyncio
async def test_routes_absent_traceparent_schedules_with_none() -> None:
    topic = "trace-topic-5-absent"
    runner = RecordingJobRunner()
    app = _app(runner)

    async with _client(app) as client:
        resp = await client.get(
            "/",
            params={"q": "gpt(hi)"},
            headers={"URL4-Capability": _token(topic), "Prefer": "respond-async"},
        )
    assert resp.status_code == 202
    assert runner.scheduled[0].traceparent is None


@pytest.mark.asyncio
async def test_routes_malformed_traceparent_schedules_with_none() -> None:
    topic = "trace-topic-5-malformed"
    runner = RecordingJobRunner()
    app = _app(runner)

    async with _client(app) as client:
        resp = await client.get(
            "/",
            params={"q": "gpt(hi)"},
            headers={
                "URL4-Capability": _token(topic),
                "Prefer": "respond-async",
                "traceparent": "garbage",
            },
        )
    assert resp.status_code == 202
    assert runner.scheduled[0].traceparent is None


@pytest.mark.asyncio
async def test_non_span_lifecycle_frames_carry_root_traceparent() -> None:
    io = StaticIOLayer(fetch_map={"https://a": "A"})
    stream = InMemoryEventStream()
    topic = "trace-topic-6"

    await publish_run(stream, Url4Executor(io), topic, "https://a!go")
    frames = await _collect(stream, topic)

    started = next(f for f in frames if isinstance(f, StartedEvent))
    result = next(f for f in frames if isinstance(f, ResultEvent))
    terminated = next(f for f in frames if isinstance(f, TerminatedEvent))

    assert started.traceparent == result.traceparent == terminated.traceparent
    assert _TP_RE.match(started.traceparent)  # type: ignore[arg-type]
    assert started.tracestate is None
    assert result.tracestate is None
    assert terminated.tracestate is None
