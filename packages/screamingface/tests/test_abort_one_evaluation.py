"""Aborting one evaluation stops only its Runs (E5 P1 spec R8; plan C3).

FEATURE: first-class Runs (OME-1785). STORY: as a researcher with two evaluations in flight on
one Client, I abort one and the other keeps running to its result.
"""

from __future__ import annotations

import asyncio
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest
from _isolation_engine import RunPlan, candidate, isolation_engine, result_body, url4_of
from test_run_isolation import _wait_until_started

from screamingface._engine.transport import AsyncUrl4CloudTransport, Url4CloudTransport


def _held() -> tuple[dict[str, RunPlan], threading.Event]:
    hold = threading.Event()
    return {url4_of("alpha"): RunPlan(hold=hold), url4_of("beta"): RunPlan(hold=hold)}, hold


def test_an_abort_stops_only_its_own_evaluations_runs() -> None:
    alpha, beta = candidate("alpha"), candidate("beta")
    plans, hold = _held()
    with isolation_engine(plans) as engine:
        transport = Url4CloudTransport(engine.url, reconnect_base_delay_s=0.01)
        try:
            aborted = transport.open_run("gsm8k", 1, (alpha,))
            transport.open_run("gsm8k", 1, (beta,))
            with ThreadPoolExecutor(max_workers=2) as pool:
                first = pool.submit(transport.run, alpha, None)
                second = pool.submit(transport.run, beta, None)
                _wait_until_started(engine, "alpha")
                _wait_until_started(engine, "beta")

                transport.abort_evaluation((alpha,))
                hold.set()
                outcome = second.result(timeout=10)
                first.exception(timeout=10)
        finally:
            transport.close()

    assert engine.state.deleted == [engine.state.capability_of(url4_of("alpha"))]
    assert engine.state.canceled_runs == [aborted]
    assert outcome.result_body == result_body(url4_of("beta"))


@pytest.mark.asyncio
async def test_async_an_abort_stops_only_its_own_evaluations_runs() -> None:
    alpha, beta = candidate("alpha"), candidate("beta")
    plans, hold = _held()
    with isolation_engine(plans) as engine:
        transport = AsyncUrl4CloudTransport(engine.url, reconnect_base_delay_s=0.01)
        try:
            aborted = await transport.open_run("gsm8k", 1, (alpha,))
            await transport.open_run("gsm8k", 1, (beta,))
            first = asyncio.create_task(transport.run(alpha, None))
            second = asyncio.create_task(transport.run(beta, None))
            await asyncio.to_thread(_wait_until_started, engine, "alpha")
            await asyncio.to_thread(_wait_until_started, engine, "beta")

            await transport.abort_evaluation((alpha,))
            hold.set()
            outcome = await asyncio.wait_for(second, timeout=10)
            await asyncio.wait([first], timeout=10)
        finally:
            await transport.close()

    assert engine.state.deleted == [engine.state.capability_of(url4_of("alpha"))]
    assert engine.state.canceled_runs == [aborted]
    assert outcome.result_body == result_body(url4_of("beta"))
