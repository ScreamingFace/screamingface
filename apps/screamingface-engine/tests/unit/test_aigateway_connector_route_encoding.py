"""A call through a `~`-encoded route reaches aigateway under the real, colon-bearing id.

FEATURE: OME-873 — `ModelSpec.id` is always the url4-route form; the connector recovers the
real gateway id (`decode_route_id`) exactly at the wire boundary and for usage reporting, so an
`aigateway_only` model (colon-bearing) is both addressable from an expression AND billed/served
correctly.

Self-contained: a minimal aigateway double, not the full `_MockAigateway` in
`test_aigateway_connector.py` (tool loop, Tavily, multi-route) — this unit needs only "does the
wire body carry the real id".
"""

from __future__ import annotations

import json

import httpx
import pytest

from screamingface_engine.world.config import ModelSpec
from screamingface_engine.world.connector import AigatewayConfig, build_aigateway_world
from url4.dag import run as url4_run
from url4.observe import ObservationEvent, Usage

pytestmark = pytest.mark.asyncio

_REAL_ID = "huggingface/openai/gpt-oss-120b:cerebras"
_ROUTE_ID = "huggingface/openai/gpt-oss-120b~cerebras"


class _Recorder:
    def __init__(self) -> None:
        self.events: list[ObservationEvent] = []

    def on_event(self, event: ObservationEvent) -> None:
        self.events.append(event)


class _MinimalAigateway:
    """Records every `/v1/chat/completions` body and answers with fixed content."""

    def __init__(self, content: str = "hello from cerebras") -> None:
        self.requests: list[httpx.Request] = []
        self._content = content

    def _handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": self._content}}],
                "usage": {"prompt_tokens": 11, "completion_tokens": 7, "total_tokens": 18},
            },
        )

    def client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            transport=httpx.MockTransport(self._handle), base_url="http://aigateway.test"
        )

    def bodies(self) -> list[dict]:
        return [json.loads(r.content) for r in self.requests]


async def test_a_call_through_the_encoded_route_sends_the_real_id_on_the_wire() -> None:
    gw = _MinimalAigateway()
    cfg = AigatewayConfig(models=(ModelSpec(id=_ROUTE_ID),), default_model=_ROUTE_ID)
    async with gw.client() as client:
        world = await build_aigateway_world(cfg, client=client)

        result = await url4_run(f"/{_ROUTE_ID}(ctx)!go", io=world.node)

    assert result == "hello from cerebras"
    bodies = gw.bodies()
    assert len(bodies) == 1
    # The wire model field is the REAL, colon-bearing id — never the route id, which is not
    # a model aigateway knows about.
    assert bodies[0]["model"] == _REAL_ID


async def test_usage_is_reported_under_the_real_id_not_the_route_id() -> None:
    gw = _MinimalAigateway()
    cfg = AigatewayConfig(models=(ModelSpec(id=_ROUTE_ID),), default_model=_ROUTE_ID)
    recorder = _Recorder()
    async with gw.client() as client:
        world = await build_aigateway_world(cfg, client=client)

        await url4_run(f"/{_ROUTE_ID}(ctx)!go", io=world.node, observer=recorder)

    usage_events = [e for e in recorder.events if isinstance(e, Usage)]
    assert len(usage_events) == 1
    assert usage_events[0].model == _REAL_ID
    assert usage_events[0].provider == "huggingface"
