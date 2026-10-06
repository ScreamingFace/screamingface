"""The run-submission route's accept span, through HTTP and on into the run (OME-1218).

STORY: as an operator reading a run's waterfall, I see the control plane accept the run, a gap
(queue wait + Job boot), then `url4.run` underneath it — in ONE trace, even when the caller
sent no traceparent at all.
"""

from __future__ import annotations

from datetime import UTC, datetime

import httpx
import pytest
from _fakes import FixedGate, RecordingJobRunner
from fastapi import FastAPI
from httpx import ASGITransport

from screamingface_engine.app import create_app
from screamingface_engine.auth import JwtCodec
from screamingface_engine.config import Settings
from screamingface_engine.runner.executor import Url4Executor
from screamingface_engine.testing import InMemoryEventStream
from screamingface_engine.tracing.accept import ACCEPT_SPAN_NAME
from screamingface_engine.tracing.relay import ROOT_SPAN_NAME, SpanRelay
from screamingface_engine.tracing.span_tree import Span
from url4.io.static import StaticIOLayer
from url4.streaming.lifecycle import run as publish_run

SECRET = "accept-span-unit-secret-at-least-32-bytes"
WINDOW_S = 60
LIFETIME_S = 58_800
T0 = datetime(2026, 7, 21, 9, 0, 0, tzinfo=UTC)
INBOUND_TRACE = "4bf92f3577b34da6a3ce929d0e0e4736"
INBOUND_SPAN = "00f067aa0ba902b7"
INBOUND = f"00-{INBOUND_TRACE}-{INBOUND_SPAN}-01"


class FakeSink:
    def __init__(self) -> None:
        self.spans: list[Span] = []
        self.closed = 0

    def emit(self, span: Span) -> None:
        self.spans.append(span)

    def close(self) -> None:
        self.closed += 1


def _token(topic: str) -> str:
    return JwtCodec(secret=SECRET, iat_window_s=WINDOW_S, capability_lifetime_s=LIFETIME_S).sign(
        topic, T0
    )


def _app(
    runner: RecordingJobRunner, sink: FakeSink | None, *, gate: FixedGate | None = None
) -> FastAPI:
    return create_app(
        Settings(jwt_secret=SECRET, iat_window_s=WINDOW_S),
        stream=InMemoryEventStream(),
        job_runner=runner,
        clock=lambda: T0,
        interest=gate or FixedGate(),
        span_sink=sink,
    )


async def _start(
    app: FastAPI, topic: str, *, q: str | None = "gpt(hi)", **headers: str
) -> httpx.Response:
    params = {"q": q} if q is not None else {}
    async with httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        return await c.get(
            "/", params=params, headers={"URL4-Capability": _token(topic), **headers}
        )


def _accepts(sink: FakeSink) -> list[Span]:
    return [s for s in sink.spans if s.name == ACCEPT_SPAN_NAME]


@pytest.mark.asyncio
async def test_without_inbound_context_the_run_is_handed_the_accept_spans_traceparent() -> None:
    runner, sink = RecordingJobRunner(), FakeSink()

    resp = await _start(_app(runner, sink), "acc-1", Prefer="respond-async")

    assert resp.status_code == 202
    (accept,) = _accepts(sink)
    assert accept.parent_span_id is None
    assert accept.attributes["url4.accept.outcome"] == "scheduled"
    assert runner.scheduled[0].traceparent == f"00-{accept.trace_id}-{accept.span_id}-01"


@pytest.mark.asyncio
async def test_with_inbound_context_the_accept_span_is_its_child_and_the_run_its_grandchild() -> (
    None
):
    runner, sink = RecordingJobRunner(), FakeSink()

    await _start(_app(runner, sink), "acc-2", Prefer="respond-async", traceparent=INBOUND)

    (accept,) = _accepts(sink)
    assert accept.trace_id == INBOUND_TRACE
    assert accept.parent_span_id == INBOUND_SPAN
    assert runner.scheduled[0].traceparent == f"00-{INBOUND_TRACE}-{accept.span_id}-01"


