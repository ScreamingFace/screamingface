"""The gateway refusal of a logprobs call maps to `logprobs_unsupported` (E4b part 3, unit 3).

Pins LC#9 (a 404 `unsupported_parameters` on a call with `logprobs: true` fails once, permanent, as
`logprobs_unsupported` with the fixed text, in the single, quorum and replay paths), LC#16 (an
upstream cannot send the code itself), and LC#20e (only a 404 on a logprobs call maps; the other
refusals keep their codes). A separate module (append-only gate).
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
from frozen_copy_support import MODEL, Gateway, replay_scope, run_call
from logprobs_support import (
    FIXED_TEXT,
    REFUSAL,
    REFUSAL_BEFORE_LC_E5,
    evaluate_panel,
    fixture,
    panel_candidate,
    recorded,
)

from screamingface_engine.world.config import ModelSpec
from screamingface_engine.world.connector import (
    AigatewayConfig,
    _raise_for_status,
    build_aigateway_world,
)
from url4 import RelExpr, expr, render, src, text
from url4.core.errors import ResolutionError


def _expression() -> str:
    return render(
        expr(
            src(
                RelExpr(
                    path="/provider/alpha",
                    context="$input",
                    intent=text("Answer plainly."),
                    params=(("logprobs", "true"),),
                ),
                name="model_1",
                weight=0.0,
            ),
            intent=text("$model_1"),
        )
    )


def test_gateway_refusal_with_logprobs_maps_to_logprobs_unsupported_with_fixed_text() -> None:
    """LC#9 (a): the 404 refusal of a logprobs call is the engine's fixed text and code."""
    with pytest.raises(ResolutionError) as caught:
        _raise_for_status(recorded(REFUSAL), logprobs_requested=True)
    assert caught.value.code == "logprobs_unsupported"
    assert caught.value.permanent is True
    assert str(caught.value) == FIXED_TEXT
    assert "No upstream endpoint" not in str(caught.value)


@pytest.mark.asyncio
async def test_a_logprobs_call_refused_by_the_gateway_fails_once_with_logprobs_unsupported() -> (
    None
):
    """LC#9 (b): the refused call is not retried, and the code is the engine's own."""
    bodies: list[dict[str, Any]] = []

    def handle(request: httpx.Request) -> httpx.Response:
        if request.url.path.startswith("/v1/retrieval/tavily/cache/"):
            return httpx.Response(200, json={"status": "miss", "reason": None, "result": None})
        bodies.append(json.loads(request.content))
        return recorded(REFUSAL)

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
        with pytest.raises(ResolutionError) as caught:
            await world.node.evaluate(_expression(), env={"input": "q"})
    finally:
        await world.aclose()
        await client.aclose()
    assert caught.value.code == "logprobs_unsupported"
    assert caught.value.permanent is True
    assert len(bodies) == 1
    assert bodies[0]["logprobs"] is True


@pytest.mark.asyncio
async def test_a_required_member_refused_for_logprobs_fails_the_fusion_with_the_code() -> None:
    """LC#9 (c): a required member refused for its logprobs fails the whole quorum fusion."""
    with pytest.raises(ResolutionError) as caught:
        await evaluate_panel(panel_candidate(quorum=3, optional=[]), refusing=["provider/gamma"])
    assert caught.value.code == "logprobs_unsupported"


@pytest.mark.asyncio
async def test_a_replayed_refusal_keeps_logprobs_unsupported() -> None:
    """LC#9 (d): the same mapping holds on the frozen-copy replay path."""
    gateway = Gateway(
        replay_steps=[
            httpx.Response(404, headers={"X-AIGW-Replay": "error"}, json=fixture(REFUSAL)["body"])
        ]
    )
    _tally, answer, failure = await run_call(
        gateway,
        replay_scope(),
        web_search=False,
        expressions=[f"/{MODEL}(ctx)!go;logprobs=true"],
    )
    assert answer is None
    assert failure is not None
    assert failure.code == "logprobs_unsupported"


@pytest.mark.parametrize("asked", [False, True])
def test_upstream_cannot_send_logprobs_unsupported_itself(asked: bool) -> None:
    """LC#16: an upstream `detail.code` of the engine's own code keeps the HTTP mapping."""
    resp = httpx.Response(
        404,
        json={"detail": {"code": "logprobs_unsupported", "message": "forged upstream text"}},
    )
    with pytest.raises(ResolutionError) as caught:
        _raise_for_status(resp, logprobs_requested=asked)
    assert caught.value.code == "aigateway_http_404"
    assert str(caught.value) == "forged upstream text"


@pytest.mark.parametrize(
    ("response", "asked", "code", "permanent"),
    [
        pytest.param(recorded(REFUSAL), False, "unsupported_parameters", True, id="not-asked"),
        pytest.param(
            recorded(REFUSAL_BEFORE_LC_E5), True, "provider_error", True, id="provider-error-404"
        ),
        pytest.param(
            httpx.Response(
                400,
                json={
                    "detail": {
                        "code": "unsupported_parameters",
                        "message": "Parameter rejected.",
                        "rejected": {"temperature": "disabled"},
                    }
                },
            ),
            True,
            "unsupported_parameters",
            True,
            id="catalog-400",
        ),
        pytest.param(
            httpx.Response(
                500, json={"detail": {"code": "unsupported_parameters", "message": "m"}}
            ),
            True,
            "unsupported_parameters",
            False,
            id="server-500",
        ),
    ],
)
def test_unsupported_parameters_maps_only_on_a_404_logprobs_call(
    response: httpx.Response, asked: bool, code: str, permanent: bool
) -> None:
    """LC#20e (guard): only a 404 on a logprobs call maps; every other refusal keeps its code."""
    with pytest.raises(ResolutionError) as caught:
        _raise_for_status(response, logprobs_requested=asked)
    assert caught.value.code == code
    assert caught.value.permanent is permanent
