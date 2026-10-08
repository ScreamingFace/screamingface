"""Run control-plane resilience across an App restart and past the old 60 s window (OME-1016).

FEATURE: OME-1016 — resumable streams and stoppable runs (plan step 6).
STORY: as a researcher whose Run outlives an App deploy, my client re-attaches to the NEW
App with the capability it already holds and loses no frame; and I can still stop a Run
that has been going for more than a minute.

In-process harness (`TestClient` + `InMemoryEventStream`, no broker), the same one
`test_e2e_compose_flow.py` uses. AIDEV-NOTE: the "App restart" is modelled as two App
instances that share only what production shares — the signing secret and the durable
event history (the broker). Each App has its own event loop and its own in-memory session
registry, so the second one knows nothing about the first one's attach. Each App gets its
own stream object holding the same history because an `asyncio.Condition` cannot be
shared across the two TestClient loops; the broker-backed resume itself is covered by
`test_events_stream.py` against JetStream.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient

from screamingface_engine.app import create_app
from screamingface_engine.auth import JwtCodec
from screamingface_engine.config import Settings
from screamingface_engine.job_env import RunShape
from screamingface_engine.ports import IdentityAwareJobRunner
from screamingface_engine.testing import InMemoryEventStream
from screamingface_engine.testing.mock_runner import build_run, publish_mock_run
from url4.streaming.interfaces import JobStatus, job_name
from url4.streaming.protocol import AttachData, AttachEvent, CachePolicy

SECRET = "resilience-secret-at-least-32-bytes-long"
WINDOW_S = 60
LIFETIME_S = 58_800  # capability_lifetime_s (D1, OME-1016)
SUBPROTOCOL = "cloudevents.json"
EXPR = "(gpt,claude)!'hi'"
T0 = datetime(2026, 9, 28, 9, 0, 0, tzinfo=UTC)
_HEARTBEAT_S = 0.2
_RESUME_DEADLINE_S = 10.0


class _RecordingJobRunner(IdentityAwareJobRunner):
    """Schedules nothing: the Run's frames are already in the durable history."""

    def __init__(self) -> None:
        self.scheduled: list[str] = []
        self.stopped: list[str] = []

    async def schedule(
        self,
        topic: str,
        url4: str,
        deadline_s: int,
        *,
        traceparent: str | None = None,
        credential: str | None = None,
        identity: Mapping[str, str] | None = None,
        cache: CachePolicy | None = None,
        answer_seed: int | None = None,
        client_version: str | None = None,
        shape: RunShape = "expression",
    ) -> str:
        del url4, deadline_s, traceparent, credential, identity, cache
        del answer_seed, client_version, shape
        self.scheduled.append(topic)
        return job_name(topic)

    async def stop(self, topic: str) -> None:
        self.stopped.append(topic)

    async def exists(self, topic: str) -> bool:
        return False

    async def status(self, topic: str) -> JobStatus:
        return "running"


def _app(
    stream: InMemoryEventStream,
    runner: _RecordingJobRunner,
    now: list[datetime],
    *,
    heartbeat_s: float = 30.0,
) -> FastAPI:
    settings = Settings(jwt_secret=SECRET, iat_window_s=WINDOW_S, ws_heartbeat_s=heartbeat_s)
    return create_app(settings, stream=stream, job_runner=runner, clock=lambda: now[0])


def _topic_of(token: str) -> str:
    codec = JwtCodec(secret=SECRET, iat_window_s=WINDOW_S, capability_lifetime_s=LIFETIME_S)
    return str(codec.verify(token, T0)["sub"])


def _attach(from_sequence: int | None) -> dict[str, Any]:
    return AttachEvent(
        id="att", source="/client", subject="t", data=AttachData(from_sequence=from_sequence)
    ).model_dump(mode="json", by_alias=True)


def _history(topic: str) -> InMemoryEventStream:
    """One App's view of the durable history: the full mock Run, already published."""
    stream = InMemoryEventStream()
    asyncio.run(publish_mock_run(stream, topic, EXPR))
    return stream


