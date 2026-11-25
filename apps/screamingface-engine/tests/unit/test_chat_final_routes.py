"""The chat final-step routes of a gateway world (tool-calls §3.2, CR-S19).

FEATURE: tool-calls §3.2. `build_world` registers one final-step route per declared model, on the
gateway world's own node.
INVARIANT: the final routes are installed after the direct-mount snapshot, so none is a direct
mount.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

import httpx
import pytest
from _chat_final_world import TOOL, Reply, ToolGateway, call_final, final_route, final_turn
from test_benchmark_foundation import _benchmark

from screamingface_engine.benchmarks import BenchmarkRegistry
from screamingface_engine.world.config import WorldConfigError, parse_config
from screamingface_engine.world.factory import build_world, direct_mount_paths
from screamingface_engine.world.models.registry import EMPTY_MODEL_WORLD
from url4.peer.server import Url4Node

_AIGATEWAY = '[aigateway]\ndefault_route = "/m"\nmodels = ["m", "prov/a"]\n'


def _gateway() -> ToolGateway:
    return ToolGateway({"m": Reply(content="ok"), "prov/a": Reply(content="ok")})


def _client(gateway: ToolGateway) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=httpx.MockTransport(gateway.handle), base_url="http://aigateway.test"
    )


@pytest.mark.asyncio
async def test_chat_routes_are_not_direct_mounts_and_have_gateway_state() -> None:  # TC-12
    gateway = _gateway()
    config = parse_config(tomllib.loads(_AIGATEWAY), {}, registry=EMPTY_MODEL_WORLD)
    async with _client(gateway) as client:
        node, aclose = await build_world(env={}, config=config, client=client)
        assert aclose is not None
        try:
            assert isinstance(node, Url4Node)
            for model in ("m", "prov/a"):
                assert final_route(model) in node.processor_routes()
                assert final_route(model) not in direct_mount_paths(node)
            text = await call_final(node, "prov/a", turn=final_turn())
            assert text == "ok"
            assert len(gateway.seen) == 1
            assert gateway.seen[0]["model"] == "prov/a"
            assert gateway.seen[0]["tools"] == [TOOL]
        finally:
            await aclose()


@pytest.mark.asyncio
async def test_a_world_with_benchmarks_installs_each_final_route_once(tmp_path: Path) -> None:
    config = parse_config(tomllib.loads(_AIGATEWAY), {}, registry=EMPTY_MODEL_WORLD)
    async with _client(_gateway()) as client:
        node, aclose = await build_world(
            env={},
            config=config,
            client=client,
            benchmarks=BenchmarkRegistry((_benchmark(),)),
            benchmark_assets_root=tmp_path,
        )
        assert aclose is not None
        try:
            assert isinstance(node, Url4Node)
            assert list(node.processor_routes()).count(final_route("m")) == 1
        finally:
            await aclose()


@pytest.mark.asyncio
async def test_a_data_mount_on_a_final_route_fails_the_world_build() -> None:
    declared = (
        _AIGATEWAY
        + '\n[data]\n"'
        + final_route("m")
        + '" = { value = "rows", media_type = "text/plain" }\n'
    )
    config = parse_config(tomllib.loads(declared), {}, registry=EMPTY_MODEL_WORLD)
    async with _client(_gateway()) as client:
        with pytest.raises(WorldConfigError):
            await build_world(env={}, config=config, client=client)
