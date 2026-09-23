"""F4 (prd/02): the engine-route/mount collision guard makes route precedence loud.

# WHY this file exists. Under D3 the node keeps ``eval_path="/v1"`` and collisions between an
# engine literal route and a url4 mount are resolved by FastAPI route precedence. Precedence is
# SILENT: a literal route registered before the node's ASGI mount shadows a mount, and the only
# symptom is a mount that stops answering. url4's own ``_check_routable`` rejects duplicates
# *within* the node; it cannot see the engine's FastAPI routes. This guard covers that
# engine-versus-node case and fails STARTUP, naming both the mount and the shadowing route
# (AC5). It runs in the one shared composition helper so the two deployment shapes (unit 3)
# cannot diverge.

# The counter-case is as load-bearing as the failure. ``eval_path="/v1"`` coexists with the
# engine's ``/v1/models``, ``/v1/benchmarks`` and ``/v1/connections`` because those are strictly
# longer literal paths: they win their exact paths while the eval path keeps everything else
# (AC6). A hypothetical engine route at exactly ``/v1`` would eat the eval path and MUST fail.
"""

from __future__ import annotations

import logging

import httpx
import pytest

from screamingface_engine.app import create_app
from screamingface_engine.world.config import WorldConfig, parse_config
from screamingface_engine.world.factory import deny_by_default_world
from screamingface_engine.world.models.registry import (
    EMPTY_MODEL_WORLD,
    ModelRegistry,
    ProviderSeed,
)
from screamingface_engine.world.serving import (
    MountCollisionError,
    NodeMountRoute,
    check_mount_collisions,
    compose_serving_world,
    engine_route_paths,
    install_node_route,
    node_eval_path,
)
from url4.peer.server import Url4Node

# A minimal declared aigateway world — the node that serves model routes is the thing the guard
# inspects, so it must exist for the encoded-id test.
_AIGATEWAY = """
[aigateway]
default_route = "/m"
models = ["m"]
"""


def _config(toml_text: str, registry: ModelRegistry = EMPTY_MODEL_WORLD) -> WorldConfig:
    import tomllib

    return parse_config(tomllib.loads(toml_text), {}, registry=registry)


def _engine_routes() -> frozenset[str]:
    """The REAL engine route set, derived from the app ``create_app`` builds — never hardcoded."""

    return engine_route_paths(create_app())


def test_engine_route_paths_sees_every_route_the_app_publishes() -> None:
    """Pin the derivation, not a list: the walker must track what ``create_app`` actually wires.

    A schema-published path missing from the derived set is a shadow the guard would miss; the
    hidden routes (WebSocket, health, token) are the ones the app's own OpenAPI view omits, so
    the walker has to find them too.
    """

    app = create_app()
    derived = engine_route_paths(app)

    assert set(app.openapi()["paths"]) <= derived
    assert {"/token", "/healthz", "/ws"} <= derived
    assert "/artifacts/{artifact_id}" in derived


# --- T3 (AC5): a shadowed mount fails startup, naming both ----------------------------------------


@pytest.mark.asyncio
async def test_a_mount_shadowed_by_an_engine_route_fails_startup_naming_both() -> None:
    # ``/token`` is a real engine route (the capability-token mint). A ``[data]`` mount at the
    # same path can never answer: the literal route is registered first and wins.
    config = _config('[data]\n"/token" = { value = "shadowed", media_type = "text/plain" }\n')

    with pytest.raises(MountCollisionError) as excinfo:
        await compose_serving_world(env={}, engine_routes=_engine_routes(), config=config)

    message = str(excinfo.value)
    assert "/token" in message, message
    # The message must name BOTH sides so the operator knows which route is the shadow.
    assert "token" in message.lower(), message


@pytest.mark.asyncio
async def test_a_parameterised_engine_route_shadows_a_concrete_mount() -> None:
    """``/artifacts/{artifact_id}`` eats ``/artifacts/foo`` — a literal-only check would miss it."""

    config = _config('[data]\n"/artifacts/foo" = { value = "shadowed" }\n')
    with pytest.raises(MountCollisionError) as excinfo:
        await compose_serving_world(env={}, engine_routes=_engine_routes(), config=config)
    assert "/artifacts/foo" in str(excinfo.value)


