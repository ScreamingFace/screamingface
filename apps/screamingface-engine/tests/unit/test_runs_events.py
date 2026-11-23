"""E5 P2 spec §4.2, R10 and §6 Events: `GET /runs/{id}/events`, one WebSocket for a whole Run.

FEATURE: a detached Run (OME-1837). STORY: as a researcher, I follow my Run from any machine and
see each Candidate start, its progress, and its record when it ends; a database blip on the Engine
does not drop me, and while I follow, my attached Run keeps going.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable, Iterator, Sequence
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

import pytest
from _fakes import RecordingJobRunner
from fastapi.testclient import TestClient
from starlette.testclient import WebSocketTestSession
from starlette.websockets import WebSocketDisconnect
from test_runs_routes import ALICE, BOB, _Engine

from screamingface_engine.adapters.memory import InMemoryEventStream
from screamingface_engine.runs.records import (
    CandidateRecord,
    CandidateState,
    OwnerKey,
    RunRecord,
    StopReason,
    owner_key,
)
from screamingface_engine.runs.state import derive_state
from url4.streaming.protocol import (
    LogData,
    LogEvent,
    OutboundFrame,
    TerminatedData,
    TerminatedEvent,
    source_for,
)

RUN_ID = "run_" + "a" * 32
OWNER = owner_key(ALICE["X-User-Email"])
RECORD = {"usage": {"input_tokens": 3}, "trace_id": "t" * 32}
# Bounds every wait: a route that never sends what a test expects fails it, never hangs it.
_MOST_FRAMES = 400


class _Runs:
    """The registry of one Run, which a test moves along; ``down`` fails that many reads."""

    def __init__(self, *candidates: tuple[CandidateState, str | None]) -> None:
        self.candidates = [
            CandidateRecord(index=i, name=f"c{i}", state=state, attempt_id=topic)
            for i, (state, topic) in enumerate(candidates)
        ]
        self.stopped_by: StopReason | None = None
        self.recorded: dict[int, dict[str, Any]] = {}
        self.down = 0
        self.holds = 0
        # While set, every summary read waits: the route's poll is stalled.
        self.stalled = False

    def move(self, index: int, state: CandidateState, topic: str | None = None) -> None:
        old = self.candidates[index]
        self.candidates[index] = replace(old, state=state, attempt_id=topic or old.attempt_id)

    def _fail(self) -> None:
        if self.down:
            self.down -= 1
            raise ConnectionError("the database is down")

    async def summary(self, owner: OwnerKey, run_id: str) -> RunRecord | None:
        while self.stalled:
            await asyncio.sleep(0.01)
        self._fail()
        if (owner, run_id) != (OWNER, RUN_ID):
            return None
        states: list[CandidateState] = [c.state for c in self.candidates]
        return RunRecord(
            id=RUN_ID,
            state=derive_state(states, canceled=self.stopped_by == "canceled"),
            created_at=datetime(2026, 11, 12, tzinfo=UTC),
            finished_at=None,
            benchmark="gsm8k",
            case_count=3,
            candidates=tuple(self.candidates),
            stopped_by=self.stopped_by,
        )

    async def records(
        self, owner: OwnerKey, run_id: str, indexes: Sequence[int]
    ) -> dict[int, dict[str, Any] | None]:
        self._fail()
        return {i: self.recorded.get(i) for i in indexes}

    async def hold(self, run_id: str) -> None:
        self._fail()
        self.holds += 1

    async def aclose(self) -> None:
        """The App's shutdown closes its registry."""


class _StreamRunner(RecordingJobRunner):
    """A runner whose `last_frame` reads the App's event stream, as both real runners do."""

    stream: InMemoryEventStream

    async def last_frame(self, topic: str) -> OutboundFrame | None:
        return await self.stream.last_frame(topic)


def _log(topic: str, body: str) -> LogEvent:
    return LogEvent(
        id=body,
        source=source_for(topic),
        subject=topic,
        time=datetime.now(UTC),
        data=LogData(severity_number=9, severity_text="INFO", body=body),
    )


def _ended(topic: str, status: Any = "succeeded") -> TerminatedEvent:
    return TerminatedEvent(
        id=f"end-{topic}",
        source=source_for(topic),
        subject=topic,
        time=datetime.now(UTC),
        data=TerminatedData(status=status),
    )


