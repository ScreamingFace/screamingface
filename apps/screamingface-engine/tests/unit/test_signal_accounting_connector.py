"""The connector keeps each model call's original signal accounting (OME-1289 E4a, SG#19).

FEATURE: a replay from the response cache must give a combine signal the same numbers as the
first call did, even though the retained accounting of a hit is zero.
Built like ``test_operation_output_capture.py``: a real aigateway world over a MockTransport.
"""

from __future__ import annotations

import logging
import math
from collections.abc import Callable
from typing import Any

import httpx
import pytest

from screamingface_engine.operation_accounting import SignalAccounting
from screamingface_engine.operation_calls import (
    OperationCall,
    capture_operation_calls,
    operation_call_identity,
    record_operation_call,
)
from screamingface_engine.world.config import ModelSpec
from screamingface_engine.world.connector import (
    AigatewayConfig,
    AigatewayWorld,
    build_aigateway_world,
)
from url4 import RelExpr, expr, render, src, text
from url4.core.errors import ResolutionError

_EXPECTED = SignalAccounting(0.002, 30.0, 10.0, 4.0)


def _expression() -> str:
    return render(
        expr(
            src(
                RelExpr(path="/provider/alpha", context="$input", intent=text("Answer plainly.")),
                name="model_1",
                weight=0.0,
            ),
            intent=text("$model_1"),
        )
    )


def _cost(amount: str) -> dict[str, str]:
    return {"status": "reported", "amount": amount, "unit": "openrouter_credits", "source": "x"}


def _attempt(outcome: str, tokens: tuple[int, int], latency_ms: int, cost: str) -> dict[str, Any]:
    return {
        "outcome": outcome,
        "provider": "openrouter",
        "response_model": "m",
        "latency_ms": latency_ms,
        "usage": {"input": {"total": tokens[0]}, "output": {"total": tokens[1]}},
        "direct_cost": _cost(cost),
    }


def _miss_body(finish_reason: str = "stop") -> dict[str, Any]:
    attempts = [
        _attempt("provider_error", (5, 0), 40, "0.0005"),
        _attempt("succeeded", (10, 4), 30, "0.002"),
    ]
    return {
        "choices": [{"message": {"content": "an answer"}, "finish_reason": finish_reason}],
        "usage": {"prompt_tokens": 15, "completion_tokens": 4},
        "_aigw": {
            "usage_accounting": {
                "capture_status": "complete",
                "omitted_attempts": 0,
                "attempts": attempts,
                "cache": {"status": "miss", "reference": None},
            },
            "request_economics": {
                "direct_cost_status": "complete",
                "known_direct_cost_subtotals": [
                    {"amount": "0.0025", "unit": "openrouter_credits", "source": "x"}
                ],
            },
        },
    }


def _tool_round_body() -> dict[str, Any]:
    """A miss whose turn ends in a web_search tool call, so the loop makes another round trip."""
    body = _miss_body()
    body["choices"] = [
        {
            "message": {
                "content": None,
                "tool_calls": [
                    {
                        "id": "call_1",
                        "type": "function",
                        "function": {"name": "web_search", "arguments": '{"query":"q"}'},
                    }
                ],
            },
            "finish_reason": "tool_calls",
        }
    ]
    return body


def _hit_body() -> dict[str, Any]:
    reference = {
        "usage": {"input": {"total": 10}, "output": {"total": 4}},
        "direct_cost": _cost("0.002"),
        "latency": {"provider_latency_ms": 30},
    }
    return {
        "choices": [{"message": {"content": "an answer"}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 4},
        "_aigw": {
            "usage_accounting": {
                "capture_status": "not_applicable",
                "omitted_attempts": 0,
                "attempts": [],
                "cache": {"status": "hit", "reference": reference},
            },
            "request_economics": {
                "direct_cost_status": "not_applicable",
                "known_direct_cost_subtotals": [],
            },
        },
    }


def _responder(
    replies: list[tuple[str, dict[str, Any]]],
) -> Callable[[httpx.Request], httpx.Response]:
    queue = list(replies)

    def respond(request: httpx.Request) -> httpx.Response:
        cache, body = queue.pop(0)
        return httpx.Response(200, headers={"X-AIGW-Cache": cache}, json=body)

    return respond


async def _world(
    replies: list[tuple[str, dict[str, Any]]], *, web_tools: bool = False
) -> tuple[AigatewayWorld, httpx.AsyncClient]:
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(_responder(replies)), base_url="http://aigateway.test"
    )
    tavily = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _request: httpx.Response(200, json={"results": []})),
        base_url="https://api.tavily.test",
    )
    world = await build_aigateway_world(
        AigatewayConfig(
            default_model="provider/alpha",
            models=(ModelSpec(id="provider/alpha", web_search=web_tools),),
        ),
        client=client,
        tavily_api_key="test-token" if web_tools else None,
        tavily_client=tavily if web_tools else None,
    )
    return world, client


