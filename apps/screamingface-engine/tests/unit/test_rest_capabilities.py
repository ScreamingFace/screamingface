"""``GET /v1/capabilities``: the dormant Engine capability discovery (C12, Unit 6).

FEATURE: Router Recipe extension, capability gate (C12). The SDK reads this document fresh before
a submission that needs a capability, and refuses that submission before any run exists when an
ID it needs is absent.
STORY: as the SDK, I learn which capability IDs this Engine fleet can run, without a run token,
and never from a cached or conditional answer.
INVARIANT defended: the closed ``engine-capabilities-v1`` document with ``private, no-store`` and
no validator. This release advertises nothing: any configuration but ``[]`` refuses startup,
``router-v1`` included, because configuration is not fleet evidence. The route joins the App's
one composition, so the existing mount-collision guard sees it.
"""

from __future__ import annotations

import socket
import tomllib
from collections.abc import Mapping

import httpx
import pytest
from _fakes import RecordingJobRunner
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

from screamingface_engine.app import create_app
from screamingface_engine.auth.jwt import JwtCodec
from screamingface_engine.config import Settings
from screamingface_engine.local import create_local_app
from screamingface_engine.rest.mounts import install_mounts
from screamingface_engine.testing import InMemoryEventStream
from screamingface_engine.world.config import WorldFile, parse_config
from screamingface_engine.world.models.registry import ModelRegistry, ProviderSeed
from screamingface_engine.world.serving import (
    MountCollisionError,
    derive_mount_table,
    engine_route_paths,
)

_PATH = "/v1/capabilities"
_VAR = "URL4_CLOUD_ADVERTISED_CAPABILITIES"
# The C12 document, byte for byte: closed, compact, and empty in this release.
_BODY = b'{"object":"engine_capabilities","contract":"engine-capabilities-v1","capabilities":[]}'


@pytest.fixture
def isolated_env(monkeypatch: pytest.MonkeyPatch) -> pytest.MonkeyPatch:
    """The process env without the capability setting, restored after the test."""
    monkeypatch.delenv(_VAR, raising=False)
    return monkeypatch


async def _get(
    app: FastAPI, path: str = _PATH, *, headers: Mapping[str, str] | None = None
) -> httpx.Response:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://engine.test"
    ) as client:
        return await client.get(path, headers=headers)


def _assert_dormant_document(response: httpx.Response) -> None:
    assert response.status_code == 200
    assert response.content == _BODY
    assert response.headers["content-type"] == "application/json"
    assert response.headers["cache-control"] == "private, no-store"
    # INVARIANT: no validator, so no reader can turn this answer into a stale 304.
    assert "etag" not in response.headers
    assert "last-modified" not in response.headers


# --- the document -------------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "configured",
    [
        pytest.param(None, id="default"),
        pytest.param("[]", id="explicit-empty"),
        pytest.param(" [ ] ", id="explicit-empty-spaced"),
    ],
)
async def test_the_dormant_document_is_exact_and_uncached(
    isolated_env: pytest.MonkeyPatch, configured: str | None
) -> None:
    if configured is not None:
        isolated_env.setenv(_VAR, configured)
    # WHY no `Settings` argument: the App reads its own, from this env, as a deployed App does.
    app = create_app(stream=InMemoryEventStream())
    _assert_dormant_document(await _get(app))


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "headers",
    [
        pytest.param({"If-None-Match": "*"}, id="if-none-match-any"),
        pytest.param({"If-None-Match": '"0"'}, id="if-none-match-tag"),
        pytest.param({"If-Modified-Since": "Fri, 01 Jan 2100 00:00:00 GMT"}, id="if-modified"),
        pytest.param({"X-User-Email": "reader@example.com"}, id="edge-identity"),
    ],
)
async def test_a_validator_or_an_identity_never_changes_the_answer(
    isolated_env: pytest.MonkeyPatch, headers: Mapping[str, str]
) -> None:
    app = create_app(Settings(), stream=InMemoryEventStream())
    _assert_dormant_document(await _get(app, headers=headers))


@pytest.mark.asyncio
async def test_the_route_emits_configured_ids_in_lexical_order() -> None:
    # WHY `model_construct`: this release refuses every ID at startup, yet the order is the C12
    # wire rule a later release's readers rely on; it is pinned here past the startup guard.
    settings = Settings.model_construct(advertised_capabilities=["b-v1", "a-v1"])
    app = create_app(settings, stream=InMemoryEventStream())
    response = await _get(app)
    assert response.json() == {
        "object": "engine_capabilities",
        "contract": "engine-capabilities-v1",
        "capabilities": ["a-v1", "b-v1"],
    }


# --- no side effects, one route, the same composition -------------------------------------------


@pytest.mark.asyncio
async def test_discovery_mints_schedules_and_dials_nothing(
    isolated_env: pytest.MonkeyPatch,
) -> None:
    signed: list[str] = []
    dialed: list[object] = []

    def _sign(self: JwtCodec, topic: str, now: object) -> str:
        signed.append(topic)
        return "token"

    def _dial(*args: object, **kwargs: object) -> None:
        dialed.append(args)
        raise OSError("discovery dialed out")

    isolated_env.setattr(JwtCodec, "sign", _sign)
    isolated_env.setattr(socket, "create_connection", _dial)
    isolated_env.setattr(socket.socket, "connect", _dial)
    runner = RecordingJobRunner()
    app = create_app(Settings(), stream=InMemoryEventStream(), job_runner=runner)

    _assert_dormant_document(await _get(app))
    assert signed == []
    assert dialed == []
    assert runner.scheduled == []
    assert runner.stopped == []


