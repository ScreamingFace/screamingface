"""E14 F-B3 — replay counts, per request, the successful answers it took (design §5.3 item 1).

FEATURE: OME-1307 — identical requests whose original answers differed (sampling, cache off) are
served in capture order. The engine sends `X-AIGW-Replay-Occurrence: <n>`, where n is how many
successful answers this run already received for the SAME request. Chat and tool lookups count
alike. A failed answer or a miss is not a successful answer and does not move the counter.

A separate module (append-only gate).
"""

from __future__ import annotations

import httpx
import pytest
from frozen_copy_support import (
    EXPRESSION,
    MODEL,
    REPLAY_CHAT,
    TOOL_LOOKUP,
    Gateway,
    chat,
    error,
    replay_scope,
    run_call,
    tool_call,
)

from screamingface_engine.request_scope import request_scope
from screamingface_engine.world.config import ModelSpec
from screamingface_engine.world.connector import AigatewayConfig, build_aigateway_world
from url4.dag import run as url4_run

_OTHER = f"/{MODEL}(other)!go"
_OCCURRENCE = "X-AIGW-Replay-Occurrence"


def _occurrences(gateway: Gateway, path: str) -> list[str]:
    return [headers[_OCCURRENCE] for headers, _body in gateway.calls(path)]


@pytest.mark.asyncio
async def test_replay_occurrence_counter_per_digest() -> None:
    gateway = Gateway(replay_steps=[chat("a"), chat("b"), chat("c")])

    _tally, answer, _failure = await run_call(
        gateway, replay_scope(), expressions=[EXPRESSION, EXPRESSION, EXPRESSION]
    )

    # Identical requests get 0, 1, 2 ...
    assert _occurrences(gateway, REPLAY_CHAT) == ["0", "1", "2"]
    assert answer == "c"


@pytest.mark.asyncio
async def test_a_different_request_has_its_own_counter() -> None:
    gateway = Gateway(replay_steps=[chat()])

    await run_call(gateway, replay_scope(), expressions=[EXPRESSION, _OTHER, EXPRESSION, _OTHER])

    assert _occurrences(gateway, REPLAY_CHAT) == ["0", "0", "1", "1"]


@pytest.mark.asyncio
async def test_a_failed_answer_does_not_move_the_counter() -> None:
    gateway = Gateway(replay_steps=[error(500, "boom"), chat(), chat()])

    _tally, _answer, failure = await run_call(
        gateway, replay_scope(), expressions=[EXPRESSION, EXPRESSION, EXPRESSION]
    )

    assert failure is None
    assert _occurrences(gateway, REPLAY_CHAT) == ["0", "0", "1"]


@pytest.mark.asyncio
async def test_a_run_without_a_tally_still_asks_for_the_first_answer() -> None:
    # No executor bound a tally (the sync surface): every call asks for occurrence 0.
    gateway = Gateway(replay_steps=[chat()])
    # `run_call` always binds a tally, so drive the connector without it.
    cfg = AigatewayConfig(models=(ModelSpec(id=MODEL),), default_model=MODEL)
    async with gateway.client() as client:
        world = await build_aigateway_world(cfg, client=client)
        with request_scope(replay_scope()):
            await url4_run(EXPRESSION, io=world.node)
            await url4_run(EXPRESSION, io=world.node)

    assert _occurrences(gateway, REPLAY_CHAT) == ["0", "0"]


@pytest.mark.asyncio
async def test_tool_lookups_count_their_own_occurrences() -> None:
    gateway = Gateway(
        replay_steps=[
            tool_call("web_search", {"query": "q"}),
            tool_call("web_search", {"query": "q"}),
            chat("done"),
        ],
        tool_lookup=lambda _r: httpx.Response(200, json={"result": "r"}),
    )

    _tally, answer, failure = await run_call(gateway, replay_scope())

    assert failure is None and answer == "done"
    assert _occurrences(gateway, TOOL_LOOKUP) == ["0", "1"]


@pytest.mark.asyncio
async def test_a_tool_lookup_miss_does_not_move_the_counter() -> None:
    lookups = iter([httpx.Response(404, json={}), httpx.Response(200, json={"result": "r"})])
    gateway = Gateway(
        replay_steps=[
            tool_call("web_search", {"query": "q"}),
            tool_call("web_search", {"query": "q"}),
            chat(),
        ],
        tool_lookup=lambda _r: next(lookups),
    )

    await run_call(gateway, replay_scope(), expressions=[EXPRESSION, EXPRESSION])

    assert _occurrences(gateway, TOOL_LOOKUP) == ["0", "0"]
