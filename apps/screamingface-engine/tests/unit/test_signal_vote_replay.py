"""A signal-weighted vote gives the same answer from a cache replay (OME-1289 E4a, SR#10).

FEATURE: ``sf.Vote(weights=sf.signal("cost_usd"))`` weighs each member by the cost of its own model
calls, found through the combine context ``sources``.
STORY: as a researcher, I rerun a cached run and the vote ends the same way, with the same weights,
although the cache hit costs nothing now.
INVARIANT: the signal comes from the call's original accounting (the cache reference), never from
the retained accounting of the replay.

The data file under ``data/combine_contract/`` is what the SDK compiles (the SDK drift guard keeps
it byte-equal), so this runs the real compiler output. The first run is a cache miss, the second a
hit. This is a CHAR test: it passes on its first run by design (units 1 and 3 deliver the behavior).
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx
import pytest
from test_samples_seed_contract import _wrapped_candidate
from test_signal_accounting_connector import _attempt, _cost

from screamingface_engine.combine.builtins import BUILTIN_OPERATORS
from screamingface_engine.request_scope import RequestScope, request_scope
from screamingface_engine.world.candidate_adapter import install_candidate_invocation
from screamingface_engine.world.combine import install_combine_runtime
from screamingface_engine.world.config import ModelSpec
from screamingface_engine.world.connector import AigatewayConfig, build_aigateway_world
from url4.dag import run as url4_run

_CANDIDATE = (
    (Path(__file__).parent / "data" / "combine_contract" / "signal_vote_candidate.url4")
    .read_text(encoding="utf-8")
    .removesuffix("\n")
)
# request model -> (reply, cost in credits); every call has 10 + 4 tokens and 30 ms
_MODELS = {
    "prov/alpha": ("A", "0.004"),
    "prov/beta": ("B", "0.001"),
    "prov/gamma": ("B", "0.002"),
}


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


def _gateway(cache: str) -> Callable[[httpx.Request], httpx.Response]:
    def handle(request: httpx.Request) -> httpx.Response:
        content, cost = _MODELS[json.loads(request.content)["model"]]
        return httpx.Response(
            200, headers={"X-AIGW-Cache": cache}, json=_body(content, cost, cache)
        )

    return handle


async def _run(cache: str) -> dict[str, Any]:
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(_gateway(cache)), base_url="http://aigateway.test"
    )
    world = await build_aigateway_world(
        AigatewayConfig(
            default_model="prov/alpha", models=tuple(ModelSpec(id=model) for model in _MODELS)
        ),
        client=client,
    )
    try:
        install_candidate_invocation(world.node)
        install_combine_runtime(world.node, BUILTIN_OPERATORS)
        with request_scope(RequestScope(origin="run")):
            result = await url4_run(_wrapped_candidate(_CANDIDATE), io=world.node)
    finally:
        await world.aclose()
        await client.aclose()
    record: dict[str, Any] = json.loads(result)
    return record


def _operation(record: dict[str, Any], operation_id: str) -> dict[str, Any]:
    return next(op for op in record["operations"] if op["operation_id"] == operation_id)


def _assert_cost_vote(record: dict[str, Any]) -> None:
    combine = _operation(record, "op_synthesis_1")["combine"]
    assert _operation(record, "op_synthesis_1")["output"] == "A"
    assert combine["signal"] == {"key": "cost_usd", "order": None}
    assert [member["signals"] for member in combine["members"]] == [
        {"cost_usd": 0.004},
        {"cost_usd": 0.001},
        {"cost_usd": 0.002},
    ]
    assert [member["weight"] for member in combine["members"]] == [0.004, 0.001, 0.002]
    # WHY lower case: the text normalizer folds the case of the group value; the output keeps it.
    tally = [(row["value"], row["score"], row["holders"]) for row in combine["tally"]]
    assert [(value, members) for value, _, members in tally] == [
        ("a", ["member_1"]),
        ("b", ["member_2", "member_3"]),
    ]
    assert [score for _, score, _ in tally] == pytest.approx([0.004, 0.003])
    assert combine["chosen"] == ["member_1"]
    assert combine["result"]["status"] == "answered"


@pytest.mark.asyncio
async def test_signal_reduce_replays_identically_from_cache() -> None:
    first = await _run("miss")
    second = await _run("hit")

    _assert_cost_vote(first)
    _assert_cost_vote(second)
    assert (
        _operation(first, "op_synthesis_1")["combine"]
        == _operation(second, "op_synthesis_1")["combine"]
    )
    # The retained accounting keeps its own truth (a hit costs nothing now), which proves the
    # signals above came from the cache reference and not from this run's accounting.
    miss_cost = _operation(first, "op_model_1")["accounting"]["usage"]["cost_usd"]
    hit_cost = _operation(second, "op_model_1")["accounting"]["usage"]["cost_usd"]
    assert hit_cost == "0"
    assert miss_cost != hit_cost
