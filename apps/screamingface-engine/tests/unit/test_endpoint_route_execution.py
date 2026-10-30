"""A configured-endpoint chat route runs through the Engine without a list call (OME-1770).

FEATURE: hosted BYOM, Unit 2. The Engine holds no endpoint URL and no key. It sends the declared
route's id with the caller's identity, and the Gateway picks the (account, provider instance)
Connection. A subsidized route in the same run keeps its own path through the same Gateway.

STORY: as a granted caller I run one expression that fans out to my endpoint's model and to a
subsidized model and reduces their answers, with no prior catalog call, on a cold run world or
a warm worker's shared world.

Child inheritance: a cold child reads the runner pod's world config path, which no App-written
message carries, and a warm child builds the private route from that same file before its run.

WHY substitutes: this proves the Engine half (route, identity, payload) on a fake Gateway. The
queue, a real worker and the real Gateway together are the hosted mixed Fusion check, which needs
the Linux NATS/JetStream environment and stays pending; nothing here claims it.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import httpx
import pytest

from screamingface_engine import job_env
from screamingface_engine.runner.main import build_executor, warm_up
from screamingface_engine.runner_queue import decode_message, encode_message
from screamingface_engine.worker.supervisor import cold_child_env
from screamingface_engine.world.config import AigatewaySection, ModelSpec, WorldConfig
from screamingface_engine.world.factory import SharedWorld, build_world
from url4.io.layer import SupportsProcessorRoutes

pytestmark = pytest.mark.no_default_scope

_ENDPOINT = "byom_" + "0123456789abcdef" * 2
_BYOM = f"{_ENDPOINT}/model_v1"
_SUBSIDIZED = "anthropic/claude-haiku-4-5"
_CALLER = "caller@x.test"
_MIXED = f"(/{_BYOM}('q')!'one', /{_SUBSIDIZED}('q')!'two')!'combine'"


def _config() -> WorldConfig:
    return WorldConfig(
        aigateway=AigatewaySection(
            base_url="http://aigateway.test",
            default_model=_SUBSIDIZED,
            models=(
                ModelSpec(id=_SUBSIDIZED, web_search=False),
                ModelSpec(id=_BYOM, web_search=False, public_schema=False),
            ),
        )
    )


class _Gateway:
    """Answers every chat call and records every request, whatever its path."""

    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []

    async def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": "answer"}}],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
            },
        )


Runner = Callable[[httpx.AsyncClient, dict[str, str]], Any]


async def _cold(client: httpx.AsyncClient, env: dict[str, str]) -> None:
    """A per-run world, built for this run from the run's env: a cold child."""
    async for _ in build_executor(env, _config(), client=client).execute(_MIXED):
        pass


async def _warm(client: httpx.AsyncClient, env: dict[str, str]) -> None:
    """A world built ahead with no caller, then handed this run: a warm child."""
    shared, aclose = await build_world(env={}, config=_config(), client=client)
    try:
        provider = lambda: SharedWorld(io=shared, section=None)  # noqa: E731 - binding read
        async for _ in build_executor(env, shared_world_provider=provider).execute(_MIXED):
            pass
    finally:
        if aclose is not None:
            await aclose()


@asynccontextmanager
async def _gateway() -> AsyncIterator[tuple[_Gateway, httpx.AsyncClient]]:
    gateway = _Gateway()
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(gateway.handle), base_url="http://aigateway.test"
    ) as client:
        yield gateway, client


@pytest.mark.asyncio
@pytest.mark.parametrize("run", [_cold, _warm], ids=["cold", "warm"])
async def test_a_mixed_run_reaches_both_routes_with_the_callers_identity_and_no_list_call(
    run: Runner,
) -> None:
    async with _gateway() as (gateway, client):
        await run(client, job_env.identity_to_env({"X-User-Email": _CALLER}))

    # No catalog, details or admission call: the declared route is enough to execute.
    assert {request.url.path for request in gateway.requests} == {"/v1/chat/completions"}
    bodies = [json.loads(request.content) for request in gateway.requests]
    assert sorted(body["model"] for body in bodies) == sorted([_BYOM, _SUBSIDIZED, _SUBSIDIZED])
    for request, body in zip(gateway.requests, bodies, strict=True):
        # The Gateway chooses the Connection from this identity; the Engine sends no key.
        assert request.headers["X-User-Email"] == _CALLER
        assert "Authorization" not in request.headers
        # A seedless run sends no seed, so the endpoint contract never sees one.
        assert "seed" not in body
    (byom,) = [body for body in bodies if body["model"] == _BYOM]
    assert "tools" not in byom and "tool_choice" not in byom


@pytest.mark.asyncio
@pytest.mark.parametrize("run", [_cold, _warm], ids=["cold", "warm"])
async def test_a_run_without_an_identity_sends_none_and_borrows_no_one_elses(
    run: Runner,
) -> None:
    """No fallback: an anonymous run reaches the Gateway anonymous, and the Gateway refuses it."""
    async with _gateway() as (gateway, client):
        await run(client, {})

    assert gateway.requests
    assert all("X-User-Email" not in request.headers for request in gateway.requests)


def test_the_queued_run_for_a_private_route_carries_only_the_per_run_env() -> None:
    """The queue message names the route and the caller, never an endpoint or a credential."""
    env = decode_message(encode_message("topic-1", _MIXED, 60, identity={"X-User-Email": _CALLER}))

    assert set(env) <= job_env.WRITTEN_BY_APP
    assert env[job_env.EXPRESSION] == _MIXED
    assert job_env.identity_from_env(env) == {"X-User-Email": _CALLER}
    assert job_env.RUNNER_CONFIG not in env


# --- child inheritance --------------------------------------------------------------------------

# Where the chart mounts the private world on the runner pod (`worldConfigDir` + `/url4.toml`).
_POD_WORLD = "/etc/screamingface-engine/world/url4.toml"


class _Publisher:
    def __init__(self, url: str) -> None:
        self.url = url

    async def ensure_stream(self, topic: str) -> None:
        pass


def test_a_cold_child_inherits_the_runner_pods_world_config() -> None:
    """The run's message carries no config path, so the child reads exactly the pod's file."""
    pod = {job_env.RUNNER_CONFIG: _POD_WORLD, job_env.NATS_URL: "nats://broker:4222"}
    run = decode_message(encode_message("topic-1", _MIXED, 60, identity={"X-User-Email": _CALLER}))

    child = cold_child_env(pod, run, 4)

    assert child[job_env.RUNNER_CONFIG] == _POD_WORLD
    assert child[job_env.EXPRESSION] == _MIXED


@pytest.mark.asyncio
async def test_a_warm_child_builds_the_private_route_from_the_pods_file(tmp_path: Path) -> None:
    world = tmp_path / "url4.toml"
    world.write_text(
        f'[aigateway]\nbase_url = "http://aigateway.invalid"\ndefault_route = "/{_SUBSIDIZED}"\n\n'
        f'[[aigateway.models]]\nid = "{_BYOM}"\nweb_search = false\npublic_schema = false\n'
    )

    state = await warm_up({job_env.RUNNER_CONFIG: str(world)}, publisher_factory=_Publisher)
    try:
        assert state.world_ok and state.shared is not None
        assert isinstance(state.shared.io, SupportsProcessorRoutes)
        assert f"/{_BYOM}" in state.shared.io.processor_routes()
    finally:
        if state.world_aclose is not None:
            await state.world_aclose()
