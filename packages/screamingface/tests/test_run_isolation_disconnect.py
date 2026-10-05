"""A lost stream stops only its own Run; a completed Run is never stopped (OME-1067).

FEATURE: OME-1067 — one lost socket must not destroy work that is healthy or already done.
STORY: as a researcher running several Candidates, when one Candidate's stream is lost past
its reconnect budget, only that Candidate fails; a sibling that already finished keeps its
result, and a sibling that is still running finishes.

Spec: `docs/spec/2026-09-28-sdk-run-isolation.md` §4.1 C3 and §4.2 (bug B2).
"""

from __future__ import annotations

import asyncio
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pytest
from _isolation_engine import (
    ARTIFACT_BODY,
    RunPlan,
    StubEngine,
    candidate,
    isolation_engine,
    result_body,
    url4_of,
)

from screamingface._engine.transport import AsyncUrl4CloudTransport, Url4CloudTransport
from screamingface.errors import ExecutionError
from screamingface.events import Terminated


def _wait_until_started(engine: StubEngine, name: str) -> str:
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        token = engine.state.capability_of(url4_of(name))
        if token is not None:
            return token
        time.sleep(0.01)
    raise AssertionError(f"the Run of {name!r} never started")


def _lost_and_healthy() -> tuple[dict[str, RunPlan], threading.Event]:
    hold = threading.Event()
    return (
        {
            # Every reconnect is refused with a transient 503, so the outage budget runs out.
            url4_of("lost"): RunPlan(first="drop", reconnects=[503] * 500),
            url4_of("healthy"): RunPlan(hold=hold),
        },
        hold,
    )


# --- C3: an outage past its budget stops only the lost Run ------------------------------


def test_a_stream_lost_past_its_budget_stops_only_its_own_run() -> None:
    # INVARIANT (spec 4.1 C3): the sibling is independently attached and healthy; the lost
    # Run's budget is not its budget. It must finish and return its result.
    plans, hold = _lost_and_healthy()
    with isolation_engine(plans) as engine:
        transport = Url4CloudTransport(
            engine.url, reconnect_budget_s=0.3, reconnect_base_delay_s=0.01
        )
        try:
            with ThreadPoolExecutor(max_workers=1) as pool:
                healthy = pool.submit(transport.run, candidate("healthy"), None)
                _wait_until_started(engine, "healthy")
                with pytest.raises(ExecutionError) as caught:
                    transport.run(candidate("lost"), None)
                hold.set()
                outcome = healthy.result(timeout=10)
        finally:
            transport.close()

    assert caught.value.code == "websocket_disconnected"
    assert outcome.result_body == result_body(url4_of("healthy"))
    assert engine.state.deleted == [engine.state.capability_of(url4_of("lost"))]


@pytest.mark.asyncio
async def test_async_a_stream_lost_past_its_budget_stops_only_its_own_run() -> None:
    plans, hold = _lost_and_healthy()
    with isolation_engine(plans) as engine:
        transport = AsyncUrl4CloudTransport(
            engine.url, reconnect_budget_s=0.3, reconnect_base_delay_s=0.01
        )
        try:
            healthy = asyncio.create_task(transport.run(candidate("healthy"), None))
            await asyncio.to_thread(_wait_until_started, engine, "healthy")
            with pytest.raises(ExecutionError) as caught:
                await transport.run(candidate("lost"), None)
            hold.set()
            outcome = await asyncio.wait_for(healthy, timeout=10)
        finally:
            await transport.close()

    assert caught.value.code == "websocket_disconnected"
    assert outcome.result_body == result_body(url4_of("healthy"))
    assert engine.state.deleted == [engine.state.capability_of(url4_of("lost"))]


# --- 4.2 / B2: a Run whose terminal frame arrived is out of every stop's reach -----------


def _completed_with_held_artifact() -> tuple[dict[str, RunPlan], threading.Event]:
    fetch_hold = threading.Event()
    return (
        {url4_of("done"): RunPlan(artifact=True, artifact_hold=fetch_hold)},
        fetch_hold,
    )


def test_an_owner_sweep_never_stops_a_completed_run() -> None:
    # INVARIANT (spec 4.2): once the terminal frame is accepted the Run is complete. A sweep
    # that lands while its result is still being fetched must not send a stop for it — the
    # Run is not running, and the caller gets the result it paid for.
    plans, fetch_hold = _completed_with_held_artifact()
    with isolation_engine(plans) as engine:
        transport = Url4CloudTransport(engine.url)
        try:
            with ThreadPoolExecutor(max_workers=1) as pool:
                done = pool.submit(transport.run, candidate("done"), None)
                assert engine.state.artifact_requested.wait(10)
                transport.cancel_active()
                fetch_hold.set()
                outcome = done.result(timeout=10)
        finally:
            transport.close()

    assert outcome.result_path is not None
    assert outcome.result_path.read_text() == ARTIFACT_BODY
    assert engine.state.deleted == []


