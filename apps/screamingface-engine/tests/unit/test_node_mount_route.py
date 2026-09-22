"""FX-31/FX-32 (04-review-fixes §2.3): a route that matches ONLY the known mounts.

# WHY this file exists. A catch-all ``Mount("/")`` is a FULL match for every path, so it changed
# the answer on existing engine routes: a wrong method on ``/token`` became url4's 404 instead of
# the engine's 405, and a trailing slash on ``/healthz`` was never redirected. ``NodeMountRoute``
# matches only the paths the node serves, so Starlette gives its normal answers for everything
# else. These tests pin the class, the one install function both shapes use, and the local shape
# end to end. The deployed shape is pinned in ``test_forwarder_deployed_shape.py``.

Offline throughout: the local world is a read-side declaration only (a ``[data]`` value route).
"""

from __future__ import annotations

from collections.abc import MutableMapping
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from starlette.routing import Match, NoMatchFound, Route

from screamingface_engine import job_env
from screamingface_engine.app import create_app
from screamingface_engine.config import Settings
from screamingface_engine.local import create_local_app
from screamingface_engine.world.serving import (
    NodeMountRoute,
    assert_node_route_last,
    install_node_route,
)

_READ_SIDE_ONLY = '[data]\n"/corpus" = { value = "rows", media_type = "text/plain" }\n'


async def _asgi(scope: Any, receive: Any, send: Any) -> None:  # pragma: no cover - never called
    raise AssertionError("the route must not dispatch in a matches() test")


def _http(path: str, method: str = "GET") -> MutableMapping[str, Any]:
    return {"type": "http", "path": path, "method": method}


# --- the class --------------------------------------------------------------------------------


def test_a_known_path_is_a_full_match_carrying_the_app_as_endpoint() -> None:
    route = NodeMountRoute(_asgi, paths=lambda: frozenset({"/corpus"}), name="node")

    match, child = route.matches(_http("/corpus"))

    assert match is Match.FULL
    assert child == {"endpoint": _asgi}


def test_any_method_on_a_known_path_is_a_full_match() -> None:
    """AC14: the node's own 405 answers a wrong method on a mount, so the route never filters."""
    route = NodeMountRoute(_asgi, paths=lambda: frozenset({"/corpus"}), name="node")

    assert route.matches(_http("/corpus", "POST"))[0] is Match.FULL


@pytest.mark.parametrize("path", ["/token", "/corpus/", "/corpus/x", "/", ""])
def test_an_unknown_path_is_no_match(path: str) -> None:
    route = NodeMountRoute(_asgi, paths=lambda: frozenset({"/corpus"}), name="node")

    assert route.matches(_http(path)) == (Match.NONE, {})


def test_a_websocket_scope_on_a_known_path_is_no_match() -> None:
    """The node owns no websocket surface; ``/ws`` and friends stay the engine's."""
    route = NodeMountRoute(_asgi, paths=lambda: frozenset({"/corpus"}), name="node")

    assert route.matches({"type": "websocket", "path": "/corpus"}) == (Match.NONE, {})


def test_the_path_set_is_read_at_match_time_not_at_construction() -> None:
    """The App fills its set in a startup hook, after the route is installed."""
    paths: set[str] = set()
    route = NodeMountRoute(_asgi, paths=lambda: frozenset(paths), name="node")

    assert route.matches(_http("/corpus"))[0] is Match.NONE
    paths.add("/corpus")
    assert route.matches(_http("/corpus"))[0] is Match.FULL


def test_url_path_for_never_resolves() -> None:
    route = NodeMountRoute(_asgi, paths=lambda: frozenset({"/corpus"}), name="node")

    with pytest.raises(NoMatchFound):
        route.url_path_for("node")


# --- the one install function and its ordering assertion --------------------------------------


def _bare_app() -> FastAPI:
    return create_app(Settings(jwt_secret="s" * 32))


def test_install_appends_the_route_last() -> None:
    app = _bare_app()
    route = NodeMountRoute(_asgi, paths=frozenset, name="node")

    install_node_route(app, route)

    assert app.router.routes[-1] is route


