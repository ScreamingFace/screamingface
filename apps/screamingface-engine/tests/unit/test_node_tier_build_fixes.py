"""Fix round B1 (04-review-fixes.md) — what the node tier refuses at boot, and its spill timing.

FEATURE (unit 3, prd/03): the sync surface's deployed shape. These tests pin the boot-time
refusals (FX-8 filesystem store, FX-9 empty key, FX-13 settings, FX-16 store errors), the
hard-cap default (FX-11), the spill that runs after url4 returns under its own bound (FX-2),
drain at SIGTERM (FX-4) and the separate metrics port (FX-5).

Stubbed aigateway throughout: no real external API is called, so the suite runs offline.
"""

from __future__ import annotations

import asyncio
import hashlib
import importlib
import signal
import threading
from typing import Any

import httpx
import pytest
import uvicorn
from test_aigateway_connector import _MockAigateway
from test_node_tier import _KEY, _NEVER_SPILLS, _config, _node_client

from screamingface_engine import job_env
from screamingface_engine.world.node_tier import (
    NODE_DEFAULT_RESULT_HARD_CAP_BYTES,
    NodeReadiness,
    NodeTier,
    NodeTierError,
    NodeTierSettings,
    build_node_metrics,
    build_node_tier,
)
from url4.peer.server import Url4Node
from url4.streaming.protocol.signals import ResultArtifact

_MODEL = "anthropic/claude-haiku-4-5"
_S3_ENV = {
    job_env.ARTIFACT_STORE: "s3",
    job_env.ARTIFACT_S3_ENDPOINT_URL: "http://s3.test",
    job_env.ARTIFACT_S3_BUCKET: "bucket",
    job_env.ARTIFACT_S3_ACCESS_KEY: "access",
    job_env.ARTIFACT_S3_SECRET_KEY: "secret",
}


class _SlowStore:
    """A spill store whose write blocks its worker thread for ``seconds`` (or until released)."""

    def __init__(self, seconds: float) -> None:
        self._seconds = seconds
        self.release = threading.Event()
        self.writes = 0

    def write_bytes(self, encoded: bytes) -> ResultArtifact:
        self.release.wait(self._seconds)
        self.writes += 1
        digest = hashlib.sha256(encoded).hexdigest()
        return ResultArtifact(id=digest, size_bytes=len(encoded), sha256=digest)

    def write_text(self, body: str) -> ResultArtifact:  # pragma: no cover - port completeness
        return self.write_bytes(body.encode())


# --- FX-11 / FX-13: settings ------------------------------------------------------------------


def test_the_node_hard_cap_default_is_64_mib_and_the_env_name_is_the_run_paths() -> None:
    assert NODE_DEFAULT_RESULT_HARD_CAP_BYTES == 64 * 1024 * 1024
    assert NodeTierSettings().result_hard_cap_bytes == NODE_DEFAULT_RESULT_HARD_CAP_BYTES
    assert NodeTierSettings.from_env({}).result_hard_cap_bytes == NODE_DEFAULT_RESULT_HARD_CAP_BYTES
    overridden = NodeTierSettings.from_env({job_env.RESULT_HARD_CAP_BYTES: "1234"})
    assert overridden.result_hard_cap_bytes == 1234


def test_the_new_settings_have_their_defaults_and_env_names() -> None:
    defaults = NodeTierSettings.from_env({})
    assert defaults.spill_timeout_s == 4.0
    assert defaults.metrics_port == 9110
    configured = NodeTierSettings.from_env(
        {"URL4_CLOUD_NODE_SPILL_TIMEOUT_S": "2.5", "URL4_CLOUD_NODE_METRICS_PORT": "9555"}
    )
    assert configured.spill_timeout_s == 2.5
    assert configured.metrics_port == 9555


def test_default_settings_validate() -> None:
    NodeTierSettings().validate()


@pytest.mark.parametrize(
    ("overrides", "names"),
    [
        ({"max_inflight_per_worker": 0}, "max_inflight"),
        ({"aigateway_timeout_s": 30.0}, "aigateway_timeout_s"),
        ({"aigateway_timeout_s": 31.0}, "aigateway_timeout_s"),
        ({"spill_timeout_s": 0.0}, "spill_timeout_s"),
        ({"result_inline_cap_bytes": 101, "result_hard_cap_bytes": 100}, "result_inline_cap"),
    ],
    ids=["no-inflight", "aigw-equals-request", "aigw-over-request", "no-spill-time", "caps"],
)
def test_invalid_settings_are_refused_by_name(overrides: dict[str, Any], names: str) -> None:
    with pytest.raises(NodeTierError, match=names):
        NodeTierSettings(**overrides).validate()


