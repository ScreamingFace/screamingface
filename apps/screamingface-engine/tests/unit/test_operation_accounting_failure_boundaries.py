"""Accounting bookkeeping never changes a model call's terminal outcome."""

from __future__ import annotations

import logging
from collections.abc import Mapping

import httpx
import pytest

from screamingface_engine.benchmarks.contract import decode_candidate_invocation_record
from screamingface_engine.benchmarks.invocation import evaluate_candidate_recipe
from screamingface_engine.runner.accounting import retained_operation_accounting
from screamingface_engine.runner.cache_readback import CacheOutcome
from screamingface_engine.runner.connector import AigatewayConfig, build_aigateway_world
from screamingface_engine.world_config import ModelSpec
from url4 import RelExpr, expr, render, src, text

_MODEL = "provider/model"


def _aigw(*, provider: str = "provider", response_model: str = _MODEL) -> dict[str, object]:
    return {
        "usage_accounting": {
            "capture_status": "complete",
            "omitted_attempts": 0,
            "attempts": [
                {
                    "provider": provider,
                    "response_model": response_model,
                    "latency_ms": 25,
                    "usage": {
                        "input": {"total": 10, "cache_read": 0, "cache_write": 0},
                        "output": {"total": 2, "reasoning": 0},
                    },
                }
            ],
            "cache": {"status": "miss", "reference": None},
        },
        "request_economics": {
            "direct_cost_status": "complete",
            "known_direct_cost_subtotals": [
                {"amount": "0.25", "unit": "openrouter_credits", "source": "provider"}
            ],
        },
    }


def _response(*, refusal: bool = False, malformed_identity: bool = False) -> dict[str, object]:
    return {
        "choices": [
            {
                "message": {
                    "content": None if refusal else "answer",
                    "refusal": "safety policy" if refusal else None,
                },
                "finish_reason": "content_filter" if refusal else "stop",
            }
        ],
        "usage": {"prompt_tokens": 10, "completion_tokens": 2},
        "_aigw": _aigw(
            provider=" " if malformed_identity else "provider",
            response_model=" " if malformed_identity else _MODEL,
        ),
    }


def _tool_response() -> dict[str, object]:
    return {
        "choices": [
            {
                "message": {
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "call_1",
                            "type": "function",
                            "function": {
                                "name": "web_search",
                                "arguments": '{"query":"accounting"}',
                            },
                        }
                    ],
                },
                "finish_reason": "tool_calls",
            }
        ],
        "usage": {"prompt_tokens": 10, "completion_tokens": 2},
        "_aigw": _aigw(),
    }


def _candidate() -> str:
    return render(
        expr(
            src(
                RelExpr(path=f"/{_MODEL}", context="$input", intent=text("Answer.")),
                name="model_1",
                weight=0.0,
            ),
            intent=text("$model_1"),
        )
    )


async def _evaluate(body: dict[str, object]):
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _request: httpx.Response(200, json=body)),
        base_url="http://aigateway.test",
    )
    world = await build_aigateway_world(
        AigatewayConfig(default_model=_MODEL, models=(ModelSpec(id=_MODEL),)),
        client=client,
    )
    try:
        encoded = await evaluate_candidate_recipe(world.node, _candidate(), "question")
    finally:
        await world.aclose()
        await client.aclose()
    return decode_candidate_invocation_record(encoded)


async def _evaluate_rounds(bodies: list[dict[str, object]]):
    remaining = iter(bodies)
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _request: httpx.Response(200, json=next(remaining))),
        base_url="http://aigateway.test",
    )
    tavily = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _request: httpx.Response(200, json={"results": []})),
        base_url="https://api.tavily.test",
    )
    world = await build_aigateway_world(
        AigatewayConfig(
            default_model=_MODEL,
            models=(ModelSpec(id=_MODEL, web_search=True),),
        ),
        client=client,
        tavily_api_key="test-token",
        tavily_client=tavily,
    )
    try:
        encoded = await evaluate_candidate_recipe(world.node, _candidate(), "question")
    finally:
        await world.aclose()
        await tavily.aclose()
        await client.aclose()
    return decode_candidate_invocation_record(encoded)


@pytest.mark.asyncio
async def test_provider_refusal_retains_the_consumed_call_accounting() -> None:
    invocation = await _evaluate(_response(refusal=True))

    assert invocation.status == "refused"
    assert invocation.operations is not None
    accounting = invocation.operations[0].accounting
    assert accounting is not None
    assert accounting.usage.cost_usd == "0.25"


@pytest.mark.asyncio
async def test_malformed_accounting_identity_degrades_only_identity_fields() -> None:
    invocation = await _evaluate(_response(malformed_identity=True))

    assert invocation.status == "completed"
    assert invocation.output == "answer"
    assert invocation.operations is not None
    accounting = invocation.operations[0].accounting
    assert accounting is not None
    assert accounting.provider is None
    assert accounting.response_model is None
    assert accounting.usage.cost_usd == "0.25"


@pytest.mark.asyncio
async def test_unexpected_accounting_failure_does_not_fail_a_successful_answer(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    def fail_accounting(**_fields: object) -> None:
        raise ValueError("private accounting payload")

    monkeypatch.setattr(
        "screamingface_engine.runner.connector.retained_operation_accounting",
        fail_accounting,
    )
    with caplog.at_level(logging.WARNING):
        invocation = await _evaluate(_response())

    assert invocation.status == "completed"
    assert invocation.output == "answer"
    assert invocation.operations is not None
    assert invocation.operations[0].accounting is None
    assert "operation accounting unavailable after ValueError" in caplog.text
    assert "provider/model" not in caplog.text
    assert "private accounting payload" not in caplog.text


@pytest.mark.asyncio
async def test_one_unavailable_tool_round_poisons_the_complete_operation_accounting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0

    def fail_first_round(
        *,
        request_model: str,
        usage: Mapping[str, object] | None,
        aigw: object,
        cache: CacheOutcome,
    ):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise ValueError("private accounting payload")
        return retained_operation_accounting(
            request_model=request_model,
            usage=usage,
            aigw=aigw,
            cache=cache,
        )

    monkeypatch.setattr(
        "screamingface_engine.runner.connector.retained_operation_accounting",
        fail_first_round,
    )

    invocation = await _evaluate_rounds([_tool_response(), _response()])

    assert invocation.operations is not None
    assert invocation.operations[0].accounting is None
