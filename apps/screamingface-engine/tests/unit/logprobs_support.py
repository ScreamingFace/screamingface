"""Shared fakes for the E4b part 3 logprob-capture tests (unit 3). Not a test module.

FEATURE: the gateway replies recorded by unit 1 (`data/logprobs/`) and a three-member quorum panel
whose member calls ask for `logprobs`, wired like the SDK's compiled Fusion.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

import httpx
from combine_support import spec_text, vote_spec

from screamingface_engine.benchmarks.invocation import evaluate_candidate_recipe
from screamingface_engine.combine.builtins import BUILTIN_OPERATORS
from screamingface_engine.combine.endpoint import COMBINE_ROUTE
from screamingface_engine.world.combine import install_combine_runtime
from screamingface_engine.world.config import ModelSpec
from screamingface_engine.world.connector import AigatewayConfig, build_aigateway_world
from url4 import RelExpr, Text, expr, render, src, struct, text

FIXTURES = Path(__file__).parent / "data" / "logprobs"
REFUSAL = "openrouter_refusal_unsupported_parameters.json"
REFUSAL_BEFORE_LC_E5 = "openrouter_refusal_provider_error.json"
REPLY = "openrouter_reply_with_logprobs.json"
# The oracle: the fixed engine text of the PRD (Delta 4), written by hand, never imported.
FIXED_TEXT = (
    "the model may not return token log-probabilities (sf.Logprob, sf.Entropy), or no endpoint for "
    "the model supports another member parameter; choose another OpenRouter model or remove that "
    "parameter"
)
ASKED: tuple[tuple[str, str], ...] = (("logprobs", "true"),)
ANSWERS = {
    "provider/alpha": "alpha reasons, so 12",
    "provider/beta": "beta says 12",
    "provider/gamma": "gamma says 7",
}
_VOTE = {
    "extract": {"op": "last_number@1", "args": {}},
    "normalize": {"op": "numeric@1", "args": {}},
    "reduce": {"op": "mode@1", "args": {}},
    "select": {"op": "first_holder@1", "args": {}},
}


def fixture(name: str) -> dict[str, Any]:
    """One recorded gateway answer: ``{"status", "body"}``."""
    loaded: dict[str, Any] = json.loads((FIXTURES / name).read_text(encoding="utf-8"))
    return loaded


def recorded(name: str) -> httpx.Response:
    """A NEW response for one recorded answer (a response object is read once)."""
    answer = fixture(name)
    return httpx.Response(answer["status"], json=answer["body"])


def completion_with_logprobs(content: str) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "choices": [
                {
                    "message": {"content": content},
                    "finish_reason": "stop",
                    "logprobs": {
                        "content": [
                            {
                                "token": "secret-token",
                                "bytes": [115],
                                "logprob": -0.5,
                                "top_logprobs": [],
                            }
                        ]
                    },
                }
            ],
            "usage": {"prompt_tokens": 4, "completion_tokens": 1},
        },
    )


def refusing_responder(refusing: Sequence[str]) -> Callable[[httpx.Request], httpx.Response]:
    """Members in ``refusing`` get the recorded 404 refusal; the others answer with logprobs."""

    def respond(request: httpx.Request) -> httpx.Response:
        model = json.loads(request.content)["model"]
        if model in refusing:
            return recorded(REFUSAL)
        return completion_with_logprobs(ANSWERS[model])

    return respond


def panel_candidate(quorum: int, optional: Sequence[int]) -> str:
    """The compiled shape of a quorum Fusion whose member calls ask for logprobs."""
    slots = [
        src(
            expr(
                src(
                    RelExpr(
                        path=f"/{model}",
                        context="$input",
                        intent=text("Answer plainly."),
                        params=ASKED,
                    ),
                    name=f"model_{index}",
                    weight=0.0,
                ),
                intent=Text(f"$model_{index}"),
            ),
            name=f"member_{index}",
            weight=1.0,
            required=index not in optional,
        )
        for index, model in enumerate(ANSWERS, start=1)
    ]
    panel = src(
        expr(*slots, intent=Text(""), broadcast=True, params={"quorum": quorum}),
        name="panel_1",
        weight=0.0,
    )
    synthesis = src(
        RelExpr(
            path=COMBINE_ROUTE,
            context=render(struct({"input": "$input", "panel": "$panel_1"})),
            intent=Text(spec_text(vote_spec(3, **_VOTE))),
            params=(("binding", "synthesis_1"),),
        ),
        name="synthesis_1",
        weight=0.0,
    )
    return render(expr(panel, synthesis, intent=text("$synthesis_1")))


async def evaluate_panel(candidate: str, refusing: Sequence[str]) -> Any:
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(refusing_responder(refusing)),
        base_url="http://aigateway.test",
    )
    world = await build_aigateway_world(
        AigatewayConfig(
            default_model="provider/alpha", models=tuple(ModelSpec(id=m) for m in ANSWERS)
        ),
        client=client,
    )
    install_combine_runtime(world.node, BUILTIN_OPERATORS)
    try:
        return await evaluate_candidate_recipe(world.node, candidate, "what is it?")
    finally:
        await world.aclose()
        await client.aclose()
