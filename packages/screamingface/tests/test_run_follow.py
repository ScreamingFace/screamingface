"""Following a Run on its one event stream (E5 P2 spec §4.2, D13, D15; plan C1).

FEATURE: a detached Run (OME-1837). STORY: as a researcher, one connection shows me every
Candidate of my Run as it runs, survives a dropped connection, and tells me how to pick the Run
up again when my sign-in expires overnight.

INVARIANT (§4.2): a reconnect replays what the Engine still holds, and the follower delivers no
event and no settled Candidate twice.
INVARIANT (D15): a follow that outlives the sign-in ends with how to pick the Run up; it never
starts a login of its own.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import pytest
from websockets.datastructures import Headers
from websockets.exceptions import ConnectionClosedError, ConnectionClosedOK, InvalidStatus
from websockets.frames import Close
from websockets.http11 import Response

from screamingface._core.ports import _ConnectionNotice
from screamingface._engine import run_follow as follow
from screamingface.errors import AuthenticationError, ExecutionError
from screamingface.events import Log, Terminated

RUN_ID = "run_" + "c" * 32
TOPIC = "url4-cloud." + "d" * 32


def _cloudevent(sequence: int, kind: str = "ai.url4.log", **data: Any) -> dict[str, Any]:
    if kind == "ai.url4.log" and not data:
        data = {"severity_text": "INFO", "severity_number": 9, "body": f"line {sequence}"}
    return {
        "specversion": "1.0",
        "id": f"e{sequence}",
        "source": "/trace/x/node/root",
        "subject": TOPIC,
        "type": kind,
        "time": "2026-11-14T09:00:00Z",
        "datacontenttype": "application/json",
        "sequence": str(sequence),
        "sequencetype": "Integer",
        "data": data,
    }


def _frame(kind: str, **fields: Any) -> str:
    return json.dumps({"type": kind, **fields})


def _event(index: int, sequence: int, **cloudevent: Any) -> str:
    return _frame("candidate.event", index=index, event=_cloudevent(sequence, **cloudevent))


def _settled(index: int, state: str = "succeeded", record: object = None) -> str:
    return _frame(
        "candidate.settled",
        index=index,
        state=state,
        attempt_id=TOPIC,
        error_code=None,
        record=record,
    )


ENDED = _frame("run.ended", state="complete", stopped_by=None)
HEARTBEAT = _frame("heartbeat")


def _closed(code: int, reason: str = "") -> ConnectionClosedError:
    return ConnectionClosedError(Close(code, reason), None, None)


def _refused(status: int, headers: dict[str, str] | None = None) -> InvalidStatus:
    return InvalidStatus(Response(status, "refused", Headers(headers or {})))


class _Socket:
    def __init__(self, script: list[str | BaseException]) -> None:
        self._script = list(script)

    def recv(self, timeout: float | None = None) -> str:
        if not self._script:
            raise _closed(1006)
        item = self._script.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item


class _Engine:
    """Each connect takes the next script: a list of frames (ending in a close or an error), or
    an exception the handshake raises."""

    def __init__(self, *connections: list[str | BaseException] | BaseException) -> None:
        self._connections = list(connections)
        self.connects = 0

    @contextmanager
    def connect(self) -> Iterator[_Socket]:
        self.connects += 1
        script = self._connections.pop(0)
        if isinstance(script, BaseException):
            raise script
        yield _Socket(script)


def _follow(engine: _Engine, *, detached: bool = False, **options: Any):
    seen: list[object] = []
    ended = follow.follow_sync(
        engine.connect,
        RUN_ID,
        seen.append,
        detached=detached,
        budget_s=options.pop("budget_s", 5.0),
        base_delay_s=0.0,
        **options,
    )
    return ended, seen


def test_every_frame_reaches_the_follower_in_order_and_the_run_end_returns() -> None:
    engine = _Engine(
        [
            _frame("candidate.state", index=0, state="pending"),
            HEARTBEAT,
            _frame("candidate.state", index=0, state="scheduled"),
            _event(0, 1),
            _event(0, 2, kind="ai.url4.terminated", status="succeeded"),
            _settled(0, record={"trace_id": "t"}),
            ENDED,
        ]
    )

    ended, seen = _follow(engine)

    assert ended == follow.RunEnded(state="complete", stopped_by=None)
    assert [type(frame).__name__ for frame in seen] == [
        "CandidateState",
        "CandidateState",
        "CandidateEvent",
        "CandidateEvent",
        "CandidateSettled",
    ]
    first, last = seen[2], seen[3]
    assert isinstance(first, follow.CandidateEvent) and isinstance(first.event, Log)
    assert isinstance(last, follow.CandidateEvent) and isinstance(last.event, Terminated)
    assert seen[4] == follow.CandidateSettled(
        index=0, state="succeeded", attempt_id=TOPIC, error_code=None, record={"trace_id": "t"}
    )


def test_a_reconnect_delivers_no_event_and_no_settled_candidate_twice() -> None:
    engine = _Engine(
        [_event(0, 1), _event(0, 2), _settled(1, "failed"), _closed(1006)],
        [_event(0, 1), _event(0, 2), _event(0, 3), _settled(1, "failed"), _settled(0), ENDED],
    )
    notices: list[_ConnectionNotice] = []

    _, seen = _follow(engine, on_connection=notices.append)

    events = [frame.event.sequence for frame in seen if isinstance(frame, follow.CandidateEvent)]
    settled = [frame.index for frame in seen if isinstance(frame, follow.CandidateSettled)]
    assert (events, settled) == ([1, 2, 3], [1, 0])
    assert [notice.state for notice in notices] == ["reconnecting", "reconnected"]


@pytest.mark.parametrize(
    "lost",
    [
        _closed(1013, "registry_unavailable"),
        _closed(1011),
        ConnectionClosedOK(Close(1000, ""), None),
        TimeoutError(),
        OSError("reset"),
    ],
    ids=["try-again-later", "internal-error", "closed-before-the-end", "timeout", "os"],
)
def test_a_connection_lost_before_the_run_ends_is_followed_again(lost: BaseException) -> None:
    engine = _Engine([lost], [ENDED])

    ended, _ = _follow(engine)

    assert (ended.state, engine.connects) == ("complete", 2)


def test_a_transient_handshake_refusal_is_tried_again() -> None:
    engine = _Engine(_refused(503), [ENDED])

    ended, _ = _follow(engine)

    assert ended.state == "complete"


@pytest.mark.parametrize(
    ("reason", "code"),
    [("run_not_found", "run_not_found"), ("runs_off", "runs_off"), ("", "run_follow_refused")],
)
def test_a_follow_the_engine_refuses_ends_with_its_code(reason: str, code: str) -> None:
    engine = _Engine([_closed(1008, reason)])

    with pytest.raises(ExecutionError) as raised:
        _follow(engine)

    assert (raised.value.code, engine.connects) == (code, 1)


@pytest.mark.parametrize(
    "refusal",
    [
        _refused(401),
        _refused(403),
        _refused(302, {"Location": "https://access.example/login?kid=" + "a" * 64}),
        _closed(1008, "identity_required"),
    ],
    ids=["401", "403", "access", "identity"],
)
def test_a_follow_that_outlives_the_sign_in_says_how_to_pick_the_run_up(
    refusal: BaseException,
) -> None:
    engine = _Engine([_event(0, 1), _closed(1006)], refusal)

    with pytest.raises(AuthenticationError) as raised:
        _follow(engine, detached=True)

    assert raised.value.code == "login_expired"
    assert "still going" in raised.value.message
    assert f"sf.runs.get({RUN_ID!r}).wait()" in (raised.value.hint or "")


def test_an_attached_run_whose_follow_ends_says_it_stops_unless_followed_again() -> None:
    engine = _Engine(_refused(401))

    with pytest.raises(AuthenticationError) as raised:
        _follow(engine, detached=False)

    assert "2 minutes" in raised.value.message


def test_a_follow_whose_outage_outlasts_the_budget_ends() -> None:
    engine = _Engine(*([OSError("down")] * 50))

    with pytest.raises(ExecutionError) as raised:
        _follow(engine, budget_s=0.0)

    assert (raised.value.code, raised.value.permanent) == ("websocket_disconnected", False)
    assert RUN_ID in raised.value.message


def test_an_event_that_does_not_decode_is_dropped_and_the_follow_goes_on() -> None:
    broken = _frame("candidate.event", index=0, event={"type": "ai.url4.log", "sequence": "2"})
    engine = _Engine([_event(0, 1), broken, _event(0, 3), ENDED])

    _, seen = _follow(engine)

    assert [frame.event.sequence for frame in seen if isinstance(frame, follow.CandidateEvent)] == [
        1,
        3,
    ]


@pytest.mark.parametrize(
    "frame",
    ["not json", "[]", json.dumps({"type": "candidate.settled", "index": "0"})],
    ids=["text", "array", "index"],
)
def test_a_malformed_frame_is_a_contract_error(frame: str) -> None:
    with pytest.raises(ExecutionError) as raised:
        _follow(_Engine([frame]))

    assert raised.value.code == "engine_contract_error"


def test_a_frame_of_a_kind_this_client_does_not_know_is_skipped() -> None:
    engine = _Engine([_frame("candidate.progress", index=0), ENDED])

    _, seen = _follow(engine)

    assert seen == []


class _AsyncSocket:
    def __init__(self, script: list[str | BaseException]) -> None:
        self._socket = _Socket(script)

    async def recv(self) -> str:
        return self._socket.recv()


class _AsyncEngine:
    def __init__(self, *connections: list[str | BaseException]) -> None:
        self._connections = list(connections)
        self.connects = 0

    def connect(self) -> _AsyncOpened:
        self.connects += 1
        return _AsyncOpened(self._connections.pop(0))


class _AsyncOpened:
    def __init__(self, script: list[str | BaseException]) -> None:
        self._script = script

    async def __aenter__(self) -> _AsyncSocket:
        return _AsyncSocket(self._script)

    async def __aexit__(self, *exc: object) -> None:
        return None


@pytest.mark.asyncio
async def test_the_async_follower_awaits_each_frame_and_reconnects_the_same_way() -> None:
    engine = _AsyncEngine([_event(0, 1), _closed(1006)], [_event(0, 1), _settled(0), ENDED])
    seen: list[object] = []

    async def observe(frame: object) -> None:
        seen.append(frame)

    ended = await follow.follow_async(
        engine.connect, RUN_ID, observe, detached=False, budget_s=5.0, base_delay_s=0.0
    )

    assert ended.state == "complete"
    assert [type(frame).__name__ for frame in seen] == ["CandidateEvent", "CandidateSettled"]
