"""How the unclaimed-run warner is wired into the App: when it exists, what it asks, where its
notice lands, and how its one process-wide task starts and stops.

FEATURE: warn the client about an unclaimed queued run (under OME-1086).
"""

import asyncio
from datetime import UTC, datetime
from typing import Any

import pytest
from _fakes import FixedGate, RecordingJobRunner
from fastapi import FastAPI
from fastapi.testclient import TestClient

from screamingface_engine.app import create_app
from screamingface_engine.auth import JwtCodec
from screamingface_engine.config import Settings
from screamingface_engine.rest import SubscriberGate
from screamingface_engine.testing import InMemoryEventStream
from screamingface_engine.unclaimed import UNCLAIMED_MESSAGE, UnclaimedRunWarner
from url4.streaming.interfaces import JobStatus
from url4.streaming.protocol import AttachData, AttachEvent

SECRET = "unclaimed-wiring-secret-0123456789abcdef"
WINDOW_S = 60
LIFETIME_S = 58_800
T0 = datetime(2026, 9, 28, 9, 0, 0, tzinfo=UTC)


class _QueuedRunner(RecordingJobRunner):
    """A queue-aware fake: it answers `accepted_ages()` and a fixed `status()`."""

    def __init__(self, ages: dict[str, float] | None = None, status: JobStatus = "scheduled"):
        super().__init__()
        self.ages = ages if ages is not None else {}
        self._status: JobStatus = status

    def accepted_ages(self) -> dict[str, float]:
        return dict(self.ages)

    async def status(self, topic: str) -> JobStatus:
        return self._status


def _app(
    *,
    warn_s: float = 300.0,
    job_runner: RecordingJobRunner | None = None,
    interest: SubscriberGate | None = None,
    heartbeat_s: float = 15.0,
) -> FastAPI:
    settings = Settings(
        jwt_secret=SECRET,
        iat_window_s=WINDOW_S,
        unclaimed_run_warn_s=warn_s,
        ws_heartbeat_s=heartbeat_s,
    )
    return create_app(
        settings,
        stream=InMemoryEventStream(),
        job_runner=job_runner,
        interest=interest,
        clock=lambda: T0,
    )


def test_the_default_grace_is_five_minutes() -> None:
    # WHY 300 s: two orders of magnitude above a healthy claim (seconds, with the publish's
    # wake-up nudge), so a notice means a saturated or absent pool — never a healthy stack.
    assert Settings(jwt_secret=SECRET).unclaimed_run_warn_s == 300.0


def test_the_grace_is_read_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("URL4_CLOUD_UNCLAIMED_RUN_WARN_S", "42")
    assert Settings(jwt_secret=SECRET).unclaimed_run_warn_s == 42.0


def test_a_negative_grace_is_refused_at_startup() -> None:
    with pytest.raises(ValueError):
        Settings(jwt_secret=SECRET, unclaimed_run_warn_s=-1.0)


def test_a_queue_aware_runner_gets_a_warner() -> None:
    app = _app(job_runner=_QueuedRunner())

    warner = app.state.unclaimed_warner
    assert isinstance(warner, UnclaimedRunWarner)
    assert warner.tick_s == 37.5


def test_a_zero_grace_disables_the_warner() -> None:
    assert _app(warn_s=0.0, job_runner=_QueuedRunner()).state.unclaimed_warner is None


def test_a_runner_with_no_queue_gets_no_warner() -> None:
    # WHY: the in-process runner starts a run at once — there is no queue to wait in.
    assert _app(job_runner=RecordingJobRunner()).state.unclaimed_warner is None


def test_a_stream_only_app_gets_no_warner_and_no_task() -> None:
    app = _app(job_runner=None)

    with TestClient(app):
        assert app.state.unclaimed_warner is None
        assert app.state.unclaimed_warner_task is None


def test_the_task_starts_with_the_app_and_is_cancelled_with_it() -> None:
    app = _app(job_runner=_QueuedRunner())

    with TestClient(app):
        task = app.state.unclaimed_warner_task
        assert isinstance(task, asyncio.Task)
        assert not task.done()

    assert app.state.unclaimed_warner_task.done()


def test_the_warner_asks_the_real_registry_and_never_the_subscriber_gate() -> None:
    """INVARIANT: `FixedGate(True)` says "someone is listening" for every topic. Wired to that
    seam, the warner would decide topics nobody can hear, and a client that attaches later
    would never be told. The real registry holds the connections a notice can reach."""
    runner = _QueuedRunner({"t": 1000.0})
    app = _app(job_runner=runner, interest=FixedGate(True))

    with TestClient(app) as client:
        assert client.portal is not None
        assert client.portal.call(app.state.unclaimed_warner.sweep) == ()


def _token(topic: str) -> str:
    return JwtCodec(secret=SECRET, iat_window_s=WINDOW_S, capability_lifetime_s=LIFETIME_S).sign(
        topic, T0
    )


def _attach(topic: str) -> dict[str, Any]:
    return AttachEvent(
        id="att", source="/client", subject=topic, data=AttachData(from_sequence=None)
    ).model_dump(mode="json", by_alias=True)


def _next_non_heartbeat(ws: Any) -> dict[str, Any]:
    for _ in range(50):
        frame = ws.receive_json()
        if frame["type"] != "ai.url4.heartbeat":
            return frame
    raise AssertionError("only heartbeats arrived")


def test_the_notice_reaches_the_attached_socket_as_a_warn_log_frame() -> None:
    topic = "topic-unclaimed"
    runner = _QueuedRunner({topic: 301.0})
    app = _app(job_runner=runner, heartbeat_s=0.05)

    with TestClient(app) as client, client.websocket_connect(f"/ws?ticket={_token(topic)}") as ws:
        ws.send_json(_attach(topic))
        # Barrier: a heartbeat proves the bridge is attached and its notifier registered.
        assert ws.receive_json()["type"] == "ai.url4.heartbeat"
        assert client.portal is not None
        assert client.portal.call(app.state.unclaimed_warner.sweep) == (topic,)
        frame = _next_non_heartbeat(ws)

    assert frame["type"] == "ai.url4.log"
    assert frame["subject"] == topic
    assert frame["data"]["severity_text"] == "WARN"
    assert frame["data"]["body"] == UNCLAIMED_MESSAGE
    assert frame["data"]["attributes"] == {"run.wait_s": 301}


def test_a_started_run_sends_nothing_to_the_socket() -> None:
    topic = "topic-started"
    runner = _QueuedRunner({topic: 301.0}, status="running")
    app = _app(job_runner=runner, heartbeat_s=0.05)

    with TestClient(app) as client, client.websocket_connect(f"/ws?ticket={_token(topic)}") as ws:
        ws.send_json(_attach(topic))
        assert ws.receive_json()["type"] == "ai.url4.heartbeat"
        assert client.portal is not None
        assert client.portal.call(app.state.unclaimed_warner.sweep) == ()
        # Ordering barrier: frames on one socket are FIFO, so two more heartbeats after the
        # sweep prove no notice was queued ahead of them.
        assert ws.receive_json()["type"] == "ai.url4.heartbeat"
        assert ws.receive_json()["type"] == "ai.url4.heartbeat"