@pytest.mark.asyncio
async def test_build_validates_settings_and_marks_readiness_failed() -> None:
    readiness = NodeReadiness()
    with pytest.raises(NodeTierError, match="max_inflight"):
        await build_node_tier(
            env={},
            config=_config(),
            settings=NodeTierSettings(max_inflight_per_worker=0),
            readiness=readiness,
            artifact_store=_NEVER_SPILLS,
            artifact_signing_key=_KEY,
        )
    assert readiness.ready is False
    assert readiness.reason is not None and "max_inflight" in readiness.reason


# --- FX-8 / FX-9 / FX-16: the spill store and its key -----------------------------------------


@pytest.mark.asyncio
async def test_a_filesystem_store_from_the_env_is_refused() -> None:
    """HL-H1: the node pod's disk is not the App's disk, so a parked artifact is unfetchable."""
    readiness = NodeReadiness()
    client = _MockAigateway((_MODEL,)).client()
    try:
        with pytest.raises(NodeTierError, match="OME-929"):
            await build_node_tier(
                env={job_env.ARTIFACT_SIGNING_KEY: _KEY},
                config=_config(),
                client=client,
                readiness=readiness,
            )
    finally:
        await client.aclose()
    assert readiness.ready is False
    assert readiness.reason is not None and "filesystem" in readiness.reason


@pytest.mark.asyncio
async def test_an_s3_store_from_the_env_with_a_key_builds() -> None:
    client = _MockAigateway((_MODEL,)).client()
    tier = await build_node_tier(
        env={**_S3_ENV, job_env.ARTIFACT_SIGNING_KEY: _KEY}, config=_config(), client=client
    )
    try:
        assert tier.readiness.ready is True
    finally:
        await tier.aclose()
        await client.aclose()


@pytest.mark.asyncio
async def test_an_empty_signing_key_is_refused_when_a_store_exists() -> None:
    readiness = NodeReadiness()
    client = _MockAigateway((_MODEL,)).client()
    try:
        with pytest.raises(NodeTierError, match="signing key"):
            await build_node_tier(env=_S3_ENV, config=_config(), client=client, readiness=readiness)
    finally:
        await client.aclose()
    assert readiness.ready is False


@pytest.mark.asyncio
async def test_a_store_construction_error_marks_readiness_failed_then_propagates() -> None:
    readiness = NodeReadiness()
    half = {job_env.ARTIFACT_STORE: "s3", job_env.ARTIFACT_SIGNING_KEY: _KEY}
    client = _MockAigateway((_MODEL,)).client()
    try:
        with pytest.raises(ValueError, match=job_env.ARTIFACT_S3_BUCKET):
            await build_node_tier(env=half, config=_config(), client=client, readiness=readiness)
    finally:
        await client.aclose()
    assert readiness.ready is False
    assert readiness.reason is not None and job_env.ARTIFACT_S3_BUCKET in readiness.reason


# --- FX-2 / FX-9: the spill runs after url4 returns, under its own bound -----------------------


def _spilling_tier(store: Any, *, signing_key: str, settings: NodeTierSettings) -> NodeTier:
    """A tier whose inner app answers 200 with a body over the (small) inline cap."""

    async def big(scope: Any, receive: Any, send: Any) -> None:
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"B" * 64})

    readiness = NodeReadiness()
    readiness.succeed()
    return NodeTier(
        settings=settings,
        metrics=build_node_metrics(),
        readiness=readiness,
        node=Url4Node("spill-timing"),
        inner=big,
        mounts=frozenset(),
        world_aclose=None,
        artifact_store=store,
        signing_key=signing_key,
        clock=lambda: 1_000_000.0,
    )


def _small_caps(**overrides: Any) -> NodeTierSettings:
    base: dict[str, Any] = {
        "request_timeout_s": 5.0,
        "aigateway_timeout_s": 4.0,
        "result_inline_cap_bytes": 10,
        "result_hard_cap_bytes": 1000,
    }
    return NodeTierSettings(**{**base, **overrides})