def test_one_get_route_serves_the_path_and_the_collision_guard_sees_it(
    isolated_env: pytest.MonkeyPatch,
) -> None:
    app = create_app(Settings(), stream=InMemoryEventStream())
    # WHY the schema, not `app.routes`: an included router stays wrapped there (FastAPI 0.141+).
    assert list(app.openapi()["paths"][_PATH]) == ["get"]
    assert _PATH in engine_route_paths(app)


@pytest.mark.asyncio
async def test_the_operators_route_keeps_its_own_conditional_read(
    isolated_env: pytest.MonkeyPatch,
) -> None:
    # WHY beside discovery: the two share ingress exposure, not caching; operators keeps its ETag.
    app = create_app(Settings(), stream=InMemoryEventStream())
    first = await _get(app, "/v1/operators")
    assert first.status_code == 200
    again = await _get(app, "/v1/operators", headers={"If-None-Match": first.headers["etag"]})
    assert again.status_code == 304


@pytest.mark.asyncio
async def test_the_local_app_serves_the_same_document(isolated_env: pytest.MonkeyPatch) -> None:
    app = create_local_app(settings=Settings(), env={})
    _assert_dormant_document(await _get(app))


# --- configuration ------------------------------------------------------------------------------

_REFUSED = [
    pytest.param("", id="empty-text"),
    pytest.param("[", id="malformed"),
    pytest.param('["router-v1",]', id="trailing-comma"),
    pytest.param("router-v1", id="bare-id"),
    pytest.param("null", id="null"),
    pytest.param("{}", id="object"),
    pytest.param('"router-v1"', id="string"),
    pytest.param("1", id="number"),
    pytest.param("true", id="boolean"),
    pytest.param("[1]", id="number-element"),
    pytest.param("[null]", id="null-element"),
    pytest.param("[true]", id="boolean-element"),
    pytest.param("[{}]", id="object-element"),
    pytest.param('[["router-v1"]]', id="nested-array"),
    pytest.param('[""]', id="empty-id"),
    pytest.param('[" "]', id="blank-id"),
    pytest.param('["a-v1", "a-v1"]', id="duplicate"),
    pytest.param('["unknown-v1"]', id="unknown-id"),
    pytest.param('["router-v1"]', id="router-v1"),
    pytest.param('["router-v1", "router-v1"]', id="duplicate-router-v1"),
    pytest.param('["classify-frozen-copy-v1"]', id="classify-frozen-copy-v1"),
    pytest.param('["router-input-ref-v1"]', id="router-input-ref-v1"),
    pytest.param('["router-placement-v1"]', id="router-placement-v1"),
    pytest.param('["e4c-branch-v1"]', id="e4c-branch-v1"),
    pytest.param('["router-placement-v1", "router-v1"]', id="router-set"),
]


@pytest.mark.parametrize("configured", _REFUSED)
def test_any_configuration_but_the_empty_set_refuses_startup(
    isolated_env: pytest.MonkeyPatch, configured: str
) -> None:
    isolated_env.setenv(_VAR, configured)
    with pytest.raises(ValidationError) as refused:
        create_app(stream=InMemoryEventStream())
    assert "advertised_capabilities" in str(refused.value)


def test_the_code_seam_refuses_router_v1_as_the_env_does() -> None:
    with pytest.raises(ValidationError) as refused:
        Settings(advertised_capabilities=["router-v1"])
    # WHY the reason, not only the field: an unknown field is refused too, for another reason.
    assert "advertises no capability" in str(refused.value)


# --- the existing mount-collision guard ---------------------------------------------------------


def _world_with_model_route(route: str, registry: ModelRegistry) -> WorldFile:
    """A synthetic declared world whose aigateway node mounts ``route``.

    WHY a model route, not a ``[data]`` key: the world refuses a data key under the ``/v1`` eval
    path on its own, so only a model id the registry names can put a mount at the discovery path.
    """
    config = parse_config(
        tomllib.loads(f'[aigateway]\ndefault_route = "{route}"\n'), {}, registry=registry
    )
    return WorldFile(config=config, digest="synthetic")


def _app_serving(world: WorldFile) -> FastAPI:
    """The App's real startup seam: the mount table derived against its own registered routes."""
    app = create_app(Settings(), stream=InMemoryEventStream())
    install_mounts(
        app,
        lambda: derive_mount_table(env={}, engine_routes=engine_route_paths(app), world=world),
    )
    return app


def test_a_world_mount_at_the_discovery_path_refuses_startup(
    isolated_env: pytest.MonkeyPatch,
) -> None:
    registry = ModelRegistry((ProviderSeed("v1", ("capabilities",)),))
    app = _app_serving(_world_with_model_route(_PATH, registry))
    with pytest.raises(MountCollisionError) as refused, TestClient(app):
        pass
    assert f"engine route {_PATH!r} shadows the node mount {_PATH!r}" in str(refused.value)


def test_a_world_mount_elsewhere_starts_and_discovery_still_answers(
    isolated_env: pytest.MonkeyPatch,
) -> None:
    registry = ModelRegistry((ProviderSeed("p", ("m",)),))
    app = _app_serving(_world_with_model_route("/p/m", registry))
    with TestClient(app) as client:
        response = client.get(_PATH)
    assert "/p/m" in engine_route_paths(app)
    assert response.status_code == 200
    assert response.content == _BODY
    assert response.headers["cache-control"] == "private, no-store"
