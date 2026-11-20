"""OME-1141: recovery time starts at failure, not at Evaluation start.

Since E5 P2 one follower per Run reconnects (`run_follow.py`), within the Engine's 120 s orphan
grace. The same recovery window decides when it gives up: one 90 s budget per outage, kept across
flapping connections, renewed only after a connection that stayed up.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Sequence
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any

import pytest
from websockets.exceptions import ConnectionClosedError
from websockets.frames import Close

from screamingface._engine import reconnect, run_follow
from screamingface.errors import ExecutionError

RUN_ID = "run_" + "9" * 32


@dataclass
class Clock:
    now: float = 0.0
    sleeps: list[float] = field(default_factory=list)

    def monotonic(self) -> float:
        return self.now

    def sleep(self, delay: float) -> None:
        self.sleeps.append(delay)
        self.now += delay

    async def asleep(self, delay: float) -> None:
        self.sleep(delay)


def _event(sequence: int) -> str:
    payload = {
        "specversion": "1.0",
        "id": str(sequence),
        "source": "/trace/test/node/root",
        "time": "2026-09-09T12:00:00Z",
        "subject": "test",
        "type": "ai.url4.log",
        "datacontenttype": "application/json",
        "sequence": str(sequence),
        "sequencetype": "Integer",
        "data": {"severity_text": "INFO", "severity_number": 9, "body": "working"},
    }
    return json.dumps({"type": "candidate.event", "index": 0, "event": payload})


_SETTLED = json.dumps(
    {
        "type": "candidate.settled",
        "index": 0,
        "state": "succeeded",
        "attempt_id": "t",
        "error_code": None,
        "record": None,
    }
)
_ENDED = json.dumps({"type": "run.ended", "state": "complete", "stopped_by": None})


class _Socket:
    def __init__(self, frames: list[str | BaseException], clock: Clock, duration: float):
        self._frames = frames
        self._clock = clock
        self._duration = duration

    def recv(self, timeout: float | None = None) -> str:
        item = self._frames.pop(0)
        if isinstance(item, BaseException):
            self._clock.now += self._duration
            raise item
        return item

    async def arecv(self) -> str:
        return self.recv()


class Script:
    """Fake only I/O and time; the follower's own reconnect decisions are real."""

    def __init__(self, clock: Clock, steps: Sequence[tuple[float, str]], asynchronous: bool):
        self.clock = clock
        self.steps = iter(steps)
        self.asynchronous = asynchronous
        self.connects = 0
        self.sequence = 0

    def connect(self) -> Any:
        self.connects += 1
        duration, action = next(self.steps)
        if action == "refused":
            self.clock.now += duration
            raise OSError("connection refused")
        self.sequence += 1
        frames: list[str | BaseException] = [_event(self.sequence)]
        if action == "close":
            frames.append(ConnectionClosedError(None, Close(1011, "keepalive ping timeout"), None))
        else:
            frames += [_SETTLED, _ENDED]
        socket = _Socket(frames, self.clock, duration)
        return _Opened(SimpleNamespace(recv=socket.arecv) if self.asynchronous else socket)


class _Opened:
    def __init__(self, socket: Any) -> None:
        self._socket = socket

    def __enter__(self) -> Any:
        return self._socket

    def __exit__(self, *exc: object) -> None:
        return None

    async def __aenter__(self) -> Any:
        return self._socket

    async def __aexit__(self, *exc: object) -> None:
        return None


@pytest.fixture(params=[False, True], ids=["sync", "async"])
def harness(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch):
    clock = Clock()
    monkeypatch.setattr(run_follow, "time", clock)
    monkeypatch.setattr(
        run_follow, "asyncio", SimpleNamespace(sleep=clock.asleep, timeout=asyncio.timeout)
    )
    monkeypatch.setattr(reconnect.random, "random", lambda: 1.0)
    return SimpleNamespace(clock=clock, asynchronous=request.param)


