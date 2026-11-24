"""`/route-answer` is one world endpoint on every Gateway world (OME-1822).

FEATURE: BYOM routing pilot (spec 3.2, 4.1). `build_world` registers `/route-answer` beside
`/classify`, before the read-side mounts and the direct-mount snapshot, whatever the world's
profiles. A world with no `[routing]` still serves the route and answers every profile as
unknown, so a profile can be added without a new Engine route.

INVARIANT: composing a world and listing its mounts call no model and read no metadata; only a
run does.
"""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Any

import pytest
from routing_support import (
    GATEWAY_TOML,
    PROFILE,
    PUBLIC,
    Gateway,
    context,
    query,
    run_direct,
    world_config,
    write_world,
)

from screamingface_engine import job_env
from screamingface_engine.app import create_app
from screamingface_engine.config import Settings
from screamingface_engine.world import factory
from screamingface_engine.world.config import (
    AigatewaySection,
    ModelSpec,
    WorldConfig,
    WorldConfigError,
    parse_config,
)
from screamingface_engine.world.connector import AigatewayWorld
from screamingface_engine.world.factory import build_world, direct_mount_paths
from screamingface_engine.world.serving import derive_mount_table, engine_route_paths
from url4.peer.server import Url4Node

pytestmark = [pytest.mark.asyncio, pytest.mark.no_default_scope]


def _models(*ids: str) -> WorldConfig:
    return WorldConfig(
        aigateway=AigatewaySection(
            base_url="http://aigateway.test",
            default_model=ids[0],
            models=tuple(ModelSpec(id=model, web_search=False) for model in ids),
        )
    )


async def test_a_gateway_world_serves_route_answer_as_a_direct_mount_and_calls_nothing() -> None:
    gateway = Gateway()
    async with gateway.client() as client:
        io, aclose = await build_world(env={}, config=world_config(), client=client)
    assert isinstance(io, Url4Node)
    assert "/route-answer" in io.processor_routes()
    assert "/route-answer" in direct_mount_paths(io)
    assert io.default_route() == f"/{PUBLIC}"
    assert gateway.requests == []
    assert aclose is not None
    await aclose()


async def test_the_mount_table_lists_one_public_route_and_reads_nothing(tmp_path: Path) -> None:
    path = write_world(tmp_path)
    app = create_app(Settings(jwt_secret="routing-world-secret-0000000000"))

    table = await derive_mount_table(
        env={job_env.RUNNER_CONFIG: str(path)}, engine_routes=engine_route_paths(app)
    )

    (mount,) = [mount for mount in table.mounts if mount.path == "/route-answer"]
    assert (mount.kind, mount.media_type, mount.public_schema) == ("endpoint", None, True)
    assert PROFILE not in repr(table)


async def test_a_world_without_profiles_serves_the_route_and_knows_no_profile() -> None:
    gateway = Gateway()

    outcome = await run_direct(gateway, query(context()), config=world_config(GATEWAY_TOML))

    assert outcome.code() == "routing_profile_not_found"
    assert gateway.requests == []


@pytest.mark.parametrize(
    "text", ["", '[data]\n"/corpus" = { value = "rows" }\n'], ids=["empty", "read-side-only"]
)
async def test_a_world_without_a_gateway_has_no_route_answer(text: str) -> None:
    io, aclose = await build_world(env={}, config=parse_config(tomllib.loads(text), {}))

    assert "/route-answer" not in direct_mount_paths(io)
    if isinstance(io, Url4Node):
        assert "/route-answer" not in io.processor_routes()
    if aclose is not None:
        await aclose()


def _spy_on_worlds(monkeypatch: pytest.MonkeyPatch) -> list[AigatewayWorld]:
    built: list[AigatewayWorld] = []
    real = factory.build_aigateway_world

    async def spy(*args: Any, **kwargs: Any) -> AigatewayWorld:
        world = await real(*args, **kwargs)
        built.append(world)
        return world

    monkeypatch.setattr(factory, "build_aigateway_world", spy)
    return built


async def test_a_declared_model_at_route_answer_fails_composition_and_closes_the_world(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    built = _spy_on_worlds(monkeypatch)

    with pytest.raises(WorldConfigError, match="/route-answer") as caught:
        await build_world(env={}, config=_models("route-answer"))

    assert "declared model" in str(caught.value)
    (world,) = built
    assert world._client.is_closed


async def test_a_data_mount_at_route_answer_fails_composition_and_closes_the_world(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    built = _spy_on_worlds(monkeypatch)
    text = (
        f'[aigateway]\ndefault_route = "/{PUBLIC}"\nmodels = ["{PUBLIC}"]\n\n'
        '[data]\n"/route-answer" = { value = "shadow" }\n'
    )

    with pytest.raises(WorldConfigError, match="/route-answer"):
        await build_world(env={}, config=parse_config(tomllib.loads(text), {}))

    (world,) = built
    assert world._client.is_closed