def _first_app_until_it_dies(
    token: str, runner: _RecordingJobRunner, now: list[datetime], frames: int
) -> list[dict[str, Any]]:
    """App A: the first attach and the start, then the App dies after `frames` frames."""
    cap = {"URL4-Capability": token}
    with TestClient(_app(_history(_topic_of(token)), runner, now)) as app_a:
        with app_a.websocket_connect(f"/ws?ticket={token}", subprotocols=[SUBPROTOCOL]) as ws:
            ws.send_json(_attach(None))
            started = app_a.get("/", params={"q": EXPR}, headers={**cap, "Prefer": "respond-async"})
            assert started.status_code == 202
            return [ws.receive_json() for _ in range(frames)]


def _new_app_resume(
    token: str, runner: _RecordingJobRunner, now: list[datetime], cursor: int, total: int
) -> list[dict[str, Any]]:
    """App B: a fresh instance. The SAME capability, attached from the cursor."""
    # WHY a short heartbeat: `receive_json` has no timeout in the TestClient, so a stalled
    # resume would hang the suite. Heartbeats wake the loop, and the deadline then fails it.
    app = _app(_history(_topic_of(token)), runner, now, heartbeat_s=_HEARTBEAT_S)
    deadline = time.monotonic() + _RESUME_DEADLINE_S
    with TestClient(app) as app_b:
        with app_b.websocket_connect(f"/ws?ticket={token}", subprotocols=[SUBPROTOCOL]) as ws:
            ws.send_json(_attach(cursor))
            rest: list[dict[str, Any]] = []
            while not rest or rest[-1]["type"] != "ai.url4.terminated":
                assert time.monotonic() < deadline, f"resume stalled after {len(rest)} frames"
                frame = ws.receive_json()
                if frame.get("sequence") is not None:  # heartbeats carry no sequence
                    rest.append(frame)
                assert len(rest) <= total
            return rest


def test_a_new_app_resumes_the_same_capability_from_the_cursor_without_loss() -> None:
    now = [T0]
    runner = _RecordingJobRunner()
    total = len(build_run("probe", EXPR))
    with TestClient(_app(InMemoryEventStream(), runner, now)) as minting_app:
        token = minting_app.post("/token").json()["token"]

    first = _first_app_until_it_dies(token, runner, now, frames=3)
    now[0] = T0 + timedelta(minutes=5)  # a deploy takes minutes, well past the old 60 s
    rest = _new_app_resume(token, runner, now, int(first[-1]["sequence"]) + 1, total)

    sequences = [int(frame["sequence"]) for frame in (*first, *rest)]
    # INVARIANT: across the restart the client sees every frame exactly once, in order.
    assert sequences == list(range(1, total + 1))
    assert rest[-1]["data"]["status"] == "succeeded"
    assert runner.scheduled == [_topic_of(token)]  # the resume did not start the Run again


def test_a_run_older_than_sixty_seconds_is_stoppable_by_its_caller() -> None:
    now = [T0]
    runner = _RecordingJobRunner()
    with TestClient(_app(InMemoryEventStream(), runner, now)) as client:
        token = client.post("/token").json()["token"]
        cap = {"URL4-Capability": token}
        with client.websocket_connect(f"/ws?ticket={token}", subprotocols=[SUBPROTOCOL]) as ws:
            ws.send_json(_attach(None))  # an async start needs a live attach (428 otherwise)
            started = client.get(
                "/", params={"q": EXPR}, headers={**cap, "Prefer": "respond-async"}
            )
            assert started.status_code == 202

            # Before OME-1018 this answered 401: the 60 s mint window was also the lifetime.
            now[0] = T0 + timedelta(seconds=WINDOW_S + 1)
            assert client.delete("/", headers=cap).status_code == 204

        # A later stop is still the caller's to make — idempotent, far into the Run's life.
        now[0] = T0 + timedelta(hours=2)
        assert client.delete("/", headers=cap).status_code == 204

    topic = _topic_of(token)
    assert runner.stopped == [topic, topic]


def test_a_capability_past_its_lifetime_can_no_longer_stop_the_run() -> None:
    # Added boundary check, outside spec R6: the lifetime still ends.
    # INVARIANT: `exp` is the only lifetime rule — the boundary is exclusive (`now >= exp`).
    now = [T0]
    runner = _RecordingJobRunner()
    with TestClient(_app(InMemoryEventStream(), runner, now)) as client:
        token = client.post("/token").json()["token"]
        cap = {"URL4-Capability": token}
        now[0] = T0 + timedelta(seconds=LIFETIME_S)
        assert client.delete("/", headers=cap).status_code == 401
    assert runner.stopped == []
