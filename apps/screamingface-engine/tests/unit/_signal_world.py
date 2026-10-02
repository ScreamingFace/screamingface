"""Run an SDK-compiled Candidate in the engine world with a mocked gateway (OME-1289 E4a).

Test-only. ``run_candidate`` links the Candidate url4 to one case, answers every model call from a
``{model: (reply, cost in credits)}`` table (each call has 10 + 4 tokens and 30 ms), and returns the
decoded run record. ``cache`` is ``"miss"`` (the gateway lists the succeeded attempt) or ``"hit"``
(the attempt is carried as the cache reference), so one test can run a miss and then a replay.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from typing import Any

import httpx
from test_samples_seed_contract import _wrapped_candidate
from test_signal_accounting_connector import _attempt, _cost

from screamingface_engine.combine.builtins import BUILTIN_OPERATORS
from screamingface_engine.request_scope import RequestScope, request_scope
from screamingface_engine.world.candidate_adapter import install_candidate_invocation
from screamingface_engine.world.combine import install_combine_runtime
from screamingface_engine.world.config import ModelSpec
from screamingface_engine.world.connector import AigatewayConfig, build_aigateway_world
from url4.dag import run as url4_run


def _usage_accounting(attempts: list[dict[str, Any]], cache: dict[str, Any]) -> dict[str, Any]:
    return {
        "capture_status": "complete" if attempts else "not_applicable",
        "omitted_attempts": 0,
        "attempts": attempts,
        "cache": cache,
    }


def _body(content: str, cost: str, cache: str) -> dict[str, Any]:
    """A gateway reply: a miss lists the succeeded attempt, a hit carries it as the reference."""

    reference = {
        "usage": {"input": {"total": 10}, "output": {"total": 4}},
        "direct_cost": _cost(cost),
        "latency": {"provider_latency_ms": 30},
    }
    hit = cache == "hit"
    accounting = _usage_accounting(
        [] if hit else [_attempt("succeeded", (10, 4), 30, cost)],
        {"status": cache, "reference": reference if hit else None},
    )
    return {
        "choices": [{"message": {"content": content}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 4},
        "_aigw": {
            "usage_accounting": accounting,
            "request_economics": {
                "direct_cost_status": "not_applicable" if hit else "complete",
                "known_direct_cost_subtotals": [],
            },
        },
    }


def _gateway(
    models: Mapping[str, tuple[str, str]], cache: str
) -> Callable[[httpx.Request], httpx.Response]:
    def handle(request: httpx.Request) -> httpx.Response:
        content, cost = models[json.loads(request.content)["model"]]
        return httpx.Response(
            200, headers={"X-AIGW-Cache": cache}, json=_body(content, cost, cache)
        )

    return handle


async def run_candidate(
    candidate: str, models: Mapping[str, tuple[str, str]], cache: str
) -> dict[str, Any]:
    """Run ``candidate`` once and return the run record (``operations`` and the rest)."""

    client = httpx.AsyncClient(
        transport=httpx.MockTransport(_gateway(models, cache)), base_url="http://aigateway.test"
    )
    world = await build_aigateway_world(
        AigatewayConfig(
            default_model=next(iter(models)), models=tuple(ModelSpec(id=model) for model in models)
        ),
        client=client,
    )
    try:
        install_candidate_invocation(world.node)
        install_combine_runtime(world.node, BUILTIN_OPERATORS)
        with request_scope(RequestScope(origin="run")):
            result = await url4_run(_wrapped_candidate(candidate), io=world.node)
    finally:
        await world.aclose()
        await client.aclose()
    record: dict[str, Any] = json.loads(result)
    return record
