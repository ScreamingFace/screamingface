"""One Run's failure stops that Run only (spec 2026-09-28 sdk-run-isolation, OME-1071).

FEATURE: OME-1071 — a failure in one Candidate's Run must not destroy its healthy siblings.
STORY: as a researcher running several Candidates on one Client, when the engine refuses
one Run's reconnect, only that Run stops; the others keep running and return results.

The stub engine (`_isolation_engine.py`) serves several Runs at once and records which
capability each `DELETE /` named — the engine stops exactly that topic (spec E1).
"""

from __future__ import annotations

import asyncio
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from http import HTTPStatus

import pytest
from _isolation_engine import (
    RunPlan,
    StubEngine,
    candidate,
    isolation_engine,
    result_body,
    url4_of,
)

from screamingface._engine.transport import AsyncUrl4CloudTransport, Url4CloudTransport
from screamingface.errors import ExecutionError


def _wait_until_started(engine: StubEngine, name: str) -> str:
    """The capability of `name`'s Run, once the engine has started it."""
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        token = engine.state.capability_of(url4_of(name))
        if token is not None:
            return token
        time.sleep(0.01)
    raise AssertionError(f"the Run of {name!r} never started")


def _refused_and_healthy(status: int) -> tuple[dict[str, RunPlan], threading.Event]:
    hold = threading.Event()
    return (
        {
            url4_of("refused"): RunPlan(first="drop", reconnects=[status]),
            url4_of("healthy"): RunPlan(hold=hold),
        },
        hold,
    )


# --- C2: a fatal handshake refusal stops only its own Run -------------------------------


@pytest.mark.parametrize("status", [401, 403])
def test_a_fatal_reconnect_refusal_stops_only_its_own_run(status: int) -> None:
    # INVARIANT (spec 4.1 C2): the refusal is about ONE stream's handshake. The sibling has
    # its own socket, so it must not be stopped — it must finish and return its result.
    plans, hold = _refused_and_healthy(status)
    with isolation_engine(plans) as engine:
        transport = Url4CloudTransport(engine.url, reconnect_base_delay_s=0.01)
        try:
            with ThreadPoolExecutor(max_workers=1) as pool:
                healthy = pool.submit(transport.run, candidate("healthy"), None)
                _wait_until_started(engine, "healthy")
                with pytest.raises(ExecutionError) as caught:
                    transport.run(candidate("refused"), None)
                # The sibling is still mid-stream here: it was held open until now.
                hold.set()
                outcome = healthy.result(timeout=10)
        finally:
            transport.close()

    assert caught.value.code == "websocket_disconnected"
    assert outcome.result_body == result_body(url4_of("healthy"))
    assert engine.state.deleted == [engine.state.capability_of(url4_of("refused"))]


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [401, 403])
async def test_async_a_fatal_reconnect_refusal_stops_only_its_own_run(status: int) -> None:
    plans, hold = _refused_and_healthy(status)
    with isolation_engine(plans) as engine:
        transport = AsyncUrl4CloudTransport(engine.url, reconnect_base_delay_s=0.01)
        try:
            healthy = asyncio.create_task(transport.run(candidate("healthy"), None))
            await asyncio.to_thread(_wait_until_started, engine, "healthy")
            with pytest.raises(ExecutionError) as caught:
                await transport.run(candidate("refused"), None)
            hold.set()
            outcome = await asyncio.wait_for(healthy, timeout=10)
        finally:
            await transport.close()

    assert caught.value.code == "websocket_disconnected"
    assert outcome.result_body == result_body(url4_of("healthy"))
    assert engine.state.deleted == [engine.state.capability_of(url4_of("refused"))]


# --- B1: an owner abort is over once its Runs are gone ----------------------------------


def test_a_run_after_an_owner_abort_reconnects_again() -> None:
    # INVARIANT (spec 4.3, B1): `_aborted` belongs to ONE abort. A Run started later on the
    # same Client — a notebook re-runs `evaluate` after a Ctrl-C — must reconnect after a
    # lost stream, not fail at once and leave its Run spending with nobody attached.
    plans = {url4_of("later"): RunPlan(first="drop")}
    with isolation_engine(plans) as engine:
        transport = Url4CloudTransport(engine.url, reconnect_base_delay_s=0.01)
        try:
            transport.cancel_active()
            outcome = transport.run(candidate("later"), None)
        finally:
            transport.close()

    token = engine.state.capability_of(url4_of("later"))
    assert outcome.result_body == result_body(url4_of("later"))
    assert token is not None
    assert engine.state.handshakes[token] == 2  # the first stream + one resume
    assert engine.state.deleted == []


@pytest.mark.asyncio
async def test_async_a_run_after_an_owner_abort_reconnects_again() -> None:
    plans = {url4_of("later"): RunPlan(first="drop")}
    with isolation_engine(plans) as engine:
        transport = AsyncUrl4CloudTransport(engine.url, reconnect_base_delay_s=0.01)
        try:
            await transport.cancel_active()
            outcome = await transport.run(candidate("later"), None)
        finally:
            await transport.close()

    token = engine.state.capability_of(url4_of("later"))
    assert outcome.result_body == result_body(url4_of("later"))
    assert token is not None
    assert engine.state.handshakes[token] == 2
    assert engine.state.deleted == []


# --- A failed own-Run stop never hides the Run's own error --------------------------------