# --- T4 (AC6): longer-literal-wins, pinned in both directions -------------------------------------


@pytest.mark.asyncio
async def test_the_real_engine_routes_pass_against_eval_path_v1() -> None:
    routes = _engine_routes()
    # The routes the eval path coexists with, and why the guard must not flag them.
    assert "/v1/models" in routes
    assert "/v1/benchmarks" in routes
    assert "/v1/connections" in routes

    config = _config(_AIGATEWAY)
    async with httpx.AsyncClient() as client:
        io, aclose = await compose_serving_world(
            env={}, engine_routes=routes, config=config, client=client
        )
    try:
        assert isinstance(io, Url4Node)
        assert node_eval_path(io) == "/v1"  # url4's default, kept under D3
        check_mount_collisions(io, routes)  # still passes when re-run
    finally:
        if aclose is not None:
            await aclose()


@pytest.mark.asyncio
async def test_a_literal_engine_route_at_exactly_the_eval_path_fails() -> None:
    """``/v1`` as an engine route would eat the eval path entirely — AC6's other direction."""

    config = _config(_AIGATEWAY)
    async with httpx.AsyncClient() as client:
        io, aclose = await compose_serving_world(
            env={}, engine_routes=_engine_routes(), config=config, client=client
        )
    try:
        assert isinstance(io, Url4Node)
        with pytest.raises(MountCollisionError) as excinfo:
            check_mount_collisions(io, _engine_routes() | {"/v1"})
        assert "/v1" in str(excinfo.value)
    finally:
        if aclose is not None:
            await aclose()


# --- T6 (AC8): colon-bearing ids are compared in their encoded form -------------------------------


@pytest.mark.asyncio
async def test_a_colon_bearing_id_is_compared_in_its_encoded_form() -> None:
    registry = ModelRegistry((ProviderSeed("huggingface", ("org/model:novita",)),))
    config = _config(
        '[aigateway]\ndefault_route = "/huggingface/org/model~novita"\n',
        registry,
    )
    async with httpx.AsyncClient() as client:
        io, aclose = await compose_serving_world(
            env={}, engine_routes=_engine_routes(), config=config, client=client
        )
    try:
        assert isinstance(io, Url4Node)
        mount = "/huggingface/org/model~novita"
        assert mount in io.processor_routes()
        assert "/huggingface/org/model:novita" not in io.processor_routes()

        # The encoded form is what the guard sees: a raw-colon engine route names no mount.
        check_mount_collisions(io, {"/huggingface/org/model:novita"})
        # The encoded mount path DOES collide, because the comparison is on encoded forms.
        with pytest.raises(MountCollisionError):
            check_mount_collisions(io, {mount})
    finally:
        if aclose is not None:
            await aclose()


def test_deny_by_default_world_composes_without_a_node_to_guard() -> None:
    """A world with no mounts has nothing to collide; the guard must not invent a node."""

    io = deny_by_default_world()
    check_mount_collisions(io, _engine_routes())


# --- FX-50: a Starlette `Mount` route shadows its whole subtree, not just its bare path -----------


@pytest.mark.asyncio
async def test_a_static_mount_shadows_every_path_under_it() -> None:
    """``/diagrams`` is a real Starlette ``Mount`` (StaticFiles): it is a FULL match for its own
    path AND everything under ``path + "/"`` — a literal-route comparison would miss the
    subtree entirely, because FastAPI's route table for a ``Mount`` never lists ``/diagrams/foo``
    as its own route (FX-50, U2-1)."""

    config = _config('[data]\n"/diagrams/foo" = { value = "shadowed" }\n')
    with pytest.raises(MountCollisionError) as excinfo:
        await compose_serving_world(env={}, engine_routes=_engine_routes(), config=config)
    assert "/diagrams" in str(excinfo.value)


def test_engine_route_paths_ignores_the_node_mount_route() -> None:
    """``NodeMountRoute`` (B2, unit 3) is the node's own surface, not an engine route — it has
    neither ``.path`` nor ``.original_router``, so the walker must not surface its paths."""

    app = create_app()

    async def _app(scope, receive, send) -> None:  # pragma: no cover - never invoked
        raise AssertionError("not called")

    install_node_route(
        app, NodeMountRoute(_app, paths=lambda: frozenset({"/some/node/path"}), name="node")
    )

    derived = engine_route_paths(app)
    assert "/some/node/path" not in derived


