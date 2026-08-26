import asyncio
from collections.abc import Mapping
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient

from screamingface_engine.app import create_app
from screamingface_engine.auth import JwtCodec
from screamingface_engine.config import Settings
from screamingface_engine.ports import IdentityAwareJobRunner
from screamingface_engine.testing import InMemoryEventStream
from screamingface_engine.testing.mock_runner import publish_mock_run
from url4.streaming.interfaces import JobStatus, job_name
from url4.streaming.protocol import (
    AttachData,
    AttachEvent,
    CachePolicy,
    CostUsageEvent,
    OutboundFrame,
    OutboundFrameAdapter,
    ResultEvent,
    SpanEvent,
    TerminatedEvent,
)

SECRET = "e2e-secret"
WINDOW_S = 60
LIFETIME_S = 58_800  # capability_lifetime_s (D1, OME-1016)
SUBPROTOCOL = "cloudevents.json"
EXPR = "(gpt,claude)!'hi'"
T0 = datetime(2026, 7, 21, 9, 0, 0, tzinfo=UTC)


class MockRunnerJobRunner(IdentityAwareJobRunner):
    def __init__(self, stream: InMemoryEventStream) -> None:
        self._stream = stream
        self.scheduled: list[tuple[str, str, int]] = []
        self.stopped: list[str] = []
        self._tasks: list[asyncio.Task[None]] = []

    async def schedule(
        self,
        topic: str,
        url4: str,
        deadline_s: int,
        *,
        traceparent: str | None = None,
        credential: str | None = None,
        profile: str | None = None,
        identity: Mapping[str, str] | None = None,
        # Accepted so this fake still satisfies the port; the mock run it publishes never reaches
        # a gateway, so there is nothing here for a cache policy to change.
        cache: CachePolicy | None = None,
    ) -> str:
        self.scheduled.append((topic, url4, deadline_s))
        self._tasks.append(asyncio.ensure_future(publish_mock_run(self._stream, topic, url4)))
        return job_name(topic)

    async def stop(self, topic: str) -> None:
        self.stopped.append(topic)

    async def exists(self, topic: str) -> bool:
        return False

    async def status(self, topic: str) -> JobStatus:
        return "running"


def _make_app(stream: InMemoryEventStream, runner: MockRunnerJobRunner) -> FastAPI:
    settings = Settings(jwt_secret=SECRET, iat_window_s=WINDOW_S, ws_heartbeat_s=30.0)
    return create_app(settings, stream=stream, job_runner=runner, clock=lambda: T0)


def _topic_of(token: str) -> str:
    return str(JwtCodec(secret=SECRET, iat_window_s=WINDOW_S, capability_lifetime_s=LIFETIME_S).verify(token, T0)["sub"])


def _attach() -> dict[str, Any]:
    return AttachEvent(
        id="att", source="/client", subject="t", data=AttachData(from_sequence=None)
    ).model_dump(mode="json", by_alias=True)


def _read_until_terminated(ws: Any) -> list[dict[str, Any]]:
    frames: list[dict[str, Any]] = []
    for _ in range(40):
        frame = ws.receive_json()
        frames.append(frame)
        if frame["type"] == "ai.url4.terminated":
            return frames
    raise AssertionError("no terminated frame within the read budget")


def _span_parent(event: SpanEvent) -> str | None:
    return None if event.tracestate is None else event.tracestate.split("=", 1)[1]


def test_full_flow_streams_valid_section8_events_then_purges() -> None:
    stream = InMemoryEventStream()
    runner = MockRunnerJobRunner(stream)
    app = _make_app(stream, runner)
    with TestClient(app) as client:
        token = client.post("/token").json()["token"]
        topic = _topic_of(token)
        cap = {"URL4-Capability": token}

        with client.websocket_connect(f"/ws?ticket={token}", subprotocols=[SUBPROTOCOL]) as ws:
            ws.send_json(_attach())
            started = client.get(
                "/", params={"q": EXPR}, headers={**cap, "Prefer": "respond-async"}
            )
            assert started.status_code == 202
            assert runner.scheduled and runner.scheduled[0][0] == topic
            wire = _read_until_terminated(ws)

            frames: list[OutboundFrame] = [OutboundFrameAdapter.validate_python(f) for f in wire]
            assert [f.type for f in frames][0] == "ai.url4.started"
            assert isinstance(frames[-1], TerminatedEvent)
            assert frames[-1].data.status == "succeeded"
            assert [int(f.sequence) for f in frames if f.sequence is not None] == list(
                range(1, len(frames) + 1)
            )
            _assert_cost_rolls_up(frames)
            _assert_span_tree(frames)

            purged = client.delete("/", params={"topic": topic}, headers=cap)
        assert purged.status_code == 204
    assert runner.stopped == [topic]
    assert stream._log[topic] == []  # noqa: SLF001 — asserting the DELETE purge side effect


def _assert_cost_rolls_up(frames: list[OutboundFrame]) -> None:
    costs = [f for f in frames if isinstance(f, CostUsageEvent)]
    selfs = [c for c in costs if c.data.scope == "self"]
    subtree = next(c for c in costs if c.data.scope == "subtree")
    assert subtree.data.cost.total_usd == sum((c.data.cost.total_usd for c in selfs), Decimal("0"))
    subtree_idx = frames.index(subtree)
    result_idx = next(i for i, f in enumerate(frames) if isinstance(f, ResultEvent))
    assert subtree_idx < result_idx


def _assert_span_tree(frames: list[OutboundFrame]) -> None:
    spans = [f for f in frames if isinstance(f, SpanEvent)]
    seen: set[str] = set()
    for span in spans:
        assert span.traceparent is not None
        parent = _span_parent(span)
        if parent is not None:
            assert parent in seen
        seen.add(span.traceparent.split("-")[2])
    assert len(seen) == len(spans)
