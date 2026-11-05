"""The connector captures the reply log-probability numbers of the terminal round (E4b part 3).

Pins LC#1 (a call without declarations keeps its exact body; the typed params reach the body),
LC#5 (the connector keeps and logs no token text; a failure of the bookkeeping fails open), LC#7
(only the terminal round counts), LC#8 (a cache hit gives the same numbers), and LC#13 (a refusal
records no reply numbers). Built like `test_signal_accounting_connector.py`: a real aigateway world
over a MockTransport. A separate module (append-only gate).
"""

from __future__ import annotations

import json
import logging
import math
from typing import Any

import httpx
import pytest
from test_signal_accounting_connector import _hit_body, _miss_body, _tool_round_body, _world

from screamingface_engine.operation_accounting import ReplyLogprobs
from screamingface_engine.operation_calls import OperationCall, capture_operation_calls
from screamingface_engine.world.config import ModelSpec
from screamingface_engine.world.connector import (
    AigatewayConfig,
    AigatewayWorld,
    build_aigateway_world,
)
from url4 import RelExpr, expr, render, src, text
from url4.core.errors import ResolutionError

_ASKED = (("logprobs", "true"),)
_EN1 = 1.0296530140645737


def _expression(params: tuple[tuple[str, str], ...] = _ASKED) -> str:
    return render(
        expr(
            src(
                RelExpr(
                    path="/provider/alpha",
                    context="$input",
                    intent=text("Answer plainly."),
                    params=params,
                ),
                name="model_1",
                weight=0.0,
            ),
            intent=text("$model_1"),
        )
    )


def _with_logprobs(body: dict[str, Any], *values: float) -> dict[str, Any]:
    body["choices"][0]["logprobs"] = {
        "content": [
            {"token": "secret-token", "bytes": [115], "logprob": value, "top_logprobs": []}
            for value in values
        ]
    }
    return body


def _with_entropy(body: dict[str, Any]) -> dict[str, Any]:
    """Three positions, -0.1, -0.2, -0.3, each with top probabilities 0.5 and 0.3."""
    tops = [
        {"token": "secret-a", "logprob": math.log(0.5)},
        {"token": "secret-b", "logprob": math.log(0.3)},
    ]
    body["choices"][0]["logprobs"] = {
        "content": [
            {"token": "secret-token", "logprob": value, "top_logprobs": tops}
            for value in (-0.1, -0.2, -0.3)
        ]
    }
    return body


async def _calls(world: AigatewayWorld, expression: str) -> list[OperationCall]:
    with capture_operation_calls() as calls:
        await world.node.evaluate(expression, env={"input": "q"})
    return list(calls)


async def _bodies(expression: str) -> list[dict[str, Any]]:
    """The JSON body of every chat request that ``expression`` sends."""
    bodies: list[dict[str, Any]] = []

    def handle(request: httpx.Request) -> httpx.Response:
        if request.url.path.startswith("/v1/retrieval/tavily/cache/"):
            return httpx.Response(200, json={"status": "miss", "reason": None, "result": None})
        bodies.append(json.loads(request.content))
        return httpx.Response(200, headers={"X-AIGW-Cache": "miss"}, json=_miss_body())

    client = httpx.AsyncClient(
        transport=httpx.MockTransport(handle), base_url="http://aigateway.test"
    )
    world = await build_aigateway_world(
        AigatewayConfig(
            default_model="provider/alpha",
            models=(ModelSpec(id="provider/alpha", web_search=False),),
        ),
        client=client,
    )
    try:
        await world.node.evaluate(expression, env={"input": "q"})
    finally:
        await world.aclose()
        await client.aclose()
    return bodies


@pytest.mark.asyncio
async def test_call_body_without_declarations_is_unchanged() -> None:
    """LC#1: a call without `logprobs` keeps its exact body (LC-D4)."""
    assert await _bodies(_expression(())) == [
        {
            "model": "provider/alpha",
            "messages": [
                {"role": "system", "content": "Answer plainly."},
                {"role": "user", "content": "q"},
            ],
        }
    ]


