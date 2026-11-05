"""Run an SDK-compiled Candidate with fake gateway logprobs (E4b part 3, unit 4). Test-only.

``replies`` maps each request model (members AND writer) to its reply text. ``logprobs`` gets the
JSON body of each gateway request and returns the ``choices[0].logprobs`` object for its reply, or
None (the reply has no logprobs). Every call is a cache miss that costs 0.001 credits.
INVARIANT: the token text is synthetic (``tok0``, ``tok0_alt1``); no real reply text is used.
"""

from __future__ import annotations

import json
import math
from collections.abc import Callable, Mapping, Sequence
from typing import Any

import httpx
from _signal_world import _body
from test_samples_seed_contract import _wrapped_candidate

from screamingface_engine.combine.builtins import BUILTIN_OPERATORS
from screamingface_engine.request_scope import RequestScope, request_scope
from screamingface_engine.world.candidate_adapter import install_candidate_invocation
from screamingface_engine.world.combine import install_combine_runtime
from screamingface_engine.world.config import ModelSpec
from screamingface_engine.world.connector import AigatewayConfig, build_aigateway_world
from url4.dag import run as url4_run

LN = math.log  # the tests write a top list as [LN(0.5), LN(0.5)]

# One reply position: (the chosen token's logprob, the logprobs of its top list).
type Position = tuple[float, Sequence[object]]
type LogprobsFor = Callable[[dict[str, Any]], dict[str, Any] | None]


def logprobs_object(positions: Sequence[Position]) -> dict[str, Any]:
    """``choices[0].logprobs`` in the shape of the unit 1 fixture, with synthetic token text."""
    content = [
        {
            "token": f"tok{index}",
            "bytes": list(f"tok{index}".encode()),
            "logprob": logprob,
            "top_logprobs": [
                {
                    "token": f"tok{index}_alt{rank}",
                    "bytes": list(f"tok{index}_alt{rank}".encode()),
                    "logprob": value,
                }
                for rank, value in enumerate(top)
            ],
        }
        for index, (logprob, top) in enumerate(positions)
    ]
    return {"content": content, "refusal": None}


def by_model(table: Mapping[str, Sequence[Position]]) -> LogprobsFor:
    """A ``logprobs`` callback: the positions of the request's model, or None for another model."""

    def answer(body: dict[str, Any]) -> dict[str, Any] | None:
        positions = table.get(body["model"])
        return None if positions is None else logprobs_object(positions)

    return answer


async def run_logprob_candidate(
    candidate: str,
    replies: Mapping[str, str],
    logprobs: LogprobsFor,
    on_request: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    """Run ``candidate`` once on the Case input "what is 2 + 2?" and return the run record."""

    def handle(request: httpx.Request) -> httpx.Response:
        sent = json.loads(request.content)
        if on_request is not None:
            on_request(sent)
        body = _body(replies[sent["model"]], "0.001", "miss")
        reply_logprobs = logprobs(sent)
        if reply_logprobs is not None:
            body["choices"][0]["logprobs"] = reply_logprobs
        return httpx.Response(200, headers={"X-AIGW-Cache": "miss"}, json=body)

    client = httpx.AsyncClient(
        transport=httpx.MockTransport(handle), base_url="http://aigateway.test"
    )
    world = await build_aigateway_world(
        AigatewayConfig(
            default_model=next(iter(replies)),
            models=tuple(ModelSpec(id=model) for model in replies),
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
