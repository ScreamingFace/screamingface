"""u3-local — the node mounted inside the local App, behind every literal route (C8, AC17/T3).

# WHY this file exists, and why route precedence is first. ``serve --local`` fuses the control
# plane and the node tier into ONE FastAPI app, so the node's catch-all ASGI mount and the
# engine's literal routes share one route table. FastAPI resolves the FIRST match: a mount
# registered before ``/v1/models`` silently swallows it and the node answers the catalog's path
# with url4's ``endpoint_not_found``. T3 pins both halves of the resulting contract — the engine
# keeps ``/v1/models`` and the node keeps bare ``/v1?q=`` — and T3's refactor note is the
# composition root's own ordering assertion, which a future route insertion must trip.

These tests drive the REAL ``create_local_app`` through its lifespan; the world is a read-side
declaration only (a ``[data]`` value route), so the eval-path assertion makes no model call and
the suite stays offline.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI
from starlette.routing import Route

from screamingface_engine import job_env
from screamingface_engine.catalog.port import Credential, ModelCatalog, compute_etag
from screamingface_engine.config import Settings
from screamingface_engine.local import create_local_app
from screamingface_engine.runner.fair_share import FairShareIOLayer
from screamingface_engine.world.serving import NodeMountRoute, assert_node_route_last

_READ_SIDE_ONLY = '[data]\n"/corpus" = { value = "rows", media_type = "text/plain" }\n'


class _FakeCatalog:
    """The engine catalog stand-in: proves ``/v1/models`` reached the ENGINE route, not the node.

    A stub rather than the real service because the real one dials aigateway — and a test that
    dials anything, even loopback, is not offline.
    """

    def __init__(self) -> None:
        self.seen: list[Credential] = []

    async def fetch(self, credential: Credential) -> ModelCatalog:
        self.seen.append(credential)
        body: dict[str, object] = {
            "object": "list",
            "data": [{"id": "declared-model", "object": "model"}],
        }
        return ModelCatalog(body=body, etag=compute_etag(body))

    def max_age_s(self, credential: Credential) -> int:
        return 60


def _config_file(tmp_path: Path, text: str = _READ_SIDE_ONLY) -> str:
    path = tmp_path / "url4.toml"
    path.write_text(text)
    return str(path)


def _app(config_path: str, **kwargs: object) -> FastAPI:
    return create_local_app(
        Settings(jwt_secret="s" * 32, **kwargs),  # type: ignore[arg-type]
        env={job_env.RUNNER_CONFIG: config_path},
    )


def _client(app: FastAPI) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://app.test")


# --- T3 / AC17: literal routes win; the eval path reaches the node ----------------------------


@pytest.mark.asyncio
async def test_engine_catalog_answers_v1_models_while_bare_v1_reaches_the_node(
    tmp_path: Path,
) -> None:
    """The exact AC17 pair: ``/v1/models`` is the catalog's, ``/v1?q=`` is the node's.

    ``/v1`` is not an engine route and is not a declared mount: the node answers it because its
    catch-all mount was registered AFTER every literal route. Reverse the order and the node's
    own dispatch would answer ``/v1/models`` with url4's ``endpoint_not_found`` instead.
    """
    app = _app(_config_file(tmp_path))
    app.state.catalog = _FakeCatalog()

    async with app.router.lifespan_context(app):
        async with _client(app) as client:
            catalog = await client.get("/v1/models")
            evaluated = await client.get("/v1", params={"q": "'hello'"})

    assert catalog.status_code == 200
    assert catalog.json()["object"] == "list"
    assert catalog.headers["content-type"].startswith("application/json")

    assert evaluated.status_code == 200
    assert evaluated.headers["content-type"] == "text/plain; charset=utf-8"
    assert evaluated.text == "hello"


@pytest.mark.asyncio
async def test_a_declared_mount_answers_through_the_mounted_node(
    tmp_path: Path,
) -> None:
    """A ``[data]`` mount is served by the node's ASGI surface, in-process (no forwarder)."""
    app = _app(_config_file(tmp_path, _READ_SIDE_ONLY))

    async with app.router.lifespan_context(app):
        async with _client(app) as client:
            mounted = await client.get("/corpus")

    assert mounted.status_code == 200
    assert mounted.text == "rows"


@pytest.mark.asyncio
async def test_a_malformed_answer_seed_is_a_400_in_the_mount_envelope(
    tmp_path: Path,
) -> None:
    """The node tier maps ``AnswerSeedError`` to 400 before dispatch; the local mount does too.

    Local mode calls the sync scope producer itself, so the same malformed-seed refusal must not
    escape as a 500 (OME-1038: a declared sitting must not run without its seed).
    """
    app = _app(_config_file(tmp_path))

    async with app.router.lifespan_context(app):
        async with _client(app) as client:
            response = await client.get("/corpus", headers={"X-Answer-Seed": "not-an-int"})

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "malformed_source"


# --- T3 refactor note: the composition root asserts the ordering -------------------------------


def test_the_node_mount_is_the_final_route(tmp_path: Path) -> None:
    """INVARIANT (D3): the node route is last, so every literal route precedes it.

    FX-31/FX-32: the last route is the `NodeMountRoute` (not a catch-all `Mount`), installed by
    the one install function both shapes share.
    """
    app = _app(_config_file(tmp_path))
    route = app.router.routes[-1]

    # `BaseRoute` has no `.app`, so narrow first — the assertion IS the type proof that the last
    # route is the node route.
    assert isinstance(route, NodeMountRoute)
    assert route.app is app.state.node_mount
    # AND: the guard itself passes on the shape the composition root built.
    assert_node_route_last(app, route)


def test_the_ordering_guard_rejects_a_route_registered_after_the_mount(
    tmp_path: Path,
) -> None:
    """A future insertion after the node route must trip the guard (D3).

    Simulated by appending a literal route directly, which is exactly what an errant
    ``include_router`` after the install would do.
    """
    app = _app(_config_file(tmp_path))
    route = app.router.routes[-1]
    assert isinstance(route, NodeMountRoute)
    app.router.routes.append(Route("/late", lambda _request: None))

    with pytest.raises(AssertionError):
        assert_node_route_last(app, route)


# --- the shared IOLayer: one node for the mount AND every in-process run -----------------------


@pytest.mark.asyncio
async def test_the_in_process_run_path_shares_the_mounted_nodes_io_layer(
    tmp_path: Path,
) -> None:
    """C8: the mount and the runs resolve ONE node, so the surfaces cannot disagree.

    The mount proves the node exists; the executor factory (what a local run builds) must then
    hand that SAME instance to its executor rather than constructing a second world.
    """
    app = _app(_config_file(tmp_path))

    async with app.router.lifespan_context(app):
        shared = app.state.node_world
        assert shared is not None
        run_env: Mapping[str, str] = {
            **app.state.job_runner._base_env,  # noqa: SLF001 - the production run env shape
            job_env.TOPIC: "t-shared",
            job_env.EXPRESSION: "'hello'",
        }
        executor = app.state.job_runner._factory(run_env)  # noqa: SLF001
        inner = executor._inner  # noqa: SLF001 - the wrapped Url4Executor

        assert inner._io is shared  # noqa: SLF001 - identity IS the invariant

        # F2 + OME-908: the shared world is wrapped PER RUN for fair-share I/O, and the
        # wrapper's inner layer is still the one shared node.
        await inner._resolve_world()  # noqa: SLF001
        assert isinstance(inner._io, FairShareIOLayer)  # noqa: SLF001
        assert inner._io._inner is shared  # noqa: SLF001