async def _run(harness: Any, steps: Sequence[tuple[float, str]], *, budget_s: float = 90.0):
    script = Script(harness.clock, steps, harness.asynchronous)
    harness.script = script
    settled: list[object] = []
    options = {"detached": False, "budget_s": budget_s, "base_delay_s": 0.5}
    if harness.asynchronous:
        ended = await run_follow.follow_async(script.connect, RUN_ID, settled.append, **options)
    else:
        ended = run_follow.follow_sync(script.connect, RUN_ID, settled.append, **options)
    return ended, settled


@pytest.mark.asyncio
async def test_late_keepalive_failure_resumes_same_run(harness):
    ended, settled = await _run(harness, [(1085, "close"), (0, "complete")])
    assert ended.state == "complete"
    assert harness.script.connects == 2
    assert [type(frame).__name__ for frame in settled][-1] == "CandidateSettled"
    assert harness.clock.sleeps == [0.5]


@pytest.mark.asyncio
async def test_late_failure_retains_one_budget_across_failed_attempts(harness):
    with pytest.raises(ExecutionError, match="keepalive ping timeout|OSError") as caught:
        await _run(harness, [(1085, "close"), (45, "refused"), (45, "refused")])
    assert caught.value.code == "websocket_disconnected"
    assert harness.script.connects == 3
    assert harness.clock.sleeps == [0.5, 1.0]


@pytest.mark.asyncio
async def test_flapping_attachments_do_not_restart_budget(harness):
    with pytest.raises(ExecutionError):
        await _run(harness, [(1085, "close"), (45, "close"), (45, "close")])
    assert harness.script.connects == 3
    assert harness.clock.sleeps == [0.5, 1.0]


@pytest.mark.asyncio
@pytest.mark.parametrize("stable_seconds", [90, 1085])
async def test_stable_recovery_restores_budget_and_backoff(harness, stable_seconds):
    ended, _ = await _run(harness, [(10, "close"), (stable_seconds, "close"), (0, "complete")])
    assert ended.state == "complete"
    assert harness.clock.sleeps == [0.5, 0.5]


@pytest.mark.asyncio
async def test_first_connection_failure_starts_budget_when_observed(harness):
    ended, _ = await _run(harness, [(100, "refused"), (0, "complete")])
    assert ended.state == "complete"
    assert harness.script.connects == 2


@pytest.mark.asyncio
async def test_zero_budget_does_not_retry(harness):
    with pytest.raises(ExecutionError, match="keepalive ping timeout"):
        await _run(harness, [(1085, "close")], budget_s=0)
    assert harness.script.connects == 1
    assert harness.clock.sleeps == []


@pytest.mark.asyncio
async def test_owner_abort_does_not_retry_or_sweep_again(harness):
    """A follow the Engine refused (1008) is not retried: retrying cannot change the answer."""
    script_steps = [(0, "refused-by-engine")]

    def refused_connect() -> Any:
        harness.script.connects += 1
        raise ConnectionClosedError(Close(1008, "run_not_found"), None, None)

    script = Script(harness.clock, script_steps, harness.asynchronous)
    harness.script = script
    options = {"detached": False, "budget_s": 90.0, "base_delay_s": 0.5}
    with pytest.raises(ExecutionError) as caught:
        if harness.asynchronous:

            class _Refusing:
                async def __aenter__(self) -> Any:
                    return refused_connect()

                async def __aexit__(self, *exc: object) -> None:
                    return None

            await run_follow.follow_async(_Refusing, RUN_ID, lambda _f: None, **options)
        else:
            run_follow.follow_sync(refused_connect, RUN_ID, lambda _f: None, **options)
    assert caught.value.code == "run_not_found"
    assert script.connects == 1
    assert harness.clock.sleeps == []


@pytest.mark.asyncio
async def test_short_reconnection_exhausts_at_exact_deadline(harness):
    # INVARIANT: the 0.5s backoff plus 89.5s connection uses the original 90s window;
    # that socket has not stayed healthy long enough to earn another recovery budget.
    with pytest.raises(ExecutionError, match="keepalive ping timeout") as caught:
        await _run(harness, [(1085, "close"), (89.5, "close")])
    assert caught.value.code == "websocket_disconnected"
    assert harness.script.connects == 2
    assert harness.clock.now == 1175