class _App:
    def __init__(self, runs: _Runs | None, **settings: Any) -> None:
        runner = _StreamRunner()
        engine = _Engine(None, runner=runner)
        self.app = engine.app
        self.stream: InMemoryEventStream = self.app.state.stream
        runner.stream = self.stream
        self.runs = runs
        self.settings = {"run_events_poll_s": 0.02, "ws_heartbeat_s": 0.05, **settings}

    @property
    def portal(self) -> Any:
        assert self.client.portal is not None
        return self.client.portal

    def __enter__(self) -> _App:
        self.client = TestClient(self.app).__enter__()
        state = self.app.state
        state.settings = state.settings.model_copy(update=self.settings)
        state.run_registry = self.runs
        return self

    def __exit__(self, *exc: object) -> None:
        self.client.__exit__(*exc)

    def publish(self, frame: OutboundFrame) -> None:
        self.portal.call(self.stream.publish, frame.subject, frame)

    def follow(self, run_id: str = RUN_ID, headers: dict[str, str] = ALICE) -> WebSocketTestSession:
        # WHY a copy: the test client adds its handshake headers to the mapping it is given.
        return self.client.websocket_connect(f"/runs/{run_id}/events", headers=dict(headers))


def _next(ws: WebSocketTestSession, *, heartbeats: bool = False) -> dict[str, Any]:
    for _ in range(_MOST_FRAMES):
        frame = ws.receive_json()
        if heartbeats or frame["type"] != "heartbeat":
            return frame
    raise AssertionError("the route sent only heartbeats")


def _until(ws: WebSocketTestSession, last: str) -> list[dict[str, Any]]:
    """Every frame but heartbeats, up to and including the first of type ``last``."""
    frames: list[dict[str, Any]] = []
    while not frames or frames[-1]["type"] != last:
        frames.append(_next(ws))
        assert len(frames) < _MOST_FRAMES
    return frames


def _of(frames: list[dict[str, Any]], index: int) -> list[tuple[str, Any]]:
    """One Candidate's frames, as (type, the field that tells them apart)."""
    shown: list[tuple[str, Any]] = []
    for frame in frames:
        if frame.get("index") != index:
            continue
        kind = frame["type"]
        if kind == "candidate.event":
            shown.append((kind, frame["event"]["id"]))
        elif kind == "candidate.settled":
            shown.append((kind, (frame["state"], frame["record"])))
        else:
            shown.append((kind, frame["state"]))
    return shown


def _wait(check: Callable[[], bool], what: str) -> None:
    for _ in range(300):
        if check():
            return
        time.sleep(0.01)
    raise AssertionError(what)


@pytest.fixture
def app_of() -> Iterator[Callable[..., _App]]:
    opened: list[_App] = []

    def build(runs: _Runs | None, **settings: Any) -> _App:
        app = _App(runs, **settings).__enter__()
        opened.append(app)
        return app

    yield build
    for app in opened:
        app.__exit__(None, None, None)


# --- frames, in order (spec §4.2) --------------------------------------------------------


def test_a_follower_sees_a_candidate_start_run_end_and_the_run_end(
    app_of: Callable[..., _App],
) -> None:
    runs = _Runs(("scheduled", "t0"))
    app = app_of(runs)

    with app.follow() as ws:
        assert _next(ws) == {"type": "candidate.state", "index": 0, "state": "scheduled"}
        app.publish(_log("t0", "one"))
        app.publish(_ended("t0"))
        runs.recorded[0] = RECORD
        runs.move(0, "succeeded")
        frames = _until(ws, "run.ended")
        with pytest.raises(WebSocketDisconnect) as closed:
            ws.receive_json()

    assert _of(frames, 0) == [
        ("candidate.state", "running"),
        ("candidate.event", "one"),
        ("candidate.event", "end-t0"),
        ("candidate.settled", ("succeeded", RECORD)),
    ]
    assert frames[-1] == {"type": "run.ended", "state": "complete", "stopped_by": None}
    assert frames[1]["event"]["data"]["body"] == "one"
    assert closed.value.code == 1000