@pytest.mark.asyncio
async def test_a_spill_that_outlives_the_request_budget_still_redirects() -> None:
    """NT-H2: the spill ran inside url4's timeout; a late spill left the caller no response.

    The model answers at 0.25 s of a 0.4 s budget and the spill takes 0.3 s more. The spill
    now runs after url4 returns, so the caller gets its 303 instead of nothing.
    """

    async def slow_answer(request: httpx.Request) -> httpx.Response:
        await asyncio.sleep(0.25)
        return httpx.Response(
            200, json={"choices": [{"message": {"content": "B" * 64}}], "usage": {}}
        )

    store = _SlowStore(0.3)
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(slow_answer), base_url="http://aigateway.test"
    )
    tier = await build_node_tier(
        env={},
        config=_config(),
        client=client,
        settings=_small_caps(request_timeout_s=0.4, aigateway_timeout_s=0.3, spill_timeout_s=2.0),
        artifact_store=store,
        artifact_signing_key=_KEY,
    )
    try:
        async with _node_client(tier) as node:
            response = await node.get(
                f"/{_MODEL}", params={"q": "('')!'go'"}, headers={"X-User-Email": "a@x.test"}
            )
        assert response.status_code == 303, response.text
        assert response.headers["location"].startswith("/artifacts/")
        assert store.writes == 1
    finally:
        await tier.aclose()
        await client.aclose()


@pytest.mark.asyncio
async def test_a_spill_over_its_own_bound_is_502_artifact_spill_failed() -> None:
    store = _SlowStore(5.0)
    tier = _spilling_tier(store, signing_key=_KEY, settings=_small_caps(spill_timeout_s=0.1))
    try:
        async with _node_client(tier) as node:
            response = await node.get("/anything")
        assert response.status_code == 502
        assert response.json()["error"]["code"] == "artifact_spill_failed"
        assert "B" * 64 not in response.text
    finally:
        store.release.set()


@pytest.mark.asyncio
async def test_a_spill_with_no_key_never_writes() -> None:
    """FX-9: an unsigned artifact is unfetchable, so it must never be parked at all."""
    store = _SlowStore(0.0)
    tier = _spilling_tier(store, signing_key="", settings=_small_caps())
    async with _node_client(tier) as node:
        response = await node.get("/anything")
    assert response.status_code == 502
    assert response.json()["error"]["code"] == "artifact_spill_failed"
    assert store.writes == 0


# --- FX-4 / FX-5: the serve entry ---------------------------------------------------------------


def _serve_module() -> Any:
    # WHY importlib: the package re-exports the `serve` FUNCTION under the submodule's name, so
    # attribute access on the package yields the function, not this module.
    return importlib.import_module("screamingface_engine.world.node_tier.serve")


def test_sigterm_drains_readiness_before_uvicorn_exits() -> None:
    readiness = NodeReadiness()
    readiness.succeed()

    async def app(scope: Any, receive: Any, send: Any) -> None:  # pragma: no cover
        raise AssertionError("never served in this test")

    server = _serve_module()._draining_server(uvicorn.Config(app=app), readiness)
    server.handle_exit(signal.SIGTERM, None)
    assert readiness.ready is False
    assert readiness.reason == "draining"
    assert server.should_exit is True


@pytest.mark.asyncio
async def test_serve_starts_metrics_on_its_own_port_with_the_tier_registry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _serve_module()
    readiness = NodeReadiness()
    readiness.succeed()

    async def inner(scope: Any, receive: Any, send: Any) -> None:  # pragma: no cover
        raise AssertionError("never served in this test")

    tier = NodeTier(
        settings=NodeTierSettings(),
        metrics=build_node_metrics(),
        readiness=readiness,
        node=Url4Node("serve-test"),
        inner=inner,
        mounts=frozenset({"/m"}),
        world_aclose=None,
    )
    started: list[tuple[int, str, object]] = []
    served: list[object] = []

    async def fake_build(**kwargs: Any) -> NodeTier:
        return tier

    def fake_metrics_server(port: int, addr: str, registry: object) -> None:
        started.append((port, addr, registry))

    async def fake_serve(self: uvicorn.Server, sockets: object = None) -> None:
        served.append(self.config.port)

    monkeypatch.setattr(module, "build_node_tier", fake_build)
    monkeypatch.setattr(module, "start_http_server", fake_metrics_server)
    monkeypatch.setattr(uvicorn.Server, "serve", fake_serve)

    await module._serve({"URL4_CLOUD_NODE_HOST": "127.0.0.1"})

    assert started == [(9110, "127.0.0.1", tier.metrics.registry)]
    assert served == [9109]
