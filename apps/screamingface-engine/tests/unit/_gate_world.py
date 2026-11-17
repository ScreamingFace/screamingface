"""Run an SDK-compiled sf.Gate Candidate in the engine world with a mocked gateway (E4c).

Test-only, the ``_signal_world`` pattern with the branch runtime installed too. ``run_gate``
links the Candidate url4 to one case input, answers every model call from a ``{model: reply}``
table (or a callable that sees the request body), counts the calls per model, and returns the
decoded run record. A reply ``FAIL`` is an HTTP 400 (a permanent call failure); a reply ``REFUSE``
is a provider refusal (``finish_reason`` ``content_filter``).
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
from _signal_world import _body

from screamingface_engine.combine.builtins import BUILTIN_OPERATORS
from screamingface_engine.request_scope import RequestScope, request_scope
from screamingface_engine.world.branch import install_branch_runtime
from screamingface_engine.world.candidate_adapter import install_candidate_invocation
from screamingface_engine.world.combine import install_combine_runtime
from screamingface_engine.world.config import ModelSpec
from screamingface_engine.world.connector import AigatewayConfig, build_aigateway_world
from url4 import RelExpr, expr, render, src, text
from url4.dag import run as url4_run

GATE_CONTRACT = Path(__file__).parent / "data" / "gate_contract"
FAIL = "<<fail>>"
REFUSE = "<<refuse>>"

type Reply = str | Callable[[dict[str, Any]], str]


def fixture(name: str) -> str:
    """A committed SDK compile from ``data/gate_contract`` (read in the test, so a gap is RED)."""
    path = GATE_CONTRACT / name
    assert path.exists(), f"gate_contract/{name} is missing - write it with the SDK"
    return path.read_text(encoding="utf-8").removesuffix("\n")


def wrapped(candidate: str, question: str) -> str:
    """The candidate linked to one case input, the way a benchmark invokes it."""
    return render(
        expr(
            src(
                RelExpr(
                    path="/benchmarks/candidate",
                    context=question,
                    intent=text(candidate),
                    params=(("web_search", "false"),),
                ),
                name="answer",
                weight=0.0,
            ),
            intent=text("$answer"),
        )
    )


@dataclass(slots=True)
class Gateway:
    """A fake gateway: one reply per model, every request kept in call order."""

    replies: Mapping[str, Reply]
    delays: Mapping[str, float] = field(default_factory=dict)
    seen: list[dict[str, Any]] = field(default_factory=list)

    def calls(self, model: str) -> int:
        return sum(1 for request in self.seen if request["model"] == model)

    async def handle(self, request: httpx.Request) -> httpx.Response:
        sent = json.loads(request.content)
        self.seen.append(sent)
        model = sent["model"]
        delay = self.delays.get(model)
        if delay:
            await asyncio.sleep(delay)
        reply = self.replies[model]
        content = reply(sent) if callable(reply) else reply
        if content == FAIL:
            return httpx.Response(
                400,
                json={"error": {"code": "model_parameter_invalid", "message": "fixed refusal"}},
            )
        body = _body("" if content == REFUSE else content, "0.001", "miss")
        if content == REFUSE:
            body["choices"][0]["finish_reason"] = "content_filter"
        return httpx.Response(200, headers={"X-AIGW-Cache": "miss"}, json=body)


async def run_gate(
    candidate: str, gateway: Gateway, question: str = "what is 2 + 2?"
) -> dict[str, Any]:
    """Run ``candidate`` once on ``question`` and return the run record."""

    client = httpx.AsyncClient(
        transport=httpx.MockTransport(gateway.handle), base_url="http://aigateway.test"
    )
    world = await build_aigateway_world(
        AigatewayConfig(
            default_model=next(iter(gateway.replies)),
            models=tuple(ModelSpec(id=model) for model in gateway.replies),
        ),
        client=client,
    )
    try:
        install_candidate_invocation(world.node)
        install_combine_runtime(world.node, BUILTIN_OPERATORS)
        install_branch_runtime(world.node)
        with request_scope(RequestScope(origin="run")):
            result = await url4_run(wrapped(candidate, question), io=world.node)
    finally:
        await world.aclose()
        await client.aclose()
    record: dict[str, Any] = json.loads(result)
    return record


def operations(record: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    """The run record's operations by id."""
    return {op["operation_id"]: op for op in record.get("operations") or ()}
