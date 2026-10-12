"""E14 F-B3 review — a failed replay call gives back only its own occurrence slot.

FEATURE: OME-1307 (design §5.3 item 1). Two identical calls on the wire together hold slots 0 and
1. When slot 1 takes its answer and slot 0 fails, the next identical call must read entry 0 — never
entry 1 a second time. Checked on the chat lane and on the tool lane.

A separate module (append-only gate).
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Coroutine
from typing import Any

import httpx
import pytest
from frozen_copy_support import COPY, REPLAY_CHAT, TOOL_LOOKUP, chat

from screamingface_engine.capture_outcomes import capture_outcomes
from screamingface_engine.world import connector
from screamingface_engine.world.errors import RunnerRequestError
from screamingface_engine.world.web_tools import FrozenToolResults
from url4.core.errors import ResolutionError

_OCCURRENCE = "X-AIGW-Replay-Occurrence"
_TIMEOUT_S = 5.0  # a broken overlap fails the test instead of hanging it


def _slot_0_fails_after_slot_1(
    path: str, answer: Callable[[str], httpx.Response]
) -> tuple[Callable[[httpx.Request], Coroutine[Any, Any, httpx.Response]], list[str]]:
    """A gateway whose first slot-0 request fails, and only once slot 1 has been answered."""
    sent: list[str] = []
    slot_1_answered = asyncio.Event()

    async def handle(request: httpx.Request) -> httpx.Response:
        assert request.url.path == path
        occurrence = request.headers[_OCCURRENCE]
        sent.append(occurrence)
        if occurrence == "0" and sent.count("0") == 1:
            await slot_1_answered.wait()
            return httpx.Response(500, json={"detail": {"code": "boom", "message": "m"}})
        if occurrence == "1":
            slot_1_answered.set()
        return answer(occurrence)

    return handle, sent


def _client(
    handle: Callable[[httpx.Request], Coroutine[Any, Any, httpx.Response]],
) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=httpx.MockTransport(handle), base_url="http://aigateway.test"
    )


@pytest.mark.asyncio
async def test_a_failed_overlapping_replay_chat_call_gives_back_only_its_own_slot() -> None:
    handle, sent = _slot_0_fails_after_slot_1(REPLAY_CHAT, lambda n: chat(f"entry-{n}"))
    body = {"model": "m", "messages": [{"role": "user", "content": "q"}]}

    async with _client(handle) as client:
        with capture_outcomes() as tally:
            tally.mode, tally.frozen_copy_id = "replay", COPY

            async def replay() -> httpx.Response:
                resp, _outcome = await connector._fetch_replay(
                    client, headers={}, body=body, copy_id=COPY
                )
                return resp

            first, second = await asyncio.wait_for(
                asyncio.gather(replay(), replay(), return_exceptions=True), _TIMEOUT_S
            )
            third = await replay()

    assert isinstance(first, ResolutionError)
    assert isinstance(second, httpx.Response)
    assert second.json()["choices"][0]["message"]["content"] == "entry-1"
    assert sent == ["0", "1", "0"]
    assert third.json()["choices"][0]["message"]["content"] == "entry-0"


@pytest.mark.asyncio
async def test_a_failed_overlapping_replay_tool_lookup_gives_back_only_its_own_slot() -> None:
    handle, sent = _slot_0_fails_after_slot_1(
        TOOL_LOOKUP, lambda n: httpx.Response(200, json={"result": f"entry-{n}"})
    )
    description = {"tool": "web_search", "query": "q"}

    async with _client(handle) as client:
        frozen = FrozenToolResults(client, {}, COPY, replay=True)
        with capture_outcomes() as tally:
            tally.mode, tally.frozen_copy_id = "replay", COPY
            first, second = await asyncio.wait_for(
                asyncio.gather(
                    frozen.lookup(description), frozen.lookup(description), return_exceptions=True
                ),
                _TIMEOUT_S,
            )
            third = await frozen.lookup(description)

    assert isinstance(first, RunnerRequestError)
    assert second == "entry-1"
    assert sent == ["0", "1", "0"]
    assert third == "entry-0"
