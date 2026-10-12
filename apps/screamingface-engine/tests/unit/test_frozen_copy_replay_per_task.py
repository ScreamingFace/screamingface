"""E14 F-B3 review round 2026-10-12 — a gathered replay gives each task its own answer (§5.4).

FEATURE: OME-1307. Replay answers each call by the (case key, occurrence) it sends. The first task
of a gathered group sends occurrence 0, and its answer must reach that task even when the task
that sent occurrence 1 answers first. The gateway is faked by occurrence header.
STORY: as a researcher who reproduces a score, two identical calls of one case get the two answers
their capture stored, in the order the case made them.

A separate module (append-only gate).
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from typing import Any

import httpx
import pytest
from frozen_copy_support import (
    EXPRESSION,
    MODEL,
    REPLAY_CHAT,
    TOOL_LOOKUP,
    Gateway,
    _bind_mode,
    chat,
    replay_scope,
)

from screamingface_engine.capture_outcomes import CALL_OCCURRENCE_HEADER, capture_outcomes
from screamingface_engine.request_scope import request_scope
from screamingface_engine.world.config import ModelSpec
from screamingface_engine.world.connector import AigatewayConfig, build_aigateway_world
from url4.dag import run as url4_run


class _ByOccurrence(Gateway):
    """A replay gateway that answers each call by its occurrence header.

    The call with occurrence 0 on ``hold_path`` waits until the call with occurrence 1 on that path
    has answered. So the task that sent occurrence 0 finishes last.
    """

    def __init__(self, hold_path: str, answer: Callable[[str, str, Any], httpx.Response]) -> None:
        super().__init__()
        self._hold_path = hold_path
        self._answer = answer
        self._second_answered = asyncio.Event()
        self.gate = self._hold_the_first

    async def _hold_the_first(self, request: httpx.Request) -> None:
        if request.url.path == self._hold_path and request.headers[CALL_OCCURRENCE_HEADER] == "0":
            await self._second_answered.wait()

    def handle(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path not in (REPLAY_CHAT, TOOL_LOOKUP):
            return super().handle(request)
        body = json.loads(request.content) if request.content else None
        self.requests.append((request.method, path, request.headers, body))
        occurrence = request.headers[CALL_OCCURRENCE_HEADER]
        if path == self._hold_path and occurrence == "1":
            self._second_answered.set()
        return self._answer(path, occurrence, body)


def _world_config() -> AigatewayConfig:
    return AigatewayConfig(models=(ModelSpec(id=MODEL, web_search=True),), default_model=MODEL)


_CHAT_BY = {"0": "a", "1": "b"}


@pytest.mark.asyncio
async def test_gathered_replay_chat_calls_take_their_own_answers_in_task_order() -> None:
    gateway = _ByOccurrence(
        REPLAY_CHAT, lambda _path, occurrence, _body: chat(_CHAT_BY[occurrence])
    )

    async with gateway.client() as client:
        world = await build_aigateway_world(_world_config(), client=client)
        with request_scope(replay_scope()), capture_outcomes() as tally:
            _bind_mode(replay_scope(), tally, bind_copy=False)
            outputs = await asyncio.gather(
                url4_run(EXPRESSION, io=world.node), url4_run(EXPRESSION, io=world.node)
            )

    assert list(outputs) == ["a", "b"]


def _two_identical_tool_calls() -> httpx.Response:
    calls = [
        {
            "id": f"call_{n}",
            "type": "function",
            "function": {"name": "web_search", "arguments": '{"query": "q"}'},
        }
        for n in (1, 2)
    ]
    return httpx.Response(
        200,
        json={
            "choices": [{"message": {"role": "assistant", "content": None, "tool_calls": calls}}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1},
        },
    )


@pytest.mark.asyncio
async def test_gathered_replay_tool_lookups_feed_their_own_results_in_task_order() -> None:
    def respond(path: str, occurrence: str, body: Any) -> httpx.Response:
        if path == TOOL_LOOKUP:
            return httpx.Response(200, json={"result": "AB"[int(occurrence)]})
        # The first chat call asks for two tools. Its second call carries their results, so it
        # is a different request, and its own occurrence is 0 again.
        if any(m["role"] == "tool" for m in body["messages"]):
            return chat("final")
        return _two_identical_tool_calls()

    gateway = _ByOccurrence(TOOL_LOOKUP, respond)

    async with gateway.client() as client:
        world = await build_aigateway_world(_world_config(), client=client)
        with request_scope(replay_scope()), capture_outcomes() as tally:
            _bind_mode(replay_scope(), tally, bind_copy=False)
            answer = await url4_run(EXPRESSION, io=world.node)

    assert answer == "final"
    # The second chat call carries the two tool results: each call's result under its own call id.
    _headers, second_body = gateway.calls(REPLAY_CHAT)[1]
    tool_messages = [m for m in second_body["messages"] if m["role"] == "tool"]
    assert {m["tool_call_id"]: m["content"] for m in tool_messages} == {
        "call_1": "A",
        "call_2": "B",
    }