async def _call(world: AigatewayWorld) -> list[OperationCall]:
    with capture_operation_calls() as calls:
        await world.node.evaluate(_expression(), env={"input": "q"})
    return list(calls)


@pytest.mark.asyncio
async def test_retried_call_signal_equals_cache_reference_on_replay() -> None:
    world, client = await _world([("miss", _miss_body()), ("hit", _hit_body())])
    try:
        first = await _call(world)
        replay = await _call(world)
    finally:
        await world.aclose()
        await client.aclose()
    assert len(first) == len(replay) == 1
    assert first[0].signal_accounting == _EXPECTED
    assert replay[0].signal_accounting == _EXPECTED
    # The retained accounting keeps its own truth: a hit costs nothing now, a retry costs both.
    assert replay[0].accounting is not None
    assert replay[0].accounting.usage.cost_usd == "0"
    assert first[0].accounting is not None
    assert first[0].accounting.usage.input_tokens == 15


@pytest.mark.asyncio
async def test_refusal_record_carries_signal_accounting() -> None:
    world, client = await _world([("miss", _miss_body("content_filter"))])
    try:
        with capture_operation_calls() as calls:
            with pytest.raises(ResolutionError) as caught:
                await world.node.evaluate(_expression(), env={"input": "q"})
    finally:
        await world.aclose()
        await client.aclose()
    assert caught.value.code == "provider_refusal"
    assert [call.output for call in calls] == [""]
    assert calls[0].signal_accounting == _EXPECTED


@pytest.mark.asyncio
async def test_a_response_without_gateway_accounting_gives_all_none() -> None:
    body = {"choices": [{"message": {"content": "x"}, "finish_reason": "stop"}]}
    world, client = await _world([("miss", body)])
    try:
        calls = await _call(world)
    finally:
        await world.aclose()
        await client.aclose()
    assert calls[0].signal_accounting == SignalAccounting()


def test_record_operation_call_puts_signal_accounting_on_the_call() -> None:
    signal = SignalAccounting(0.1, 2.0, 3.0, 4.0)
    with capture_operation_calls() as calls:
        with operation_call_identity("/provider/alpha", {"temperature": "0.0"}):
            record_operation_call("out", "stop", None, signal)
            record_operation_call("plain", "stop")
    assert [call.signal_accounting for call in calls] == [signal, None]


@pytest.mark.asyncio
async def test_tool_loop_rounds_sum_signal_accounting() -> None:
    world, client = await _world(
        [("miss", _tool_round_body()), ("miss", _miss_body())], web_tools=True
    )
    try:
        calls = await _call(world)
    finally:
        await world.aclose()
        await client.aclose()
    assert len(calls) == 1  # one logical call: only the terminal round is recorded
    assert calls[0].signal_accounting == SignalAccounting(
        math.fsum([0.002, 0.002]), 60.0, 20.0, 8.0
    )


@pytest.mark.asyncio
async def test_unexpected_signal_accounting_failure_does_not_fail_a_successful_answer(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    def fail_accounting(*_args: object) -> None:
        raise ValueError("private accounting payload")

    monkeypatch.setattr(
        "screamingface_engine.world.connector.signal_accounting_from_aigw", fail_accounting
    )
    world, client = await _world([("miss", _miss_body())])
    try:
        with caplog.at_level(logging.WARNING):
            calls = await _call(world)
    finally:
        await world.aclose()
        await client.aclose()
    assert [call.output for call in calls] == ["an answer"]
    assert calls[0].signal_accounting == SignalAccounting()
    assert "signal accounting unavailable after ValueError" in caplog.text
    assert "private accounting payload" not in caplog.text
    assert "an answer" not in caplog.text
