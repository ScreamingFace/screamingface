"""Reconnect-handshake outcomes the OME-1016 plan named but did not test (spec 2026-09-28).

FEATURE: OME-1016 — a deploy mid-Run must not cost the researcher the Run.
STORY: as a researcher whose Evaluation is running during an engine deploy, a dead
credential fails at once, an expired Access session asks me to log in and then carries on,
and a proxy's 5xx while the App restarts is just another reconnect.

The stub engine (`_reconnect_engine.py`) closes the first stream with 1012 after frames
1..2, then answers the reconnect handshake from a script.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncGenerator, Generator, Mapping

import httpx
import pytest
from _reconnect_engine import RESULT_BODY, StubEngine, candidate, stub_engine

from screamingface._access.base import _TransportAuth
from screamingface._engine.transport import AsyncUrl4CloudTransport, Url4CloudTransport
from screamingface.errors import ExecutionError
from screamingface.events import Event

# WHY a generous bound and not the budget itself: the test proves "no retry loop until the
# budget ends". Any value far below the 90 s budget proves that and stays stable on CI.
_FAST_S = 10.0


class _CountingAuth(_TransportAuth):
    def __init__(self, *, login_s: float = 0.0) -> None:
        self.reauthentications = 0
        self.timeouts: list[float] = []
        # How long each "browser login" takes — a real one can take minutes.
        self._login_s = login_s

    def reauthenticate(self, *, timeout: float = 300.0) -> None:
        self.reauthentications += 1
        self.timeouts.append(timeout)
        time.sleep(self._login_s)

    async def reauthenticate_async(self, *, timeout: float = 300.0) -> None:
        self.reauthentications += 1
        self.timeouts.append(timeout)
        await asyncio.sleep(self._login_s)

    def websocket_headers(self) -> Mapping[str, str]:
        return {}

    async def websocket_headers_async(self) -> Mapping[str, str]:
        return {}

    def close(self) -> None:
        pass

    def sync_auth_flow(
        self, request: httpx.Request
    ) -> Generator[httpx.Request, httpx.Response, None]:
        yield request

    async def async_auth_flow(
        self, request: httpx.Request
    ) -> AsyncGenerator[httpx.Request, httpx.Response]:
        yield request


def _sync_run(
    engine: StubEngine, auth: _TransportAuth, events: list[Event], *, budget_s: float = 90.0
) -> object:
    transport = Url4CloudTransport(
        engine.url, auth, reconnect_budget_s=budget_s, reconnect_base_delay_s=0.01
    )
    try:
        return transport.run(candidate(), events.append)
    finally:
        transport.close()


async def _async_run(
    engine: StubEngine, auth: _TransportAuth, events: list[Event], *, budget_s: float = 90.0
) -> object:
    transport = AsyncUrl4CloudTransport(
        engine.url, auth, reconnect_budget_s=budget_s, reconnect_base_delay_s=0.01
    )
    try:
        return await transport.run(candidate(), events.append)
    finally:
        await transport.close()


# --- R1: a real auth rejection on the reconnect is FATAL at once (spec 2026-08-26 D5) -----


@pytest.mark.parametrize("status", [401, 403])
def test_reconnect_rejected_by_the_engine_fails_fast_and_sweeps(status: int) -> None:
    # INVARIANT: a non-Access 401/403 means dead credentials. Retrying cannot help, and
    # the started Run must be stopped rather than orphaned (G3).
    with stub_engine(status) as engine:
        began = time.monotonic()
        with pytest.raises(ExecutionError) as caught:
            _sync_run(engine, _CountingAuth(), [])
        elapsed = time.monotonic() - began

    assert caught.value.code == "websocket_disconnected"
    assert "InvalidStatus" in str(caught.value)
    assert len(engine.state.handshake_tickets) == 2  # the first stream + ONE reconnect
    assert engine.state.deletes == 1  # the sweep stopped the started Run
    assert elapsed < _FAST_S


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [401, 403])
async def test_async_reconnect_rejected_by_the_engine_fails_fast_and_sweeps(status: int) -> None:
    with stub_engine(status) as engine:
        began = time.monotonic()
        with pytest.raises(ExecutionError) as caught:
            await _async_run(engine, _CountingAuth(), [])
        elapsed = time.monotonic() - began

    assert caught.value.code == "websocket_disconnected"
    assert len(engine.state.handshake_tickets) == 2
    assert engine.state.deletes == 1
    assert elapsed < _FAST_S


# --- R2: an Access challenge on the reconnect re-authenticates, then resumes -------------


def _assert_resumed_without_loss(engine: StubEngine, events: list[Event]) -> None:
    sequences = [event.sequence for event in events]
    # INVARIANT: the caller sees every frame once, in order — no gap across the outage
    # and no duplicate from the replay.
    assert sequences == sorted(set(sequences))
    assert {1, 2, 3} <= set(sequences)
    assert engine.state.resume_cursors[-1] == 3


def test_access_challenge_during_reconnect_resumes_on_the_same_capability() -> None:
    auth = _CountingAuth()
    events: list[Event] = []
    with stub_engine("access") as engine:
        outcome = _sync_run(engine, auth, events)

    assert getattr(outcome, "result_body") == RESULT_BODY
    assert auth.reauthentications == 1
    tickets = engine.state.handshake_tickets
    # WHY the SAME capability: a fresh mint names a NEW topic that holds none of this
    # Run's frames (spec 2026-09-28 F1).
    assert tickets[-1] == tickets[0]
    _assert_resumed_without_loss(engine, events)


@pytest.mark.asyncio
async def test_async_access_challenge_during_reconnect_resumes_on_the_same_capability() -> None:
    auth = _CountingAuth()
    events: list[Event] = []
    with stub_engine("access") as engine:
        outcome = await _async_run(engine, auth, events)

    assert getattr(outcome, "result_body") == RESULT_BODY
    assert auth.reauthentications == 1
    tickets = engine.state.handshake_tickets
    assert tickets[-1] == tickets[0]
    _assert_resumed_without_loss(engine, events)


# --- R3: a 5xx on the reconnect handshake is a transient outage (spec §6 S3 BACKOFF) -----


@pytest.mark.parametrize("status", [502, 503])
def test_reconnect_handshake_5xx_backs_off_and_resumes(status: int) -> None:
    events: list[Event] = []
    with stub_engine(status, status) as engine:
        outcome = _sync_run(engine, _CountingAuth(), events)

    assert getattr(outcome, "result_body") == RESULT_BODY
    assert len(engine.state.handshake_tickets) == 4
    assert engine.state.deletes == 0  # nothing was swept
    _assert_resumed_without_loss(engine, events)


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [502, 503])
async def test_async_reconnect_handshake_5xx_backs_off_and_resumes(status: int) -> None:
    events: list[Event] = []
    with stub_engine(status) as engine:
        outcome = await _async_run(engine, _CountingAuth(), events)

    assert getattr(outcome, "result_body") == RESULT_BODY
    assert engine.state.deletes == 0
    _assert_resumed_without_loss(engine, events)


def test_reconnect_handshake_5xx_still_ends_when_the_budget_is_spent() -> None:
    # INVARIANT: a 5xx outage spends the SAME budget as a dropped socket — it is not an
    # unbounded retry.
    with stub_engine(*([503] * 200)) as engine:
        transport = Url4CloudTransport(
            engine.url, _CountingAuth(), reconnect_budget_s=0.3, reconnect_base_delay_s=0.01
        )
        try:
            with pytest.raises(ExecutionError) as caught:
                transport.run(candidate(), None)
        finally:
            transport.close()

    assert caught.value.code == "websocket_disconnected"
    assert engine.state.deletes == 1  # budget exhausted → sweep (G3)


@pytest.mark.asyncio
async def test_async_reconnect_handshake_5xx_still_ends_when_the_budget_is_spent() -> None:
    with stub_engine(*([503] * 200)) as engine:
        with pytest.raises(ExecutionError) as caught:
            await _async_run(engine, _CountingAuth(), [], budget_s=0.3)

    assert caught.value.code == "websocket_disconnected"
    assert engine.state.deletes == 1


@pytest.mark.parametrize("status", [503, 501, 505])
def test_a_5xx_on_the_first_handshake_stays_fatal(status: int) -> None:
    # INVARIANT (spec R3, second half; Q2): before the Run starts nothing is billed and
    # nothing needs a resume, so a refused FIRST handshake fails at once.
    with stub_engine(first=status) as engine:
        with pytest.raises(ExecutionError) as caught:
            _sync_run(engine, _CountingAuth(), [])

    assert caught.value.code == "websocket_disconnected"
    assert len(engine.state.handshake_tickets) == 1
    assert engine.state.started_topic is None


@pytest.mark.parametrize("status", [501, 505])
def test_a_non_transient_5xx_on_the_reconnect_is_fatal(status: int) -> None:
    # WHY: 501/505 say the server cannot speak this protocol; waiting does not change that.
    with stub_engine(status) as engine:
        with pytest.raises(ExecutionError) as caught:
            _sync_run(engine, _CountingAuth(), [])

    assert caught.value.code == "websocket_disconnected"
    assert len(engine.state.handshake_tickets) == 2
    assert engine.state.deletes == 1


# --- The post-start Access re-login is bounded (review fix 1) ------------------------------
#
# WHY: while no client is attached the engine's orphan reaper (`orphan_grace_s` = 120 s)
# counts down. An unbounded re-login — or an edge that challenges forever — outlives it.


def test_a_repeatedly_challenging_edge_stops_after_the_challenge_cap() -> None:
    auth = _CountingAuth()
    with stub_engine("access", "access", "access", "access") as engine:
        with pytest.raises(ExecutionError) as caught:
            _sync_run(engine, auth, [])

    assert caught.value.code == "websocket_disconnected"
    assert auth.reauthentications == 2  # _MAX_RECONNECT_CHALLENGES
    assert engine.state.deletes == 1


@pytest.mark.asyncio
async def test_async_a_repeatedly_challenging_edge_stops_after_the_challenge_cap() -> None:
    auth = _CountingAuth()
    with stub_engine("access", "access", "access", "access") as engine:
        with pytest.raises(ExecutionError) as caught:
            await _async_run(engine, auth, [])

    assert caught.value.code == "websocket_disconnected"
    assert auth.reauthentications == 2
    assert engine.state.deletes == 1


def test_a_re_login_is_bounded_by_the_outage_budget() -> None:
    # The first login is admitted with at most the budget left; it outlasts it, so the
    # next challenge is refused without a second prompt.
    auth = _CountingAuth(login_s=0.5)
    with stub_engine("access", "access") as engine:
        with pytest.raises(ExecutionError) as caught:
            _sync_run(engine, auth, [], budget_s=0.3)

    assert caught.value.code == "websocket_disconnected"
    assert auth.reauthentications == 1
    assert 0 < auth.timeouts[0] <= 0.3
    assert engine.state.deletes == 1


@pytest.mark.asyncio
async def test_async_a_re_login_is_bounded_by_the_outage_budget() -> None:
    auth = _CountingAuth(login_s=0.5)
    with stub_engine("access", "access") as engine:
        with pytest.raises(ExecutionError) as caught:
            await _async_run(engine, auth, [], budget_s=0.3)

    assert caught.value.code == "websocket_disconnected"
    assert auth.reauthentications == 1
    assert 0 < auth.timeouts[0] <= 0.3
    assert engine.state.deletes == 1
