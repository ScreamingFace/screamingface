"""The connector puts the request scope's ``response_format`` in the chat body, and only then.

FEATURE: OME-1478 PR 1 of 2. HLE's official judge demands strict JSON output, an OpenAI
``response_format`` object. url4 params cannot hold JSON, so the gateway judge sets the format on
the request scope around that one judge call, and the connector, which already reads the scope
on every call, writes it into the body.

INVARIANT the suite defends: a scope with no format adds nothing, so every other call's body is
byte-identical to before, and every recorded replay keyed on the body still hits.

Stand-ins: ``_Gateway`` stands in for the AI Gateway over httpx's mock transport and answers one
fixed reply; ``prov/judge-x`` is a stand-in route name.
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from screamingface_engine.request_scope import RequestScope, request_scope
from screamingface_engine.world.config import ModelSpec
from screamingface_engine.world.connector import AigatewayConfig, build_aigateway_world
from screamingface_engine.world.request_parameters import response_format_body_field
from url4.dag import run as url4_run

_MODEL: str = "prov/judge-x"

#: A judge's strict JSON format, shaped like HLE's: a yes/no verdict.
_FORMAT: dict[str, Any] = {
    "type": "json_schema",
    "json_schema": {
        "name": "Verdict",
        "schema": {
            "type": "object",
            "properties": {"correct": {"type": "string", "enum": ["yes", "no"]}},
            "required": ["correct"],
            "additionalProperties": False,
        },
        "description": "",
        "strict": True,
    },
}


class _Gateway:
    """Records every chat body and answers one fixed judge reply."""

    def __init__(self) -> None:
        self.bodies: list[dict[str, Any]] = []

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.bodies.append(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "choices": [
                    {"message": {"content": '{"correct": "yes"}'}, "finish_reason": "stop"}
                ],
                "usage": {"prompt_tokens": 4, "completion_tokens": 2},
            },
        )


async def _one_call(response_format: str | None) -> dict[str, Any]:
    """One bare model call (a judge's shape) under a run scope; returns the body sent."""

    gateway = _Gateway()
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(gateway.handle), base_url="http://aigateway.test"
    )
    world = await build_aigateway_world(
        AigatewayConfig(default_model=_MODEL, models=(ModelSpec(id=_MODEL),)), client=client
    )
    try:
        with request_scope(RequestScope(origin="run", response_format=response_format)):
            await url4_run(f"/{_MODEL}('Is Paris the capital?')!'grade'", io=world.node)
    finally:
        await world.aclose()
        await client.aclose()
    [body] = gateway.bodies
    return body


def test_no_format_adds_no_field() -> None:
    assert response_format_body_field(None) == {}


def test_a_format_becomes_the_openai_object() -> None:
    assert response_format_body_field(json.dumps(_FORMAT)) == {"response_format": _FORMAT}


@pytest.mark.asyncio
async def test_a_scope_with_a_format_sends_it_in_the_chat_body() -> None:
    body: dict[str, Any] = await _one_call(json.dumps(_FORMAT))

    assert body["response_format"] == _FORMAT


@pytest.mark.asyncio
async def test_a_scope_with_no_format_sends_todays_body() -> None:
    """THE acceptance criterion: an ordinary call's body keeps exactly its two keys."""

    body: dict[str, Any] = await _one_call(None)

    assert set(body) == {"model", "messages"}