def test_install_refuses_a_second_node_route() -> None:
    """Two node routes would shadow each other depending on registration order (D3)."""
    app = _bare_app()
    install_node_route(app, NodeMountRoute(_asgi, paths=frozenset, name="node"))

    with pytest.raises(AssertionError):
        install_node_route(app, NodeMountRoute(_asgi, paths=frozenset, name="other"))


def test_the_ordering_assertion_rejects_a_route_registered_after_the_node_route() -> None:
    app = _bare_app()
    route = NodeMountRoute(_asgi, paths=frozenset, name="node")
    install_node_route(app, route)
    app.router.routes.append(Route("/late", lambda _request: None))

    with pytest.raises(AssertionError):
        assert_node_route_last(app, route)


# --- the local shape, end to end --------------------------------------------------------------


def _local(tmp_path: Path, text: str = _READ_SIDE_ONLY) -> FastAPI:
    config = tmp_path / "url4.toml"
    config.write_text(text)
    return create_local_app(Settings(jwt_secret="s" * 32), env={job_env.RUNNER_CONFIG: str(config)})


def _client(app: FastAPI) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://app.test")


async def _engine_answer(method: str, path: str) -> httpx.Response:
    """What the engine alone answers: an App with no node route at all."""
    async with _client(_bare_app()) as client:
        return await client.request(method, path)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("method", "path", "status"),
    [
        ("GET", "/token", 405),
        ("PUT", "/token", 405),
        ("POST", "/healthz", 405),
        ("POST", "/v1/models", 405),
        ("GET", "/healthz/", 307),
        ("GET", "/v1/nope", 404),
        ("GET", "/no-such-path", 404),
    ],
)
async def test_local_engine_paths_keep_the_engines_own_answer(
    tmp_path: Path, method: str, path: str, status: int
) -> None:
    """repro_405: the catch-all turned every one of these into url4's ``endpoint_not_found``."""
    app = _local(tmp_path)
    expected = await _engine_answer(method, path)

    async with app.router.lifespan_context(app):
        async with _client(app) as client:
            response = await client.request(method, path)

    assert response.status_code == status == expected.status_code
    assert response.headers.get("content-type") == expected.headers.get("content-type")
    assert response.content == expected.content


@pytest.mark.asyncio
async def test_local_mount_and_eval_path_still_reach_the_node(tmp_path: Path) -> None:
    app = _local(tmp_path)

    async with app.router.lifespan_context(app):
        async with _client(app) as client:
            mounted = await client.get("/corpus")
            evaluated = await client.get("/v1", params={"q": "'hello'"})

    assert (mounted.status_code, mounted.text) == (200, "rows")
    assert (evaluated.status_code, evaluated.text) == (200, "hello")


@pytest.mark.asyncio
async def test_a_wrong_method_on_a_local_mount_is_the_nodes_own_answer(tmp_path: Path) -> None:
    """AC14: the route matches the path, not the method, so the node decides — never the engine."""
    app = _local(tmp_path)

    async with app.router.lifespan_context(app):
        async with _client(app) as client:
            response = await client.post("/corpus")

    assert response.status_code == 405
    assert "error" in response.json()
    assert "detail" not in response.json()


@pytest.mark.asyncio
async def test_a_local_app_with_no_node_answers_every_path_as_the_engine(tmp_path: Path) -> None:
    """An empty world has no mounts and no eval path: nothing is the node's."""
    app = _local(tmp_path, text="")
    expected = await _engine_answer("GET", "/v1")

    async with app.router.lifespan_context(app):
        async with _client(app) as client:
            response = await client.get("/v1", params={"q": "'hello'"})

    assert response.status_code == 404
    assert response.content == expected.content


def test_the_local_app_installs_the_node_route_last(tmp_path: Path) -> None:
    app = _local(tmp_path)
    route = app.router.routes[-1]

    assert isinstance(route, NodeMountRoute)
    assert route.app is app.state.node_mount
    assert_node_route_last(app, route)
