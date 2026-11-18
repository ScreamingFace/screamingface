"""A cancel of a waiting chat request is never swallowed (review F4, CC-S26, CC-41).

Starlette's `Request.is_disconnected()` opens an anyio cancel scope, and a cancel of the request
task that lands inside it is swallowed. The wait of the chat route watches the disconnect with a
task that awaits `receive()` instead. This test cancels many waiting requests, each after a
seeded random number of loop turns, so the cancels land at each await point of the wait, and
asserts that each cancel ends the request promptly and that its cleanup runs.
"""

from __future__ import annotations

import asyncio
import json
import random

import pytest
from _chat_app import asgi_call, asgi_scope, body, body_then, chat_app

pytestmark = pytest.mark.asyncio

RUNS = 200
SEED = 20261118


async def _turns(count: int) -> None:
    for _ in range(count):
        await asyncio.sleep(0)


async def test_every_cancel_of_a_waiting_request_ends_it_and_runs_its_cleanup() -> None:
    rng = random.Random(SEED)
    ca = chat_app(None, chat_max_wait_s=30.0)
    raw = json.dumps(body()).encode()
    for run in range(RUNS):
        never = asyncio.Event()
        call = asyncio.ensure_future(asgi_call(ca.app, asgi_scope(len(raw)), body_then(raw, never)))
        for _ in range(300):
            if len(ca.runner.scheduled) > run:
                break
            await asyncio.sleep(0.01)
        topic = ca.runner.scheduled[run]["topic"]
        await _turns(rng.randint(0, 12))
        if rng.random() < 0.3:
            await asyncio.sleep(rng.uniform(0.0, 0.02))

        call.cancel()
        done, _ = await asyncio.wait({call}, timeout=2.0)

        assert done, f"run {run}: the cancel was swallowed and the request still waits"
        assert call.cancelled(), f"run {run}: the request ended without the cancel"
        for _ in range(300):
            if topic in ca.runner.stopped and not ca.objects.objects:
                break
            await asyncio.sleep(0.01)
        assert topic in ca.runner.stopped, f"run {run}: the run was not stopped"
        assert ca.objects.objects == {}, f"run {run}: the input blob was not deleted"
    assert len(ca.runner.stopped) == RUNS
