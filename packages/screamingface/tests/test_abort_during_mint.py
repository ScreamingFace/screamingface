"""An abort that lands while a Candidate is minting its capability still stops it (E5 P1 spec
R8, D7; plan C3).

FEATURE: first-class Runs (OME-1785). STORY: as a researcher against an Engine that does not
record Runs, I abort an evaluation and none of its Candidates starts afterwards, even one that
was already asking for its capability.
"""

from __future__ import annotations

import asyncio
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import pytest
from _isolation_engine import RunPlan, candidate, isolation_engine, url4_of

from screamingface._engine import runs as wire
from screamingface._engine import transport as transport_module
from screamingface._engine.transport import AsyncUrl4CloudTransport, Url4CloudTransport
from screamingface.errors import ExecutionError
from screamingface.warnings import EvaluationWarning


def test_an_abort_during_the_mint_refuses_an_unregistered_start(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    alpha = candidate("alpha")
    minting, release = threading.Event(), threading.Event()
    real_mint = transport_module._mint_sync

    def slow_mint(*args: Any, **kwargs: Any) -> str:
        token = real_mint(*args, **kwargs)
        minting.set()
        release.wait(10)
        return token

    monkeypatch.setattr(transport_module, "_mint_sync", slow_mint)
    monkeypatch.setattr(wire, "create_sync", lambda *_a: wire.Unavailable("Runs are off"))
    with isolation_engine({url4_of("alpha"): RunPlan()}) as engine:
        transport = Url4CloudTransport(engine.url)
        try:
            with pytest.warns(EvaluationWarning):
                assert transport.open_run("gsm8k", 1, (alpha,)) is None
            with ThreadPoolExecutor(max_workers=1) as pool:
                start = pool.submit(transport.run, alpha, None)
                assert minting.wait(10)
                transport.abort_evaluation((alpha,))
                release.set()
                with pytest.raises(ExecutionError) as caught:
                    start.result(timeout=10)
        finally:
            transport.close()

    assert caught.value.code == "run_canceled"
    assert engine.state.started == {}


@pytest.mark.asyncio
async def test_async_an_abort_during_the_mint_refuses_an_unregistered_start(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    alpha = candidate("alpha")
    minting, release = asyncio.Event(), asyncio.Event()
    real_mint = transport_module._mint_async

    async def slow_mint(*args: Any, **kwargs: Any) -> str:
        token = await real_mint(*args, **kwargs)
        minting.set()
        await release.wait()
        return token

    async def unavailable(*_args: object) -> wire.Unavailable:
        return wire.Unavailable("Runs are off")

    monkeypatch.setattr(transport_module, "_mint_async", slow_mint)
    monkeypatch.setattr(wire, "create_async", unavailable)
    with isolation_engine({url4_of("alpha"): RunPlan()}) as engine:
        transport = AsyncUrl4CloudTransport(engine.url)
        try:
            with pytest.warns(EvaluationWarning):
                assert await transport.open_run("gsm8k", 1, (alpha,)) is None
            start = asyncio.create_task(transport.run(alpha, None))
            await asyncio.wait_for(minting.wait(), timeout=10)
            await transport.abort_evaluation((alpha,))
            release.set()
            with pytest.raises(ExecutionError) as caught:
                await asyncio.wait_for(start, timeout=10)
        finally:
            await transport.close()

    assert caught.value.code == "run_canceled"
    assert engine.state.started == {}