@pytest.mark.asyncio
async def test_without_a_sink_the_inbound_traceparent_is_forwarded_unchanged() -> None:
    """D4: off by construction. A self-minted parent nobody exports would dangle."""
    runner = RecordingJobRunner()

    await _start(_app(runner, None), "acc-3", Prefer="respond-async", traceparent=INBOUND)

    assert runner.scheduled[0].traceparent == INBOUND


@pytest.mark.asyncio
async def test_a_duplicate_run_emits_a_refused_accept_span() -> None:
    runner, sink = RecordingJobRunner(exists=True), FakeSink()

    resp = await _start(_app(runner, sink), "acc-4", Prefer="respond-async")

    assert resp.status_code == 409
    (accept,) = _accepts(sink)
    assert accept.attributes["url4.accept.outcome"] == "refused"
    assert accept.attributes["http.response.status_code"] == 409
    assert runner.scheduled == []


@pytest.mark.asyncio
async def test_a_validation_failure_emits_a_refused_accept_span() -> None:
    sink = FakeSink()

    resp = await _start(_app(RecordingJobRunner(), sink), "acc-5", q=None)

    assert resp.status_code == 400
    assert _accepts(sink)[0].attributes["http.response.status_code"] == 400


@pytest.mark.asyncio
async def test_a_missing_subscriber_emits_a_refused_accept_span() -> None:
    sink = FakeSink()

    resp = await _start(
        _app(RecordingJobRunner(), sink, gate=FixedGate(present=False)),
        "acc-6",
        Prefer="respond-async",
    )

    assert resp.status_code == 428
    assert _accepts(sink)[0].attributes["http.response.status_code"] == 428


@pytest.mark.asyncio
async def test_a_sync_request_ends_the_accept_span_at_enqueue_not_after_the_hold() -> None:
    """D2: the sync hold is not accept latency. Counting it would swallow the queue-wait gap."""
    runner, sink = RecordingJobRunner(), FakeSink()

    resp = await _start(_app(runner, sink), "acc-7", Prefer="wait=0.5")

    assert resp.status_code == 202  # the bound elapsed: nothing ever terminates this run
    (accept,) = _accepts(sink)
    assert accept.attributes["url4.accept.outcome"] == "scheduled"
    assert accept.end_time is not None
    assert (accept.end_time - accept.start_time).total_seconds() < 0.4


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["/healthz", "/livez", "/readyz", "/metrics"])
async def test_probe_and_scrape_routes_emit_no_span(path: str) -> None:
    """OME-1217's lesson, from the start: probes as root spans were 60% of aigateway's
    spans. Here no probe span exists by construction — only the submission route opens one."""
    sink = FakeSink()
    app = _app(RecordingJobRunner(), sink)

    async with httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        await c.get(path)

    assert sink.spans == []


@pytest.mark.asyncio
async def test_one_run_is_one_trace_rooted_at_the_accept_span() -> None:
    """The ticket's Verify, end to end minus the network: accept → forwarded traceparent →
    `lifecycle.run` → relay. No inbound context, and still ONE trace whose only root is the
    accept span, with `url4.run` directly beneath it."""
    runner, sink = RecordingJobRunner(), FakeSink()
    await _start(_app(runner, sink), "acc-8", Prefer="respond-async")
    handed = runner.scheduled[0].traceparent

    stream = InMemoryEventStream()
    with SpanRelay(stream, sink, traceparent=handed) as relay:
        executor = Url4Executor(StaticIOLayer(fetch_map={"https://a": "A"}))
        await publish_run(relay, executor, "acc-8", "https://a!go", traceparent=handed)

    (accept,) = _accepts(sink)
    (run_span,) = [s for s in sink.spans if s.name == ROOT_SPAN_NAME]
    assert {s.trace_id for s in sink.spans} == {accept.trace_id}
    assert run_span.parent_span_id == accept.span_id
    assert [s.name for s in sink.spans if s.parent_span_id is None] == [ACCEPT_SPAN_NAME]


@pytest.mark.asyncio
async def test_shutdown_closes_the_control_plane_sink() -> None:
    sink = FakeSink()
    app = _app(RecordingJobRunner(), sink)

    for handler in app.router.on_shutdown:
        await handler()

    assert sink.closed == 1
