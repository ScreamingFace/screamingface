"""A run that classifies never publishes a priced total, through the real executor (OME-1795).

FEATURE: hosted BYOM, Unit 3, spec E8 as amended by the owner on 2026-10-30. A classification
answer carries no price. The run total latches unpriced only on a call that reports an unknown
cost, and a call that reports nothing is simply absent, so a run that also made a priced chat call
would publish a complete-looking total that leaves the classification out.

INVARIANT: a priced total is a claim that every call was priced; a run with a classification in
it cannot make that claim.

WHY the real `Url4Executor` on a `build_world` world: the total is folded by the executor from the
records the handlers report, and `build_world` is where `/classify` is registered in production.
The control run without the classification proves the fake chat answer is priced, so the
classified run's unpriced total cannot pass by accident.
"""

from __future__ import annotations

import json
from decimal import Decimal
from typing import Any

import httpx
import pytest

from screamingface_engine.request_scope import RequestScope, request_scope
from screamingface_engine.runner.executor import Url4Executor
from screamingface_engine.world.accounting import (
    OPENROUTER_CREDIT_UNIT,
    PRICING_VERSION,
    UNPRICED,
)
from screamingface_engine.world.classification import CLASSIFICATIONS_PATH
from screamingface_engine.world.config import AigatewaySection, ModelSpec, WorldConfig
from screamingface_engine.world.factory import build_world
from url4.core.errors import ResolutionError
from url4.streaming.interfaces import Completed, Traced
from url4.streaming.protocol import CostUsageData

pytestmark = [pytest.mark.asyncio, pytest.mark.no_default_scope]

_CHAT = "openrouter/anthropic/claude-x"
_CHAT_PATH = "/v1/chat/completions"
_CLASSIFIER = "byom_" + "0123456789abcdef" * 2 + "/classifier_v1"
_CONTEXT = json.dumps({"model": _CLASSIFIER, "input": "hello"}, separators=(",", ":"))
_CHAT_ONLY = f"/{_CHAT}(ctx)!go"
_CHAT_OVER_CLASSIFY = f"/{_CHAT}(/classify('{_CONTEXT}')!classify)!go"


def _priced_chat() -> dict[str, Any]:
    """A priced cache miss: one succeeded attempt with a complete provider-authored subtotal."""
    return {
        "choices": [
            {"message": {"role": "assistant", "content": "an answer"}, "finish_reason": "stop"}
        ],
        "usage": {"prompt_tokens": 11, "completion_tokens": 7},
        "_aigw": {
            "usage_accounting": {
                "capture_status": "complete",
                "omitted_attempts": 0,
                "cache": {"status": "miss", "reference": None},
                "attempts": [
                    {
                        "provider": "openrouter",
                        "response_model": "anthropic/claude-x-20260801",
                        "outcome": "succeeded",
                        "usage": {"input": {"total": 11}, "output": {"total": 7}},
                    }
                ],
            },
            "request_economics": {
                "direct_cost_status": "complete",
                "known_direct_cost_subtotals": [
                    {"amount": "0.001", "unit": OPENROUTER_CREDIT_UNIT, "source": "openrouter"}
                ],
            },
        },
    }


def _classification(model: str) -> dict[str, Any]:
    return {
        "object": "classification",
        "model": model,
        "contract": "classification-scores-v1",
        "scores": [{"label": "A", "score": 0.5}],
    }


async def _execute(expression: str) -> tuple[list[str], list[object], ResolutionError | None]:
    """The Gateway paths, the executor's steps, and the error that ended the run, if any."""
    paths: list[str] = []

    def handle(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.path)
        if request.url.path == CLASSIFICATIONS_PATH:
            return httpx.Response(200, json=_classification(json.loads(request.content)["model"]))
        return httpx.Response(
            200,
            headers={"X-AIGW-Cache": "miss", "X-AIGW-Cache-Reason": "absent"},
            json=_priced_chat(),
        )

    config = WorldConfig(
        aigateway=AigatewaySection(
            base_url="http://aigateway.test",
            default_model=_CHAT,
            models=(ModelSpec(id=_CHAT, web_search=False),),
        )
    )
    steps: list[object] = []
    failure: ResolutionError | None = None
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handle), base_url="http://aigateway.test"
    ) as client:
        world, aclose = await build_world(env={}, config=config, client=client)
        try:
            with request_scope(
                RequestScope(origin="run", identity_headers={"X-User-Email": "a@x"})
            ):
                try:
                    async for step in Url4Executor(world).execute(expression):
                        steps.append(step)
                except ResolutionError as exc:
                    failure = exc
        finally:
            if aclose is not None:
                await aclose()
    return paths, steps, failure


def _costs(steps: list[object]) -> list[CostUsageData]:
    return [
        step.payload
        for step in steps
        if isinstance(step, Traced) and isinstance(step.payload, CostUsageData)
    ]


async def _run(expression: str) -> tuple[list[str], Completed, list[CostUsageData]]:
    paths, steps, failure = await _execute(expression)
    assert failure is None
    completed = steps[-1]
    assert isinstance(completed, Completed)
    return paths, completed, _costs(steps)


async def test_a_chat_run_without_a_classification_is_priced() -> None:
    """The control: the fake chat answer alone gives a priced total."""
    paths, completed, _ = await _run(_CHAT_ONLY)

    assert paths == [_CHAT_PATH]
    assert completed.subtree_cost.pricing_version == PRICING_VERSION
    assert completed.subtree_cost.cost.total_usd == Decimal("0.001")


async def test_a_priced_chat_over_a_classification_gives_an_unpriced_total() -> None:
    paths, completed, frames = await _run(_CHAT_OVER_CLASSIFY)

    assert paths == [CLASSIFICATIONS_PATH, _CHAT_PATH]
    assert completed.result.body == "an answer"
    assert completed.subtree_cost.pricing_version == UNPRICED
    (own,) = [frame for frame in frames if frame.scope == "self" and frame.model == _CLASSIFIER]
    assert own.pricing_version == UNPRICED
    assert (own.usage.input_tokens, own.usage.output_tokens) == (0, 0)


async def test_a_classification_refused_inside_a_run_sends_and_reports_nothing() -> None:
    """A lone surrogate in a run's own expression is the caller's malformed request: refused
    before dispatch, so no Gateway request and no cost record."""
    context = json.dumps({"model": _CLASSIFIER, "input": "a\ud800b"}, separators=(",", ":"))

    paths, steps, failure = await _execute(f"/classify('{context}')!classify")

    assert failure is not None and failure.code == "malformed_source"
    assert paths == []
    assert _costs(steps) == []
