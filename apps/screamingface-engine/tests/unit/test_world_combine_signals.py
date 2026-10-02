"""The combine route next to member model calls (OME-1289 E4a gap-closure, unit 1).

FEATURE: a combine step runs after its member calls; a member that fails still fails the case,
and the route reads each member's accounting by exact call fingerprint.
"""

from __future__ import annotations

import pytest
from combine_support import FAKE_REGISTRY, spec_text, vote_spec

from screamingface_engine.combine.endpoint import COMBINE_ROUTE
from screamingface_engine.operation_calls import capture_operation_calls
from screamingface_engine.world.combine import install_combine_runtime
from url4 import RelExpr, Text, expr, render, src, struct, text
from url4.core.errors import ResolutionError
from url4.io.static import StaticIOLayer
from url4.peer.server import Request, Url4Node

# --- AB#6 -------------------------------------------------------------------------------------


def _member_down(request: Request) -> str:
    raise ResolutionError("down", code="upstream_error", permanent=True)


def _failing_member_expression() -> str:
    context = render(struct({"input": "$input", "outputs": {"member_1": "$model_1"}}))
    return render(
        expr(
            src(
                RelExpr(path="/provider/down", context="$input", intent=text("Answer plainly.")),
                name="model_1",
                weight=0.0,
            ),
            src(
                RelExpr(
                    path=COMBINE_ROUTE,
                    context=context,
                    intent=Text(spec_text(vote_spec(1))),
                    params=(("binding", "synthesis_1"),),
                ),
                name="synthesis_1",
                weight=0.0,
            ),
            intent=text("$synthesis_1"),
        )
    )


@pytest.mark.asyncio
async def test_member_transport_error_still_fails_the_case() -> None:
    node = Url4Node("t", outbound=StaticIOLayer())
    node.endpoint("/provider/down")(_member_down)
    install_combine_runtime(node, FAKE_REGISTRY)
    with capture_operation_calls() as calls:
        with pytest.raises(ResolutionError) as caught:
            await node.evaluate(_failing_member_expression(), env={"input": "q"})
    assert caught.value.code == "upstream_error"
    assert all(call.combine is None for call in calls)