def test_a_late_follower_gets_the_record_of_an_ended_candidate_and_the_events_of_a_live_one(
    app_of: Callable[..., _App],
) -> None:
    runs = _Runs(("succeeded", "t0"), ("scheduled", "t1"), ("pending", None))
    runs.recorded[0] = RECORD
    app = app_of(runs)
    app.publish(_log("t0", "old"))
    app.publish(_ended("t0"))
    app.publish(_log("t1", "first"))
    app.publish(_log("t1", "second"))

    with app.follow() as ws:
        frames = [_next(ws) for _ in range(6)]
        app.publish(_ended("t1", "failed"))
        runs.move(1, "failed")
        runs.move(2, "stopped")
        runs.stopped_by = "canceled"
        frames += _until(ws, "run.ended")

    assert _of(frames, 0) == [("candidate.settled", ("succeeded", RECORD))]
    assert _of(frames, 1) == [
        ("candidate.state", "scheduled"),
        ("candidate.state", "running"),
        ("candidate.event", "first"),
        ("candidate.event", "second"),
        ("candidate.event", "end-t1"),
        ("candidate.settled", ("failed", None)),
    ]
    assert _of(frames, 2) == [
        ("candidate.state", "pending"),
        ("candidate.settled", ("stopped", None)),
    ]
    assert frames[-1] == {"type": "run.ended", "state": "canceled", "stopped_by": "canceled"}


def test_a_succeeded_candidate_settles_once_its_record_lands(app_of: Callable[..., _App]) -> None:
    """Review round 3: the driver may settle a Candidate from its terminal frame before the
    runner's outcome lands (R7). Its settled frame waits for the record, which names the result
    the Client fetches."""
    runs = _Runs(("succeeded", "t0"))
    app = app_of(runs)

    with app.follow() as ws:
        early = [_next(ws, heartbeats=True) for _ in range(3)]
        runs.recorded[0] = RECORD
        frames = _until(ws, "run.ended")

    assert early == [{"type": "heartbeat"}] * 3
    assert _of(frames, 0) == [("candidate.settled", ("succeeded", RECORD))]


def test_a_succeeded_candidate_whose_record_never_lands_settles_after_the_outcome_grace(
    app_of: Callable[..., _App],
) -> None:
    runs = _Runs(("succeeded", "t0"))
    app = app_of(runs, run_outcome_grace_s=0.2)

    with app.follow() as ws:
        frames = _until(ws, "run.ended")

    assert _of(frames, 0) == [("candidate.settled", ("succeeded", None))]


def test_a_candidate_stopped_before_it_ran_settles_without_waiting_for_a_frame(
    app_of: Callable[..., _App],
) -> None:
    runs = _Runs(("pending", None))
    app = app_of(runs)

    with app.follow() as ws:
        assert _next(ws)["state"] == "pending"
        runs.move(0, "scheduled", "t0")
        assert _next(ws) == {"type": "candidate.state", "index": 0, "state": "scheduled"}
        runs.move(0, "stopped")
        runs.stopped_by = "deadline"
        frames = _until(ws, "run.ended")

    assert _of(frames, 0) == [("candidate.settled", ("stopped", None))]
    assert frames[-1] == {"type": "run.ended", "state": "interrupted", "stopped_by": "deadline"}


def test_a_silent_run_sends_heartbeats(app_of: Callable[..., _App]) -> None:
    app = app_of(_Runs(("pending", None)))

    with app.follow() as ws:
        assert _next(ws)["type"] == "candidate.state"
        beats = [_next(ws, heartbeats=True) for _ in range(3)]

    assert beats == [{"type": "heartbeat"}] * 3


# --- registry failures and follows (spec R10) --------------------------------------------


def test_a_registry_failure_does_not_close_the_stream(app_of: Callable[..., _App]) -> None:
    runs = _Runs(("scheduled", "t0"))
    app = app_of(runs, run_follow_stamp_s=0.05)

    with app.follow() as ws:
        assert _next(ws)["state"] == "scheduled"
        held = runs.holds
        runs.down = 20
        app.publish(_log("t0", "during"))
        during = [_next(ws), _next(ws)]
        _wait(lambda: runs.down == 0, "the route stopped reading the registry")
        _wait(lambda: runs.holds > held, "no hold after the registry came back")
        app.publish(_ended("t0"))
        runs.recorded[0] = RECORD  # the outcome writes state and record together
        runs.move(0, "succeeded")
        frames = _until(ws, "run.ended")

    assert [frame["type"] for frame in during] == ["candidate.state", "candidate.event"]
    assert frames[-1]["type"] == "run.ended"


def test_a_connected_follower_holds_the_run_again(app_of: Callable[..., _App]) -> None:
    runs = _Runs(("pending", None))
    app = app_of(runs, run_follow_stamp_s=0.05)

    with app.follow() as ws:
        _next(ws)
        for _ in range(6):
            _next(ws, heartbeats=True)
        _wait(lambda: runs.holds >= 3, "a connected follower did not hold the Run again")


