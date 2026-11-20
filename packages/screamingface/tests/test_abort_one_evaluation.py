"""Aborting one evaluation stops only its Run (E5 P1 spec R8; E5 P2 spec D14; plan C1).

FEATURE: first-class Runs (OME-1785). STORY: as a researcher with two evaluations in flight on
one Client, I abort one and the other keeps running to its result.

Since E5 P2 each evaluation is one Run the Engine drives, so an abort cancels that Run alone.
"""

from __future__ import annotations

import asyncio
import threading

import pytest
from _isolation_engine import candidate
from _run_engine import (
    AsyncCollectingSink,
    CollectingSink,
    ended,
    run_engine,
    run_id_of,
    settled,
    state,
)

from screamingface._engine.transport import AsyncUrl4CloudTransport, Url4CloudTransport

BODY = b'{"cases": []}'
SCRIPT = [[state(0, "scheduled"), settled(0, BODY), ended()]]


def test_an_abort_stops_only_its_own_evaluations_runs() -> None:
    alpha, beta = candidate("alpha"), candidate("beta")
    sink = CollectingSink()
    with run_engine(SCRIPT, {0: BODY}) as engine:
        transport = Url4CloudTransport(engine.url, reconnect_base_delay_s=0.01)
        try:
            aborted = transport.register_run(None, (alpha,))
            kept = transport.register_run(None, (beta,))
            follower = threading.Thread(target=transport.follow_run, args=(kept, (beta,), sink))
            follower.start()
            transport.cancel_run(aborted)
            follower.join(timeout=10)
        finally:
            transport.close()

    assert (aborted, kept) == (run_id_of(0), run_id_of(1))
    assert engine.state.deleted == [f"/runs/{aborted}"]
    assert sink.outcomes[0].result_body == BODY.decode()


@pytest.mark.asyncio
async def test_async_an_abort_stops_only_its_own_evaluations_runs() -> None:
    alpha, beta = candidate("alpha"), candidate("beta")
    sink = AsyncCollectingSink()
    with run_engine(SCRIPT, {0: BODY}) as engine:
        transport = AsyncUrl4CloudTransport(engine.url, reconnect_base_delay_s=0.01)
        try:
            aborted = await transport.register_run(None, (alpha,))
            kept = await transport.register_run(None, (beta,))
            following = asyncio.create_task(transport.follow_run(kept, (beta,), sink))
            await transport.cancel_run(aborted)
            await asyncio.wait_for(following, timeout=10)
        finally:
            await transport.close()

    assert engine.state.deleted == [f"/runs/{aborted}"]
    assert sink.outcomes[0].result_body == BODY.decode()