@pytest.mark.asyncio
async def test_logprob_params_reach_the_body_typed() -> None:
    """LC#1 (LC-2, engine side): the declared params reach the body with their JSON types."""
    bodies = await _bodies(_expression((("logprobs", "true"), ("top_logprobs", "5"))))
    assert bodies[0]["logprobs"] is True
    assert bodies[0]["top_logprobs"] == 5
    assert type(bodies[0]["top_logprobs"]) is int


@pytest.mark.asyncio
async def test_terminal_round_records_reply_logprobs_on_the_operation_call() -> None:
    """LC#7: only the terminal round's numbers are recorded; the tool rounds never count."""
    world, client = await _world(
        [
            ("miss", _with_logprobs(_tool_round_body(), -1.0)),
            ("miss", _with_logprobs(_tool_round_body(), -2.0)),
            ("miss", _with_logprobs(_miss_body(), -0.25, -0.5)),
        ],
        web_tools=True,
    )
    try:
        calls = await _calls(world, _expression())
    finally:
        await world.aclose()
        await client.aclose()
    assert len(calls) == 1
    assert calls[0].reply_logprobs == ReplyLogprobs(
        tokens=2, logprob_sum=-0.75, top_k=None, entropy_mean=None
    )


@pytest.mark.asyncio
async def test_cache_hit_gives_the_same_numbers() -> None:
    """LC#8: a replayed call gives the numbers of the call it replays, bit for bit."""
    expression = _expression((("logprobs", "true"), ("top_logprobs", "5")))
    world, client = await _world(
        [("miss", _with_entropy(_miss_body())), ("hit", _with_entropy(_hit_body()))]
    )
    try:
        first = await _calls(world, expression)
        replay = await _calls(world, expression)
    finally:
        await world.aclose()
        await client.aclose()
    assert first[0].reply_logprobs is not None
    assert first[0].reply_logprobs == replay[0].reply_logprobs
    assert first[0].reply_logprobs.tokens == 3
    assert first[0].reply_logprobs.logprob_sum == -0.6
    assert first[0].reply_logprobs.top_k == 5
    assert first[0].reply_logprobs.entropy_mean == pytest.approx(_EN1, rel=1e-12)


@pytest.mark.asyncio
async def test_connector_logs_no_token_text(caplog: pytest.LogCaptureFixture) -> None:
    """LC#5: the numbers reach the call, and no token text reaches the log."""
    world, client = await _world([("miss", _with_logprobs(_miss_body(), -0.5))])
    try:
        with caplog.at_level(logging.DEBUG):
            calls = await _calls(world, _expression())
    finally:
        await world.aclose()
        await client.aclose()
    assert calls[0].reply_logprobs == ReplyLogprobs(1, -0.5, None, None)
    assert "secret-token" not in caplog.text


@pytest.mark.asyncio
async def test_unexpected_reply_logprobs_failure_does_not_fail_a_successful_answer(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """LC#5 (NFR, fail open): a parser failure never fails a successful answer."""

    def fail(*_args: object) -> None:
        raise ValueError("private logprob payload")

    monkeypatch.setattr("screamingface_engine.world.connector.reply_logprobs", fail)
    world, client = await _world([("miss", _with_logprobs(_miss_body(), -0.5))])
    try:
        with caplog.at_level(logging.WARNING):
            calls = await _calls(world, _expression())
    finally:
        await world.aclose()
        await client.aclose()
    assert [call.output for call in calls] == ["an answer"]
    assert calls[0].reply_logprobs is None
    assert "reply logprobs unavailable after ValueError" in caplog.text
    assert "private logprob payload" not in caplog.text


@pytest.mark.asyncio
async def test_refusal_records_no_reply_logprobs() -> None:
    """LC#13 (guard): a refused call records no reply numbers (LC-D6)."""
    world, client = await _world([("miss", _with_logprobs(_miss_body("content_filter"), -0.5))])
    try:
        with capture_operation_calls() as calls, pytest.raises(ResolutionError) as caught:
            await world.node.evaluate(_expression(), env={"input": "q"})
    finally:
        await world.aclose()
        await client.aclose()
    assert caught.value.code == "provider_refusal"
    assert [c.output for c in calls] == [""]
    assert calls[0].reply_logprobs is None