# --- FX-54 (AC5): the collision message names both sides, even for a method-only overlap ----------


@pytest.mark.asyncio
async def test_a_get_only_engine_route_collision_names_both_the_mount_and_the_route() -> None:
    """``/healthz`` is a GET-only engine route. A ``[data]`` mount at the same path is answered
    by the engine route for GET, so the message must not claim the mount "never" answers."""

    config = _config('[data]\n"/healthz" = { value = "shadowed", media_type = "text/plain" }\n')
    with pytest.raises(MountCollisionError) as excinfo:
        await compose_serving_world(env={}, engine_routes=_engine_routes(), config=config)

    message = str(excinfo.value)
    assert "/healthz" in message
    assert "never" not in message.lower(), message


@pytest.mark.asyncio
async def test_the_parameterised_route_name_appears_in_the_collision_message() -> None:
    """AC5: the message names the SHADOWING route, not just the mount it shadows."""

    config = _config('[data]\n"/artifacts/foo" = { value = "shadowed" }\n')
    with pytest.raises(MountCollisionError) as excinfo:
        await compose_serving_world(env={}, engine_routes=_engine_routes(), config=config)

    message = str(excinfo.value)
    assert "/artifacts/foo" in message
    assert "/artifacts/{artifact_id}" in message, message


# --- FX-52: mounts are guarded against each other too --------------------------------------------


@pytest.mark.asyncio
async def test_a_data_route_equal_to_a_declared_model_route_is_rejected() -> None:
    """A ``[data]`` mount at the same path as a declared model route collides on the SAME node —
    url4's own ``Url4Node._check_routable`` already refuses the duplicate registration; this pins
    that it surfaces as the engine's own ``WorldConfigError``, not a raw ``ValueError`` (FX-52)."""
    from screamingface_engine.world.config import WorldConfigError

    config = _config(_AIGATEWAY + '\n[data]\n"/m" = { value = "shadowed" }\n')
    with pytest.raises(WorldConfigError) as excinfo:
        async with httpx.AsyncClient() as client:
            await compose_serving_world(
                env={}, engine_routes=_engine_routes(), config=config, client=client
            )
    assert "/m" in str(excinfo.value)


def test_a_data_route_under_the_eval_path_is_rejected() -> None:
    """``{eval_path}/…`` is url4's reserved self-holdings qualifier namespace (spec §5.6.3.1,
    mirrored from ``url4.cli._config.ServeConfig.validate``) — a data mount there would shadow
    every ``@`` qualifier below it (FX-52)."""
    from screamingface_engine.world.config import WorldConfigError

    with pytest.raises(WorldConfigError) as excinfo:
        _config(_AIGATEWAY + '\n[data]\n"/v1/science" = { value = "shadowed" }\n')
    message = str(excinfo.value)
    assert "/v1/science" in message
    assert "/v1" in message


# --- FX-57: a holdings collection colliding with an engine literal route WARNS, not fails --------


@pytest.mark.asyncio
async def test_a_holdings_collection_matching_an_engine_route_segment_warns(caplog) -> None:
    """``models`` collides with the real engine route ``/v1/models`` — ``/v1/models?q=(@)`` is
    then answered by the engine, not the ``models`` shelf. That is a narrow shadow (one query
    form under one literal path), so the guard warns rather than fails startup (FX-57)."""

    config = _config(_AIGATEWAY + '\n[holdings]\nmodels = { value = "shadowed shelf" }\n')
    with caplog.at_level(logging.WARNING, logger="screamingface_engine.world.serving"):
        async with httpx.AsyncClient() as client:
            io, aclose = await compose_serving_world(
                env={}, engine_routes=_engine_routes(), config=config, client=client
            )
    try:
        assert isinstance(io, Url4Node)
    finally:
        if aclose is not None:
            await aclose()

    assert "models" in caplog.text
    assert "/v1/models" in caplog.text
