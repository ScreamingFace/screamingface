"""A routed run stays unpriced however its branch is priced (OME-1822).

FEATURE: BYOM routing pilot (spec 5, acceptance 8). A routed answer is one direct run with two
calls: a classification, whose cost is unknown (Unit 3, E8 as amended), and one chat call to the
selected branch, priced as any chat call. The run total latches unpriced on the unknown-cost
record, so it cannot claim a price that leaves the classification out.

WHY one `self` frame: a direct run is one span, and the executor folds every call reported on a
span into that span's frame, so the classification and the branch share it. The classification
reports no tokens, so the frame's counts are the branch's own.

WHY the control: the same priced answer from the same branch, called alone, gives a priced total,
so the routed run's unpriced total cannot pass by accident.
"""

from __future__ import annotations

import json
from decimal import Decimal
from typing import Any

import httpx
import pytest
from routing_support import (
    CALLER,
    CHAT_PATH,
    CLASSIFICATIONS_PATH,
    MODELS,
    Gateway,
    run_direct,
    world_config,
)

from screamingface_engine.request_scope import RequestScope, request_scope
from screamingface_engine.runner.executor import Url4Executor
from screamingface_engine.world.accounting import (
    OPENROUTER_CREDIT_UNIT,
    PRICING_VERSION,
    UNPRICED,
)
from screamingface_engine.world.factory import build_world
from url4.streaming.interfaces import Completed, Traced
from url4.streaming.protocol import CostUsageData

pytestmark = [pytest.mark.asyncio, pytest.mark.no_default_scope]

_BRANCH = MODELS["code"]


def _priced_chat() -> httpx.Response:
    """A priced cache miss: one succeeded attempt with a complete provider-authored subtotal."""
    body: dict[str, Any] = {
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
                        "response_model": "lab/code-20261101",
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
    return httpx.Response(
        200, headers={"X-AIGW-Cache": "miss", "X-AIGW-Cache-Reason": "absent"}, json=body
    )


def _costs(steps: list[object]) -> list[CostUsageData]:
    return [
        step.payload
        for step in steps
        if isinstance(step, Traced) and isinstance(step.payload, CostUsageData)
    ]


async def test_the_branch_answer_alone_is_priced() -> None:
    """The control: the branch's priced answer, with no classification, gives a priced total."""
    gateway = Gateway(script={(CHAT_PATH, _BRANCH): _priced_chat()})
    context = json.dumps("a question")
    steps: list[object] = []
    async with gateway.client() as client:
        node, aclose = await build_world(env={}, config=world_config(), client=client)
        try:
            with request_scope(RequestScope(origin="run", identity_headers=CALLER)):
                async for step in Url4Executor(node).execute(f"/{_BRANCH}({context})!go"):
                    steps.append(step)
        finally:
            if aclose is not None:
                await aclose()

    completed = steps[-1]
    assert isinstance(completed, Completed)
    assert [request.url.path for request in gateway.requests] == [CHAT_PATH]
    assert completed.subtree_cost.pricing_version == PRICING_VERSION
    assert completed.subtree_cost.cost.total_usd == Decimal("0.001")


async def test_a_priced_branch_leaves_the_routed_run_unpriced() -> None:
    gateway = Gateway(top="code", script={(CHAT_PATH, _BRANCH): _priced_chat()})

    outcome = await run_direct(gateway)

    assert outcome.document()["selected"]["model"] == _BRANCH
    assert len(gateway.posts(CLASSIFICATIONS_PATH)) == 1
    assert [body["model"] for body in gateway.posts(CHAT_PATH)] == [_BRANCH]
    completed = outcome.steps[-1]
    assert isinstance(completed, Completed)
    assert completed.subtree_cost.pricing_version == UNPRICED
    assert completed.subtree_cost.cost.total_usd == Decimal("0")
    (own,) = [frame for frame in _costs(outcome.steps) if frame.scope == "self"]
    assert own.pricing_version == UNPRICED
    assert (own.usage.input_tokens, own.usage.output_tokens) == (11, 7)
