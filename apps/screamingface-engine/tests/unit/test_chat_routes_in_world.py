"""The engine's internal routes in each gateway world, and the App's mount table (chat-run CR-S19).

FEATURE: chat-run. `build_world` installs the combine, branch and chat routes in every gateway
world, after the direct-mount snapshot, so none of them is a direct mount.
INVARIANT: the App lists only the direct mounts, as `local.py` does, so an internal route is never
public, and a `[data]` mount on an internal route fails the world build.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

import httpx
import pytest
from test_benchmark_foundation import _benchmark

from screamingface_engine import job_env
from screamingface_engine.benchmarks import BenchmarkRegistry
from screamingface_engine.benchmarks.contract import CANDIDATE_ROUTE
from screamingface_engine.combine.endpoint import COMBINE_ROUTE
from screamingface_engine.world.chat_turn import CHAT_TURN_ROUTE
from screamingface_engine.world.config import WorldConfigError, parse_config, read_world_file
from screamingface_engine.world.factory import build_world, direct_mount_paths
from screamingface_engine.world.models.registry import EMPTY_MODEL_WORLD
from screamingface_engine.world.serving import derive_mount_table
from url4.peer.server import Url4Node

_PUBLIC = "anthropic/claude-haiku-4-5"
_PRIVATE = "byom_" + "0123456789abcdef" * 2 + "/model_v1"
_WORLD = f"""
[aigateway]
base_url = "http://aigateway.test"
default_route = "/{_PUBLIC}"

[[aigateway.models]]
id = "{_PRIVATE}"
web_search = false
public_schema = false
"""

_AIGATEWAY = """
[aigateway]
default_route = "/m"
models = ["m"]
"""

_DATA_ON_CHAT_TURN = (
    _AIGATEWAY
    + '\n[data]\n"'
    + CHAT_TURN_ROUTE
    + '" = { value = "rows", media_type = "text/plain" }\n'
)


def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _request: httpx.Response(500)),
        base_url="http://aigateway.test",
    )


@pytest.mark.asyncio
async def test_app_mount_table_and_openapi_are_unchanged(tmp_path: Path) -> None:  # CR-29
    path = tmp_path / "url4.toml"
    path.write_text(_WORLD)

    table = await derive_mount_table(env={job_env.RUNNER_CONFIG: str(path)}, engine_routes=())

    paths = {mount.path for mount in table.mounts}
    assert not [p for p in paths if p.startswith("/ensemble/")]
    assert f"/{_PUBLIC}" in paths
    assert f"/{_PRIVATE}" in paths
    config = read_world_file({job_env.RUNNER_CONFIG: str(path)}, include_extra_models=True).config
    async with _client() as client:
        node, aclose = await build_world(env={}, config=config, client=client)
        assert aclose is not None
        try:
            assert paths == set(direct_mount_paths(node))
        finally:
            await aclose()


@pytest.mark.asyncio
async def test_a_world_with_benchmarks_installs_each_internal_route_once(tmp_path: Path) -> None:
    config = parse_config(tomllib.loads(_AIGATEWAY), {}, registry=EMPTY_MODEL_WORLD)
    async with _client() as client:
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
            for route in (CHAT_TURN_ROUTE, COMBINE_ROUTE, CANDIDATE_ROUTE):
                assert route in node.processor_routes()
        finally:
            await aclose()


@pytest.mark.asyncio
async def test_a_data_mount_on_an_internal_route_fails_the_world_build() -> None:
    config = parse_config(tomllib.loads(_DATA_ON_CHAT_TURN), {}, registry=EMPTY_MODEL_WORLD)
    async with _client() as client:
        with pytest.raises(WorldConfigError):
            await build_world(env={}, config=config, client=client)
