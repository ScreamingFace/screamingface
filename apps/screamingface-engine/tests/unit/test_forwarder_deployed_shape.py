"""FX-33..FX-38, FX-43 (04-review-fixes B2): the forwarder in the DEPLOYED shape.

# WHY this file exists. Before the fix round every forwarder test built the App through a
# `create_app(forwarder=...)` seam that production never used, so no test saw the production
# install path: the startup derivation, the route order and the ordering assertion. Here the App
# is built exactly as `create_app_from_env` builds it — `create_app` and then `_install_forwarder`
# — with a stub node behind an injected client. Starlette's TestClient drives the real lifespan,
# because the mount set is derived in a startup hook.

Offline throughout: the stub node is an ``httpx.MockTransport`` and deriving the mount set builds
the world without dialling anything (AC19).
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from screamingface_engine import job_env
from screamingface_engine.app import _install_forwarder, create_app
from screamingface_engine.config import Settings
from screamingface_engine.rest import forwarder as forwarder_module
from screamingface_engine.rest.forwarder import NodeForwarder

_MODEL = "anthropic/claude-haiku-4-5"
_USER = {"X-User-Email": "caller@example.com"}
_CONFIG = (
    "[aigateway]\n"
    'base_url = "http://aigateway.test"\n'
    f'default_route = "/{_MODEL}"\n'
    "\n[data]\n"
    '"/corpus/papers" = { value = "rows", media_type = "text/plain" }\n'
)
_S3: dict[str, Any] = {
    "artifact_store": "s3",
    "artifact_s3_endpoint_url": "http://garage.test:3900",
    "artifact_s3_bucket": "artifacts",
    "artifact_s3_access_key": "GKtest",
    "artifact_s3_secret_key": "secret",
}

Handler = Callable[[httpx.Request], httpx.Response]


class _StubNode:
    """A canned node that records every request it receives."""

    def __init__(self, *handlers: Handler) -> None:
        self.calls: list[httpx.Request] = []
        self._handlers = handlers or (lambda _r: httpx.Response(200, content=b"ok"),)

    def client(self) -> httpx.AsyncClient:
        def handle(request: httpx.Request) -> httpx.Response:
            self.calls.append(request)
            return self._handlers[min(len(self.calls), len(self._handlers)) - 1](request)

        return httpx.AsyncClient(transport=httpx.MockTransport(handle))


def _raise(exc_type: type[httpx.TransportError]) -> Handler:
    def handle(request: httpx.Request) -> httpx.Response:
        raise exc_type("stub", request=request)

    return handle


def _kwargs(**kwargs: Any) -> dict[str, Any]:
    """Untyped call arguments, for the tests that assert a removed parameter is refused."""
    return kwargs


def _settings() -> Settings:
    return Settings(jwt_secret="s" * 32, node_base_url="http://node.test", **_S3)


def _deployed(tmp_path: Path, stub: _StubNode) -> tuple[FastAPI, Path]:
    config = tmp_path / "url4.toml"
    config.write_text(_CONFIG)
    settings = _settings()
    app = create_app(settings)
    _install_forwarder(
        app, settings, env={job_env.RUNNER_CONFIG: str(config)}, client=stub.client()
    )
    return app, config


def _engine_answer(method: str, path: str) -> httpx.Response:
    """What the engine alone answers: the same App settings, no node route."""
    return TestClient(create_app(_settings())).request(method, path, follow_redirects=False)


# --- FX-43: the deployed route table ----------------------------------------------------------


def test_engine_routes_reach_the_engine_and_mounts_reach_the_forwarder(tmp_path: Path) -> None:
    stub = _StubNode()
    app, config = _deployed(tmp_path, stub)

    with TestClient(app) as client:
        health = client.get("/healthz")
        token = client.get("/token")
        artifact = client.get(f"/artifacts/{'c' * 64}")
        eval_path = client.get("/v1", params={"q": "'hello'"})
        with pytest.raises(WebSocketDisconnect), client.websocket_connect("/ws") as socket:
            socket.receive_text()
        assert stub.calls == [], "no engine path may reach the node"

        mounted = client.get("/corpus/papers", headers=_USER)
        model = client.get(f"/{_MODEL}", params={"q": "('')!'go'"}, headers=_USER)

    assert health.json() == {
        "status": "ok",
        "config_digest": hashlib.sha256(config.read_bytes()).hexdigest(),
    }
    expected_405 = _engine_answer("GET", "/token")
    assert (token.status_code, token.content) == (405, expected_405.content)
    assert artifact.status_code == 401
    assert artifact.headers["content-type"] == "application/problem+json"
    expected_404 = _engine_answer("GET", "/v1")
    assert (eval_path.status_code, eval_path.content) == (404, expected_404.content)
    assert (mounted.status_code, model.status_code) == (200, 200)
    assert [call.url.path for call in stub.calls] == ["/corpus/papers", f"/{_MODEL}"]


def test_a_trailing_slash_and_a_wrong_method_keep_starlettes_answers(tmp_path: Path) -> None:
    stub = _StubNode()
    app, _config = _deployed(tmp_path, stub)

    with TestClient(app) as client:
        slash = client.get("/healthz/", follow_redirects=False)
        wrong = client.post("/healthz")

    assert slash.status_code == 307
    assert wrong.status_code == 405
    assert stub.calls == []


def test_a_wrong_method_on_a_mount_is_forwarded_for_the_node_to_answer(tmp_path: Path) -> None:
    """AC14: the route matches the path, not the method; the node's own 405 is relayed."""
    stub = _StubNode(lambda _r: httpx.Response(405, content=b'{"error":{}}'))
    app, _config = _deployed(tmp_path, stub)

    with TestClient(app) as client:
        response = client.post("/corpus/papers", headers=_USER)

    assert response.status_code == 405
    assert [call.method for call in stub.calls] == ["POST"]


