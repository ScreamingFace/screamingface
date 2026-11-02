"""A run's own frames never list the routes this Engine declares (OME-1770, OME-1777).

FEATURE: hosted BYOM, Unit 2. A private configured-endpoint route is executable but unpublished:
a caller who never named it must not learn it exists.

WHY this shape: a nested peer call may pick its own `processor=`, and an unknown id is resolved
only when a real fan-out reduce needs it. That resolution used to raise an error listing every
declared route, private ones included, and the run's terminal frame carried that text to the
caller's own WebSocket. Two public calls and a reduce are what reach it; a nested expression of
literals never does.

INVARIANT: the refusal keeps its code and stays permanent; it names the id the caller passed and
no route, on the HTTP answer and on every frame `/ws` replays, for a cold and a warm run.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, MutableMapping
from contextlib import asynccontextmanager
from typing import Any
from urllib.parse import quote, urlencode

import httpx
import pytest
from fastapi import FastAPI

from screamingface_engine.adapters.inprocess import InProcessJobRunner
from screamingface_engine.app import create_app
from screamingface_engine.config import Settings
from screamingface_engine.runner.main import build_executor
from screamingface_engine.testing import InMemoryEventStream
from screamingface_engine.world.config import AigatewaySection, ModelSpec, WorldConfig
from screamingface_engine.world.factory import SharedWorld, build_world

pytestmark = pytest.mark.no_default_scope

_PRIVATE = "byom_" + "a" * 32 + "/private_alias"
_PUBLIC = "anthropic/claude-haiku-4-5"
_INNER = f"(/{_PUBLIC}('x')!'one', /{_PUBLIC}('y')!'two')!'combine'"
# The caller's whole expression: one nested peer call whose reduce asks for a processor id the
# node does not declare. It names no private route.
_EXPRESSION = f"(/v1?processor=never&q={quote(_INNER, safe='')})!'$1'"
_ATTACH = {
    "specversion": "1.0",
    "id": "attach",
    "source": "/test",
    "type": "ai.url4.attach",
    "data": {},
}


def _config() -> WorldConfig:
    return WorldConfig(
        aigateway=AigatewaySection(
            base_url="http://aigateway.test",
            default_model=_PUBLIC,
            models=(
                ModelSpec(id=_PUBLIC, web_search=False),
                ModelSpec(id=_PRIVATE, web_search=False, public_schema=False),
            ),
        )
    )


class _Gateway:
    """Answers every chat call and records which model each one asked for."""

    def __init__(self) -> None:
        self.models: list[str] = []

    async def handle(self, request: httpx.Request) -> httpx.Response:
        self.models.append(json.loads(request.content)["model"])
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": "answer"}}],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
            },
        )


@asynccontextmanager
async def _engine(*, warm: bool) -> AsyncIterator[tuple[FastAPI, _Gateway]]:
    """The App with an in-process runner: a per-run world (cold) or one built ahead (warm)."""
    gateway = _Gateway()
    stream = InMemoryEventStream()
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(gateway.handle), base_url="http://aigateway.test"
    ) as client:
        aclose = None
        if warm:
            node, aclose = await build_world(env={}, config=_config(), client=client)
            provider = lambda: SharedWorld(io=node, section=None)  # noqa: E731 - binding read
            runner = InProcessJobRunner(
                stream, lambda env: build_executor(env, shared_world_provider=provider)
            )
        else:
            runner = InProcessJobRunner(
                stream, lambda env: build_executor(env, _config(), client=client)
            )
        app = create_app(
            Settings(jwt_secret="private-route-frames-secret-0000000"),
            stream=stream,
            job_runner=runner,
        )
        try:
            yield app, gateway
        finally:
            await runner.aclose()
            if aclose is not None:
                await aclose()


async def _replay(app: FastAPI, token: str) -> list[dict[str, Any]]:
    """Every frame the caller's own `/ws` replays after an attach, through the terminal one."""
    inbox: asyncio.Queue[MutableMapping[str, Any]] = asyncio.Queue()
    await inbox.put({"type": "websocket.connect"})
    await inbox.put({"type": "websocket.receive", "text": json.dumps(_ATTACH)})
    frames: list[dict[str, Any]] = []

    async def send(message: MutableMapping[str, Any]) -> None:
        if message["type"] != "websocket.send":
            return
        frames.append(json.loads(message.get("text") or message["bytes"]))
        if frames[-1]["type"] == "ai.url4.terminated":
            await inbox.put({"type": "websocket.disconnect", "code": 1000})

    scope: MutableMapping[str, Any] = {
        "type": "websocket",
        "asgi": {"version": "3.0"},
        "scheme": "ws",
        "path": "/ws",
        "raw_path": b"/ws",
        "root_path": "",
        "query_string": urlencode({"ticket": token}).encode(),
        "headers": [],
        "client": ("127.0.0.1", 1),
        "server": ("engine.test", 80),
        "subprotocols": ["cloudevents.json"],
        "state": {},
    }
    await asyncio.wait_for(app(scope, inbox.get, send), timeout=5)
    return frames


@pytest.mark.asyncio
@pytest.mark.parametrize("warm", [False, True], ids=["cold", "warm"])
async def test_an_unknown_nested_processor_names_no_route_on_the_callers_socket(
    warm: bool,
) -> None:
    async with _engine(warm=warm) as (app, gateway):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://engine.test"
        ) as caller:
            token = (await caller.post("/token")).json()["token"]
            response = await caller.get(
                "/",
                params={"q": _EXPRESSION},
                headers={"X-User-Email": "outsider@x.test", "URL4-Capability": token},
            )
        frames = await _replay(app, token)

    # Both public calls ran, so the reduce really resolved the unknown processor; the private
    # route was never called.
    assert gateway.models == [_PUBLIC, _PUBLIC]
    assert _PRIVATE not in response.text
    terminated = frames[-1]
    assert terminated["type"] == "ai.url4.terminated"
    error = terminated["data"]["error"]
    assert (error["code"], error["permanent"]) == ("unknown_processor", True)
    assert "never" in error["message"]
    assert _PUBLIC not in error["message"], "the refusal must list no route at all"
    assert [frame for frame in frames if _PRIVATE in json.dumps(frame)] == []
