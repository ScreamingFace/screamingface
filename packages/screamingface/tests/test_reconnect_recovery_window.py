"""OME-1141: recovery time starts at failure, not at Evaluation start."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, Mock

import pytest
from websockets.exceptions import ConnectionClosedError
from websockets.frames import Close

from screamingface._access.base import _TransportAuth
from screamingface._engine import transport as module
from screamingface._engine.run_lifecycle import _Lifecycle
from screamingface._engine.trace import new_trace_context
from screamingface._evaluation.model import _compiled_candidate, _compiled_operation
from screamingface.errors import ExecutionError


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


def _frame(kind: str, data: dict[str, object], sequence: int) -> str:
    return json.dumps(
        {
            "specversion": "1.0",
            "id": str(sequence),
            "source": "/trace/test/node/root",
            "time": "2026-09-09T12:00:00Z",
            "subject": "test",
            "type": kind,
            "datacontenttype": "application/json",
            "sequence": str(sequence),
            "sequencetype": "Integer",
            "data": data,
        }
    )


class Script:
    """Fake only I/O and time; retain real lifecycle, cursor and reconnect decisions."""

    def __init__(self, clock: Clock, steps: list[tuple[float, str]], asynchronous: bool):
        self.clock = clock
        self.steps = iter(steps)
        self.asynchronous = asynchronous
        self.urls: list[str] = []
        self.attaches: list[dict[str, object]] = []
        self.sequence = 0

    def connect(self, url: str, **kwargs: object) -> MagicMock:
        self.urls.append(url)
        duration, action = next(self.steps)
        if action == "refused":
            self.clock.now += duration
            raise OSError("connection refused")
        socket = MagicMock(subprotocol="cloudevents.json")
        receiver = self.receive(duration, action)
        socket.recv.side_effect = lambda **kw: next(receiver)
        socket.send.side_effect = self.send
        if self.asynchronous:
            socket.recv = AsyncMock(side_effect=lambda: next(receiver))
            socket.send = AsyncMock(side_effect=self.send)
        context = MagicMock()
        context.__enter__.return_value = socket
        context.__aenter__.return_value = socket
        return context

    def send(self, message: str) -> None:
        event = json.loads(message)
        if event["type"] == "ai.url4.attach":
            self.attaches.append(event["data"])

    def receive(self, duration: float, action: str):
        self.sequence += 1
        if self.sequence == 1:
            yield _frame("ai.url4.started", {"url4": "(@)!'hi'"}, self.sequence)
        else:
            yield _frame(
                "ai.url4.log",
                {"severity_text": "INFO", "severity_number": 9, "body": "working"},
                self.sequence,
            )
        self.clock.now += duration
        if action == "close":
            raise ConnectionClosedError(None, Close(1011, "keepalive ping timeout"))
        self.sequence += 1
        yield _frame(
            "ai.url4.result", {"body": "complete", "media_type": "text/plain"}, self.sequence
        )
        self.sequence += 1
        yield _frame("ai.url4.terminated", {"status": "succeeded", "error": None}, self.sequence)


@pytest.fixture(params=[False, True], ids=["sync", "async"])
def harness(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch):
    asynchronous = request.param
    clock = Clock()
    monkeypatch.setattr(module, "time", clock)
    monkeypatch.setattr(
        module, "asyncio", SimpleNamespace(sleep=clock.asleep, wait_for=asyncio.wait_for)
    )
    monkeypatch.setattr(module.random, "random", lambda: 1.0)
    auth = Mock(spec=_TransportAuth)
    auth.websocket_headers.return_value = {}
    auth.websocket_headers_async = AsyncMock(return_value={})
    cls = module.AsyncUrl4CloudTransport if asynchronous else module.Url4CloudTransport
    client = cls("http://example.invalid", caller_auth=auth)
    sweep = AsyncMock() if asynchronous else Mock()
    monkeypatch.setattr(client, "_sweep_after_disconnect", sweep)
    start = AsyncMock() if asynchronous else Mock()
    monkeypatch.setattr(module, "_start_async" if asynchronous else "_start_sync", start)
    return SimpleNamespace(
        client=client, clock=clock, asynchronous=asynchronous, sweep=sweep, start=start
    )


async def _run(harness, monkeypatch: pytest.MonkeyPatch, steps: list[tuple[float, str]]):
    script = Script(harness.clock, steps, harness.asynchronous)
    harness.script = script
    ws_module = module.async_ws if harness.asynchronous else module.sync_ws
    monkeypatch.setattr(ws_module, "connect", script.connect)
    candidate = _compiled_candidate(
        name="model",
        kind="model",
        models=("provider/model",),
        url4="(@)!'hi'",
        operations=(_compiled_operation(id="model", kind="model", label="answer", depends_on=()),),
    )
    args = (_Lifecycle(candidate), ["same-token"], candidate, None, 0.0, new_trace_context())
    try:
        if harness.asynchronous:
            return await harness.client._run_reconnecting(*args)
        return harness.client._run_reconnecting(*args)
    finally:
        if harness.asynchronous:
            await harness.client.close()
        else:
            harness.client.close()


@pytest.mark.asyncio
async def test_late_keepalive_failure_resumes_same_run(harness, monkeypatch):
    outcome = await _run(harness, monkeypatch, [(1085, "close"), (0, "complete")])
    assert outcome.result_body == "complete"
    assert len(harness.script.urls) == 2
    assert len(set(harness.script.urls)) == 1
    assert harness.script.attaches == [{"from_sequence": None}, {"from_sequence": 2}]
    harness.start.assert_called_once()
    harness.sweep.assert_not_called()
    assert harness.clock.sleeps == [0.5]


@pytest.mark.asyncio
async def test_late_failure_retains_one_budget_across_failed_attempts(harness, monkeypatch):
    with pytest.raises(ExecutionError, match="websocket|WebSocket") as caught:
        await _run(harness, monkeypatch, [(1085, "close"), (45, "refused"), (45, "refused")])
    assert caught.value.code == "websocket_disconnected"
    assert len(harness.script.urls) == 3
    assert harness.clock.sleeps == [0.5, 1.0]
    harness.sweep.assert_called_once()


@pytest.mark.asyncio
async def test_flapping_attachments_do_not_restart_budget(harness, monkeypatch):
    with pytest.raises(ExecutionError):
        await _run(harness, monkeypatch, [(1085, "close"), (45, "close"), (45, "close")])
    assert len(harness.script.attaches) == 3
    assert harness.clock.sleeps == [0.5, 1.0]
    harness.sweep.assert_called_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("stable_seconds", [90, 1085])
async def test_stable_recovery_restores_budget_and_backoff(harness, monkeypatch, stable_seconds):
    outcome = await _run(
        harness, monkeypatch, [(10, "close"), (stable_seconds, "close"), (0, "complete")]
    )
    assert outcome.result_body == "complete"
    assert harness.clock.sleeps == [0.5, 0.5]
    harness.sweep.assert_not_called()


@pytest.mark.asyncio
async def test_first_connection_failure_starts_budget_when_observed(harness, monkeypatch):
    outcome = await _run(harness, monkeypatch, [(100, "refused"), (0, "complete")])
    assert outcome.result_body == "complete"
    assert harness.script.attaches == [{"from_sequence": None}]
    harness.start.assert_called_once()


@pytest.mark.asyncio
async def test_zero_budget_does_not_retry(harness, monkeypatch):
    harness.client._reconnect_budget_s = 0
    with pytest.raises(ExecutionError, match="keepalive ping timeout"):
        await _run(harness, monkeypatch, [(1085, "close")])
    assert len(harness.script.urls) == 1
    assert harness.clock.sleeps == []
    harness.sweep.assert_called_once()


@pytest.mark.asyncio
async def test_owner_abort_does_not_retry_or_sweep_again(harness, monkeypatch):
    harness.client._aborted = True
    with pytest.raises(ExecutionError):
        await _run(harness, monkeypatch, [(1085, "close")])
    assert len(harness.script.urls) == 1
    assert harness.clock.sleeps == []
    harness.sweep.assert_not_called()


@pytest.mark.asyncio
async def test_short_reconnection_exhausts_at_exact_deadline(harness, monkeypatch):
    # INVARIANT: the 0.5s backoff plus 89.5s connection uses the original 90s window;
    # that socket has not stayed healthy long enough to earn another recovery budget.
    with pytest.raises(ExecutionError, match="keepalive ping timeout") as caught:
        await _run(harness, monkeypatch, [(1085, "close"), (89.5, "close")])
    assert caught.value.code == "websocket_disconnected"
    assert len(harness.script.urls) == 2
    assert harness.clock.now == 1175
    harness.sweep.assert_called_once()
