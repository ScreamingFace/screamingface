"""E5 P2 spec §4.2: what a refused follower sees through a real server.

FEATURE: a detached Run (OME-1837). STORY: as a researcher whose follow is refused, my Client
can tell "retry" from "not your Run".

WHY a real server: the in-process test client hands a close made before the handshake straight
to the test, with its code; a real server turns it into a bare HTTP 403. Only a socket shows
what the Client reads.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncIterator

import pytest
import uvicorn
import websockets
from test_runs_events import RUN_ID, _Runs
from test_runs_routes import ALICE, BOB, _Engine

pytestmark = pytest.mark.asyncio


@contextlib.asynccontextmanager
async def _served(runs: _Runs) -> AsyncIterator[str]:
    app = _Engine(None).app
    app.state.run_registry = runs
    server = uvicorn.Server(
        uvicorn.Config(app, host="127.0.0.1", port=0, lifespan="off", log_config=None)
    )
    task = asyncio.create_task(server.serve())
    try:
        while not server.started:
            await asyncio.sleep(0.01)
        port = server.servers[0].sockets[0].getsockname()[1]
        yield f"ws://127.0.0.1:{port}/runs/{RUN_ID}/events"
    finally:
        server.should_exit = True
        await task


async def _closed_with(url: str, headers: dict[str, str]) -> tuple[int | None, str | None]:
    async with websockets.connect(url, additional_headers=headers) as socket:
        with pytest.raises(websockets.ConnectionClosed):
            await asyncio.wait_for(socket.recv(), timeout=5)
        return socket.close_code, socket.close_reason


async def test_a_refusal_reaches_a_real_client_with_its_code_and_reason() -> None:
    async with _served(_Runs(("scheduled", "t0"))) as url:
        assert await _closed_with(url, BOB) == (1008, "run_not_found")


async def test_a_registry_outage_reaches_a_real_client_as_try_again_later() -> None:
    runs = _Runs(("scheduled", "t0"))
    runs.down = 1
    async with _served(runs) as url:
        assert await _closed_with(url, ALICE) == (1013, "registry_unavailable")
