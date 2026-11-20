"""Nothing starts without a Run (E5 P1 spec R8; E5 P2 spec D2; plan C1).

FEATURE: first-class Runs (OME-1785). STORY: as a researcher against an Engine that does not run
Runs, I never get a Candidate that started outside one, so an abort always has a Run to cancel.

WHY this replaced the abort-during-mint guard: a P1 Client could start a Candidate with no Run
when the Engine did not record one, so an abort that landed while it minted its capability had to
refuse its start. A P2 Client starts nothing itself, and an Engine with Runs off refuses the
evaluation before anything runs.
"""

from __future__ import annotations

import httpx
import pytest
from _run_engine import run_engine
from test_client_run import _engine as _catalog_engine

import screamingface as sf
from screamingface.errors import ExecutionError

_MODELS = [sf.Model("provider/opus", name="alpha"), sf.Model("provider/opus", name="beta")]


def test_an_abort_during_the_mint_refuses_an_unregistered_start() -> None:
    with run_engine([], {}, refuse_create=(404, "runs_off")) as engine:
        with sf.Client(
            engine_url=engine.url, http_transport=httpx.MockTransport(_catalog_engine)
        ) as client:
            with pytest.raises(ExecutionError) as caught:
                client.evaluate(_MODELS, benchmark="draco", progress=False)

    assert caught.value.code == "runs_off"
    assert (engine.state.followed, engine.state.deleted) == ([], [])


@pytest.mark.asyncio
async def test_async_an_abort_during_the_mint_refuses_an_unregistered_start() -> None:
    with run_engine([], {}, refuse_create=(404, "runs_off")) as engine:
        async with sf.AsyncClient(
            engine_url=engine.url, http_transport=httpx.MockTransport(_catalog_engine)
        ) as client:
            with pytest.raises(ExecutionError) as caught:
                await client.evaluate(_MODELS, benchmark="draco", progress=False)

    assert caught.value.code == "runs_off"
    assert (engine.state.followed, engine.state.deleted) == ([], [])
