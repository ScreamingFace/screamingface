"""E14 F-B3 — a normal run is byte-identical to a run on a world without the frozen copy.

FEATURE: OME-1307 — capture and replay are opt-in. A run that asked for neither sends no copy
header, makes no tool-result post, reads no lookup route, and writes no `capture.*` attribute.
INVARIANT: this is the reason the cache-hit contract fixture needs no regeneration.

A separate module (append-only gate).
"""

from __future__ import annotations

import pytest
from frozen_copy_support import (
    CHAT,
    EXPRESSION,
    MODEL,
    Gateway,
    Tavily,
    chat,
    run_call,
    tool_call,
)

from screamingface_engine.request_scope import RequestScope, request_scope
from screamingface_engine.runner.executor import Url4Executor
from screamingface_engine.world.config import ModelSpec
from screamingface_engine.world.connector import AigatewayConfig, build_aigateway_world
from url4.streaming.interfaces import Traced
from url4.streaming.protocol import LogData


@pytest.mark.asyncio
async def test_normal_run_is_byte_identical() -> None:
    gateway = Gateway([tool_call("web_search", {"query": "q"}), chat("final")])

    tally, answer, failure = await run_call(gateway, RequestScope(origin="run"), tavily=Tavily())

    assert failure is None
    assert answer == "final"
    # No copy route of any kind is reached; the Tavily cache lanes are the only side routes.
    assert {p for p in gateway.paths() if "frozen-copies" in p} == set()
    assert gateway.paths().count(CHAT) == 2
    for headers, body in gateway.calls(CHAT):
        assert not [name for name in headers if name.lower().startswith("x-aigw-")]
        assert "cache" not in body
    # Nothing is recorded or counted: the tally of a normal run stays empty.
    assert tally.mode is None
    assert tally.frozen_copy_id is None
    assert tally.outcomes == []
    assert tally.slots == {}


@pytest.mark.asyncio
async def test_a_normal_run_writes_no_capture_summary_attribute() -> None:
    gateway = Gateway([chat("final")])
    cfg = AigatewayConfig(models=(ModelSpec(id=MODEL),), default_model=MODEL)
    logs: list[LogData] = []
    async with gateway.client() as client:
        world = await build_aigateway_world(cfg, client=client)
        executor = Url4Executor(world.node)
        with request_scope(RequestScope(origin="run")):
            async for step in executor.execute(EXPRESSION):
                if isinstance(step, Traced) and isinstance(step.payload, LogData):
                    logs.append(step.payload)

    summary = executor.last_summary()
    assert summary is not None and summary.cache_attributes is not None
    assert not [key for key in summary.cache_attributes if key.startswith("capture.")]
    assert not [
        key for log in logs for key in (log.attributes or {}) if str(key).startswith("capture.")
    ]
    assert gateway.paths() == [CHAT]