def test_a_failed_own_run_stop_is_logged_not_raised(caplog: pytest.LogCaptureFixture) -> None:
    # WHY: the caller must learn WHY the Run ended (the refused handshake), not that the
    # best-effort stop behind it also failed. The stop failure is a log line.
    plans = {url4_of("refused"): RunPlan(first="drop", reconnects=[401])}
    with isolation_engine(plans, delete_status=HTTPStatus.INTERNAL_SERVER_ERROR) as engine:
        transport = Url4CloudTransport(engine.url, reconnect_base_delay_s=0.01)
        try:
            with pytest.raises(ExecutionError) as caught:
                transport.run(candidate("refused"), None)
        finally:
            transport.close()

    assert caught.value.code == "websocket_disconnected"
    assert len(engine.state.deleted) == 1
    assert "Stopping the SF Engine Run also failed" in caplog.text


@pytest.mark.asyncio
async def test_async_a_failed_own_run_stop_is_logged_not_raised(
    caplog: pytest.LogCaptureFixture,
) -> None:
    plans = {url4_of("refused"): RunPlan(first="drop", reconnects=[401])}
    with isolation_engine(plans, delete_status=HTTPStatus.INTERNAL_SERVER_ERROR) as engine:
        transport = AsyncUrl4CloudTransport(engine.url, reconnect_base_delay_s=0.01)
        try:
            with pytest.raises(ExecutionError) as caught:
                await transport.run(candidate("refused"), None)
        finally:
            await transport.close()

    assert caught.value.code == "websocket_disconnected"
    assert len(engine.state.deleted) == 1
    assert "Stopping the SF Engine Run also failed" in caplog.text


# --- B1 (review): after an owner abort, a later Run stops its OWN Run -------------------


def _lost_later() -> dict[str, RunPlan]:
    # Every reconnect is refused with a transient 503, so the outage budget runs out.
    return {url4_of("later"): RunPlan(first="drop", reconnects=[503] * 500)}


def test_a_run_after_an_owner_abort_stops_its_own_run_when_its_budget_ends() -> None:
    # INVARIANT (spec B1): the stale abort flag used to skip this stop, so the lost Run kept
    # spending with nobody attached until the engine's reaper found it.
    with isolation_engine(_lost_later()) as engine:
        transport = Url4CloudTransport(
            engine.url, reconnect_budget_s=0.3, reconnect_base_delay_s=0.01
        )
        try:
            transport.cancel_active()
            with pytest.raises(ExecutionError) as caught:
                transport.run(candidate("later"), None)
        finally:
            transport.close()

    assert caught.value.code == "websocket_disconnected"
    assert engine.state.deleted == [engine.state.capability_of(url4_of("later"))]


@pytest.mark.asyncio
async def test_async_a_run_after_an_owner_abort_stops_its_own_run_when_its_budget_ends() -> None:
    with isolation_engine(_lost_later()) as engine:
        transport = AsyncUrl4CloudTransport(
            engine.url, reconnect_budget_s=0.3, reconnect_base_delay_s=0.01
        )
        try:
            await transport.cancel_active()
            with pytest.raises(ExecutionError) as caught:
                await transport.run(candidate("later"), None)
        finally:
            await transport.close()

    assert caught.value.code == "websocket_disconnected"
    assert engine.state.deleted == [engine.state.capability_of(url4_of("later"))]


# --- 4.3 (review): the abort stays in effect while any Run of it still runs --------------


def _swept_and_later() -> tuple[dict[str, RunPlan], threading.Event]:
    hold = threading.Event()
    return (
        {url4_of("swept"): RunPlan(hold=hold), url4_of("later"): RunPlan(first="drop")},
        hold,
    )


def test_an_abort_stays_in_effect_while_a_swept_run_still_runs() -> None:
    # INVARIANT (spec 4.3): a Run started while the swept Runs still unwind belongs to the
    # abort's window — it does not reconnect. Only when no Run is running does it end.
    plans, hold = _swept_and_later()
    with isolation_engine(plans) as engine:
        transport = Url4CloudTransport(engine.url, reconnect_base_delay_s=0.01)
        try:
            with ThreadPoolExecutor(max_workers=1) as pool:
                swept = pool.submit(transport.run, candidate("swept"), None)
                _wait_until_started(engine, "swept")
                transport.cancel_active()
                with pytest.raises(ExecutionError):
                    transport.run(candidate("later"), None)
                hold.set()
                swept.result(timeout=10)
        finally:
            transport.close()

    later = engine.state.capability_of(url4_of("later"))
    assert later is not None
    assert engine.state.handshakes[later] == 1  # no reconnect inside the abort's window


@pytest.mark.asyncio
async def test_async_an_abort_stays_in_effect_while_a_swept_run_still_runs() -> None:
    # WHY the async twin needs its own proof: its sweep EMPTIES the registry (a cancelled
    # Run leaves its capability for the sweep to clear), so "no capability registered" is
    # not "no Run running" there.
    plans, hold = _swept_and_later()
    with isolation_engine(plans) as engine:
        transport = AsyncUrl4CloudTransport(engine.url, reconnect_base_delay_s=0.01)
        try:
            swept = asyncio.create_task(transport.run(candidate("swept"), None))
            await asyncio.to_thread(_wait_until_started, engine, "swept")
            await transport.cancel_active()
            with pytest.raises(ExecutionError):
                await transport.run(candidate("later"), None)
            hold.set()
            await asyncio.wait_for(swept, timeout=10)
        finally:
            await transport.close()

    later = engine.state.capability_of(url4_of("later"))
    assert later is not None
    assert engine.state.handshakes[later] == 1