def test_a_follower_holds_the_run_when_it_connects_and_when_it_leaves(
    app_of: Callable[..., _App],
) -> None:
    runs = _Runs(("pending", None))
    app = app_of(runs, run_follow_stamp_s=60)

    with app.follow() as ws:
        _next(ws)
        assert runs.holds == 1

    _wait(lambda: runs.holds == 2, "a leaving follower did not hold the Run")


def test_a_follower_whose_frames_stall_still_holds_the_run(app_of: Callable[..., _App]) -> None:
    """R10: the route holds on a timer of its own, not in the loop that sends frames, so a
    follower that reads slowly (one fetching a result) holds its Run while its socket is open."""
    runs = _Runs(("pending", None))
    app = app_of(runs, run_follow_stamp_s=0.05)

    with app.follow() as ws:
        _next(ws)
        runs.stalled = True
        held = runs.holds
        _wait(lambda: runs.holds >= held + 3, "a stalled follow stopped holding the Run")
        runs.stalled = False


# --- who may follow (spec D5) ------------------------------------------------------------


@pytest.mark.parametrize(
    ("who", "reason"),
    [
        ("foreign", "run_not_found"),
        ("unknown", "run_not_found"),
        ("malformed", "run_not_found"),
        ("no-identity", "identity_required"),
        ("runs-off", "runs_off"),
    ],
)
def test_only_the_owner_follows_a_run(app_of: Callable[..., _App], who: str, reason: str) -> None:
    runs = _Runs(("scheduled", "t0"))
    app = app_of(None if who == "runs-off" else runs)
    run_id = {"unknown": "run_" + "0" * 32, "malformed": "nope"}.get(who, RUN_ID)
    headers = {"foreign": BOB, "no-identity": {}}.get(who, ALICE)

    with pytest.raises(WebSocketDisconnect) as refused, app.follow(run_id, headers) as ws:
        ws.receive_json()

    assert (refused.value.code, refused.value.reason) == (1008, reason)
    assert runs.holds == 0


def test_a_registry_that_cannot_say_whose_the_run_is_asks_the_follower_to_retry(
    app_of: Callable[..., _App],
) -> None:
    runs = _Runs(("scheduled", "t0"))
    runs.down = 1
    app = app_of(runs)

    with pytest.raises(WebSocketDisconnect) as refused, app.follow() as ws:
        ws.receive_json()

    assert (refused.value.code, refused.value.reason) == (1013, "registry_unavailable")


def test_a_settled_frame_names_the_candidates_attempt_and_error_code(
    app_of: Callable[..., _App],
) -> None:
    """The Client builds a Candidate's outcome from this frame alone: the attempt names it and
    keys its saved result, and the code says why one with no record ended (spec §4.2)."""
    runs = _Runs(("scheduled", "t0"), ("pending", None))
    app = app_of(runs)
    runs.recorded[0] = RECORD
    runs.move(0, "succeeded")
    runs.candidates[1] = replace(runs.candidates[1], state="failed", error_code="start_refused")

    with app.follow() as ws:
        frames = _until(ws, "run.ended")

    settled = {frame["index"]: frame for frame in frames if frame["type"] == "candidate.settled"}
    assert (settled[0]["attempt_id"], settled[0]["error_code"]) == ("t0", None)
    assert (settled[1]["attempt_id"], settled[1]["error_code"]) == (None, "start_refused")


def test_a_follower_that_asks_for_no_events_gets_each_candidates_state_and_end(
    app_of: Callable[..., _App],
) -> None:
    """`Run.wait()` needs only when the Run ends, so it asks for no events (`?events=false`):
    the stream sends each Candidate's state, its settled frame and the Run's end, and still
    holds an attached Run (R10)."""
    runs = _Runs(("scheduled", "t0"))
    app = app_of(runs)
    app.publish(_log("t0", "old"))

    url = f"/runs/{RUN_ID}/events?events=false"
    with app.client.websocket_connect(url, headers=dict(ALICE)) as ws:
        assert _next(ws) == {"type": "candidate.state", "index": 0, "state": "scheduled"}
        app.publish(_log("t0", "one"))
        app.publish(_ended("t0"))
        runs.recorded[0] = RECORD
        runs.move(0, "succeeded")
        frames = _until(ws, "run.ended")

    assert _of(frames, 0) == [("candidate.settled", ("succeeded", RECORD))]
    assert runs.holds