@pytest.mark.asyncio
async def test_async_an_owner_sweep_never_stops_a_completed_run() -> None:
    plans, fetch_hold = _completed_with_held_artifact()
    with isolation_engine(plans) as engine:
        transport = AsyncUrl4CloudTransport(engine.url)
        try:
            done = asyncio.create_task(transport.run(candidate("done"), None))
            assert await asyncio.to_thread(engine.state.artifact_requested.wait, 10)
            await transport.cancel_active()
            fetch_hold.set()
            outcome = await asyncio.wait_for(done, timeout=10)
        finally:
            await transport.close()

    assert outcome.result_path is not None
    assert outcome.result_path.read_text() == ARTIFACT_BODY
    assert engine.state.deleted == []


@pytest.mark.asyncio
async def test_async_a_cancelled_completed_run_leaves_nothing_for_the_sweep() -> None:
    # WHY this case: a cancelled async Run deliberately keeps its capability registered so
    # the Evaluation's sweep can stop it (see `AsyncUrl4CloudTransport.run`). A Run that was
    # already COMPLETE when the cancel landed must not be on that list.
    plans, _fetch_hold = _completed_with_held_artifact()
    with isolation_engine(plans) as engine:
        transport = AsyncUrl4CloudTransport(engine.url)
        try:
            done = asyncio.create_task(transport.run(candidate("done"), None))
            assert await asyncio.to_thread(engine.state.artifact_requested.wait, 10)
            done.cancel()
            with pytest.raises(asyncio.CancelledError):
                await done
            await transport.cancel_active()
        finally:
            await transport.close()

    assert engine.state.deleted == []


# --- 4.2 (review): complete at the terminal FRAME, before the caller's callback ----------


def _is_terminal(event: object) -> bool:
    return isinstance(event, Terminated)


def test_a_sweep_during_a_slow_terminal_callback_never_stops_the_completed_run() -> None:
    # INVARIANT (spec 4.2): the Run is complete when its terminal frame is accepted — not
    # when the caller's callback for that frame returns. A slow callback is not a live Run.
    in_callback, release = threading.Event(), threading.Event()

    def slow(event: object) -> None:
        if _is_terminal(event):
            in_callback.set()
            release.wait(10)

    with isolation_engine({url4_of("done"): RunPlan()}) as engine:
        transport = Url4CloudTransport(engine.url)
        try:
            with ThreadPoolExecutor(max_workers=1) as pool:
                done = pool.submit(transport.run, candidate("done"), slow)
                assert in_callback.wait(10)
                transport.cancel_active()
                release.set()
                outcome = done.result(timeout=10)
        finally:
            transport.close()

    assert outcome.result_body == result_body(url4_of("done"))
    assert engine.state.deleted == []
    assert engine.state.stop_frames == []


def test_a_raising_terminal_callback_sends_no_stop_for_the_completed_run() -> None:
    # WHY: the socket's interrupt arm sends `ai.url4.stop` for a Run that is still running.
    # The callback's error still reaches the caller, but the finished Run is not "stopped".
    def raising(event: object) -> None:
        if _is_terminal(event):
            raise RuntimeError("callback failed")

    with isolation_engine({url4_of("done"): RunPlan()}) as engine:
        transport = Url4CloudTransport(engine.url)
        try:
            with pytest.raises(RuntimeError, match="callback failed"):
                transport.run(candidate("done"), raising)
        finally:
            transport.close()

    assert engine.state.deleted == []
    assert engine.state.stop_frames == []


@pytest.mark.asyncio
async def test_async_a_sweep_during_a_slow_terminal_callback_never_stops_the_completed_run() -> (
    None
):
    in_callback, release = asyncio.Event(), asyncio.Event()

    async def slow(event: object) -> None:
        if _is_terminal(event):
            in_callback.set()
            await release.wait()

    with isolation_engine({url4_of("done"): RunPlan()}) as engine:
        transport = AsyncUrl4CloudTransport(engine.url)
        try:
            done = asyncio.create_task(transport.run(candidate("done"), slow))
            await asyncio.wait_for(in_callback.wait(), timeout=10)
            await transport.cancel_active()
            release.set()
            outcome = await asyncio.wait_for(done, timeout=10)
        finally:
            await transport.close()

    assert outcome.result_body == result_body(url4_of("done"))
    assert engine.state.deleted == []
    assert engine.state.stop_frames == []


@pytest.mark.asyncio
async def test_async_a_raising_terminal_callback_sends_no_stop_for_the_completed_run() -> None:
    async def raising(event: object) -> None:
        if _is_terminal(event):
            raise RuntimeError("callback failed")

    with isolation_engine({url4_of("done"): RunPlan()}) as engine:
        transport = AsyncUrl4CloudTransport(engine.url)
        try:
            with pytest.raises(RuntimeError, match="callback failed"):
                await transport.run(candidate("done"), raising)
        finally:
            await transport.close()

    assert engine.state.deleted == []
    assert engine.state.stop_frames == []