# --- FX-33: the connect budget and which timeouts retry ---------------------------------------


def test_the_forward_client_bounds_connect_at_two_seconds() -> None:
    forwarder = NodeForwarder(node_base_url="http://node.test", timeout_s=35.0)

    timeout = forwarder._client.timeout  # noqa: SLF001 - the built client IS the contract

    assert timeout.connect == 2.0
    assert (timeout.read, timeout.write, timeout.pool) == (35.0, 35.0, 35.0)


@pytest.mark.parametrize("exc_type", [httpx.ConnectTimeout, httpx.PoolTimeout])
def test_a_connect_or_pool_timeout_is_retried_once_then_answers_503(
    tmp_path: Path, exc_type: type[httpx.TransportError]
) -> None:
    """The request never reached the node, so it is safe to retry, like a refused connection."""
    stub = _StubNode(_raise(exc_type))
    app, _config = _deployed(tmp_path, stub)

    with TestClient(app) as client:
        response = client.get("/corpus/papers", headers=_USER)

    assert len(stub.calls) == 2
    assert response.status_code == 503
    assert response.headers["retry-after"] == "1"
    assert response.json()["error"]["code"] == "upstream_unavailable"


def test_a_connect_timeout_then_success_is_the_nodes_answer(tmp_path: Path) -> None:
    stub = _StubNode(_raise(httpx.ConnectTimeout), lambda _r: httpx.Response(200, content=b"rows"))
    app, _config = _deployed(tmp_path, stub)

    with TestClient(app) as client:
        response = client.get("/corpus/papers", headers=_USER)

    assert (response.status_code, response.text, len(stub.calls)) == (200, "rows", 2)


@pytest.mark.parametrize("exc_type", [httpx.ReadTimeout, httpx.WriteTimeout])
def test_a_read_or_write_timeout_is_504_and_never_retried(
    tmp_path: Path, exc_type: type[httpx.TransportError]
) -> None:
    stub = _StubNode(_raise(exc_type))
    app, _config = _deployed(tmp_path, stub)

    with TestClient(app) as client:
        response = client.get("/corpus/papers", headers=_USER)

    assert len(stub.calls) == 1
    assert response.status_code == 504
    assert response.json()["error"]["code"] == "timeout"


# --- FX-34: one source for the forward budget -------------------------------------------------


def test_the_forward_budget_has_no_module_default() -> None:
    assert not hasattr(forwarder_module, "FORWARD_TIMEOUT_S")
    with pytest.raises(TypeError):
        NodeForwarder(**_kwargs(node_base_url="http://node.test"))


def test_install_forwarder_takes_the_budget_from_settings(tmp_path: Path) -> None:
    settings = Settings(
        jwt_secret="s" * 32,
        node_base_url="http://node.test",
        node_forward_timeout_s=12.5,
        **_S3,
    )
    app = create_app(settings)
    _install_forwarder(app, settings, env={job_env.RUNNER_CONFIG: str(tmp_path / "x.toml")})

    assert app.state.forwarder._client.timeout.read == 12.5  # noqa: SLF001


# --- FX-35, FX-37: what is relayed ------------------------------------------------------------


def test_a_303_is_relayed_with_its_location_unchanged(tmp_path: Path) -> None:
    location = "/artifacts/abc123?exp=1000&sig=deadbeef"
    stub = _StubNode(lambda _r: httpx.Response(303, headers={"Location": location}))
    app, _config = _deployed(tmp_path, stub)

    with TestClient(app) as client:
        response = client.get("/corpus/papers", headers=_USER, follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"] == location


def test_the_prefix_rewrite_is_gone() -> None:
    assert not hasattr(forwarder_module, "_rewrite_location")
    with pytest.raises(TypeError):
        NodeForwarder(
            **_kwargs(node_base_url="http://node.test", timeout_s=1.0, node_artifact_prefix="/x/")
        )


def test_the_nodes_server_and_date_headers_are_not_relayed(tmp_path: Path) -> None:
    """The App's own server writes these; relaying the node's would send two of each."""
    stub = _StubNode(
        lambda _r: httpx.Response(
            200,
            content=b"rows",
            headers={"Server": "node-uvicorn", "Date": "Mon, 01 Jan 2001 00:00:00 GMT"},
        )
    )
    app, _config = _deployed(tmp_path, stub)

    # WHY through TestClient: it has no uvicorn to add its own `server`/`date`, so any value seen
    # here was relayed from the node.
    with TestClient(app) as client:
        response = client.get("/corpus/papers", headers=_USER)

    assert response.text == "rows"
    assert "server" not in response.headers
    assert "date" not in response.headers
    assert response.headers["content-length"] == "4"


# --- FX-38: the node tier needs a shared store ------------------------------------------------


def test_a_filesystem_store_is_refused_when_a_node_tier_is_configured(tmp_path: Path) -> None:
    """OME-929: the node pod's disk is not the App's, so a spilled sync result would 404."""
    settings = Settings(
        jwt_secret="s" * 32, node_base_url="http://node.test", artifacts_dir=str(tmp_path)
    )

    with pytest.raises(ValueError, match="OME-929"):
        create_app(settings)


def test_a_filesystem_store_is_still_fine_without_a_node_tier(tmp_path: Path) -> None:
    app = create_app(Settings(jwt_secret="s" * 32, artifacts_dir=str(tmp_path)))

    assert app.state.artifact_store is not None
