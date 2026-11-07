"""`/classify` is one stable world endpoint wherever the Gateway is configured (OME-1795).

FEATURE: hosted BYOM, Unit 3 (spec E1, E2). `build_world` registers `/classify` right after the
model routes, before the read-side mounts and the direct-mount snapshot. Every production path
builds through it, so the App's mount table, cold and warm children and local mode all serve it,
and adding a classifier needs no Engine route and no world config entry.

INVARIANT: `/classify` is one public path. No classifier ID reaches the shared schema or the
metric labels, because no classifier is ever declared to the Engine.
"""

from __future__ import annotations

import json
import tomllib
from pathlib import Path
from typing import Any

import httpx
import pytest
from httpx import ASGITransport

from screamingface_engine import cli, job_env
from screamingface_engine.app import create_app
from screamingface_engine.config import Settings
from screamingface_engine.rest.mounts import register_mounts
from screamingface_engine.testing import InMemoryEventStream
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
from screamingface_engine.world.models.registry import EMPTY_MODEL_WORLD
from screamingface_engine.world.serving import derive_mount_table, engine_route_paths
from url4.peer.server import Url4Node
from url4.streaming.protocol import ResultData, ResultEvent, TerminatedData, TerminatedEvent
from url4.streaming.protocol.envelope import source_for

_ENDPOINT = "byom_" + "0123456789abcdef" * 2
_PRIVATE = f"{_ENDPOINT}/model_v1"
_CLASSIFIER = f"{_ENDPOINT}/classifier_v1"
_PUBLIC = "anthropic/claude-haiku-4-5"
_EMAIL = {"X-User-Email": "caller@example.com"}
_WORLD = f"""
[aigateway]
base_url = "http://aigateway.test"
default_route = "/{_PUBLIC}"

[[aigateway.models]]
id = "{_PRIVATE}"
web_search = false
public_schema = false
"""


def _config(text: str) -> WorldConfig:
    return parse_config(tomllib.loads(text), {}, registry=EMPTY_MODEL_WORLD)


def _gateway_world(*models: str) -> WorldConfig:
    return WorldConfig(
        aigateway=AigatewaySection(
            base_url="http://aigateway.test",
            default_model=models[0],
            models=tuple(ModelSpec(id=model, web_search=False) for model in models),
        )
    )


# --- registration ---------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_gateway_world_serves_classify_as_a_direct_mount() -> None:
    async with httpx.AsyncClient() as client:
        io, aclose = await build_world(env={}, config=_gateway_world(_PUBLIC), client=client)
    assert isinstance(io, Url4Node)
    assert "/classify" in io.processor_routes()
    assert "/classify" in direct_mount_paths(io)
    # The node's reduce route is still the declared default model, not the new endpoint.
    assert io.default_route() == f"/{_PUBLIC}"
    assert aclose is not None
    await aclose()


@pytest.mark.asyncio
async def test_the_app_mount_table_lists_classify_as_one_public_mount(tmp_path: Path) -> None:
    path = tmp_path / "url4.toml"
    path.write_text(_WORLD)
    app = create_app(Settings(jwt_secret="classify-world-secret"))

    table = await derive_mount_table(
        env={job_env.RUNNER_CONFIG: str(path)}, engine_routes=engine_route_paths(app)
    )

    (classify,) = [mount for mount in table.mounts if mount.path == "/classify"]
    assert (classify.kind, classify.media_type, classify.public_schema) == ("endpoint", None, True)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "text",
    ["", '[data]\n"/corpus" = { value = "rows" }\n'],
    ids=["empty-world", "read-side-only"],
)
async def test_a_world_without_a_gateway_has_no_classify(text: str) -> None:
    io, aclose = await build_world(env={}, config=_config(text))

    assert "/classify" not in direct_mount_paths(io)
    if isinstance(io, Url4Node):
        assert "/classify" not in io.processor_routes()
    if aclose is not None:
        await aclose()


# --- collisions -----------------------------------------------------------------------------------


def _spy_on_worlds(monkeypatch: pytest.MonkeyPatch) -> list[AigatewayWorld]:
    built: list[AigatewayWorld] = []
    real = factory.build_aigateway_world

    async def spy(*args: Any, **kwargs: Any) -> AigatewayWorld:
        world = await real(*args, **kwargs)
        built.append(world)
        return world

    monkeypatch.setattr(factory, "build_aigateway_world", spy)
    return built


@pytest.mark.asyncio
async def test_a_declared_model_at_classify_fails_composition_and_closes_the_world(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    built = _spy_on_worlds(monkeypatch)

    with pytest.raises(WorldConfigError, match="/classify") as caught:
        await build_world(env={}, config=_gateway_world("classify"))

    assert "declared model" in str(caught.value)
    (world,) = built
    assert world._client.is_closed


@pytest.mark.asyncio
async def test_a_data_mount_at_classify_fails_composition_and_closes_the_world(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    built = _spy_on_worlds(monkeypatch)
    text = (
        f'[aigateway]\ndefault_route = "/{_PUBLIC}"\nmodels = ["{_PUBLIC}"]\n\n'
        '[data]\n"/classify" = { value = "shadow" }\n'
    )

    with pytest.raises(WorldConfigError, match="/classify"):
        await build_world(env={}, config=_config(text))

    (world,) = built
    assert world._client.is_closed


# --- the shared surfaces --------------------------------------------------------------------------


class _Runner:
    """Answers each direct run at once with one result and a terminal frame."""

    def __init__(self, stream: InMemoryEventStream) -> None:
        self._stream = stream
        self.targets: list[str] = []

    async def schedule(self, topic: str, url4: str, deadline_s: int, **_: Any) -> str:
        self.targets.append(url4)
        source = source_for(topic)
        await self._stream.publish(
            topic, ResultEvent(id="r", source=source, subject=topic, data=ResultData(body="{}"))
        )
        await self._stream.publish(
            topic,
            TerminatedEvent(
                id="t", source=source, subject=topic, data=TerminatedData(status="succeeded")
            ),
        )
        return f"job-{topic}"

    async def stop(self, topic: str) -> None:
        pass

    async def exists(self, topic: str) -> bool:
        return False

    async def status(self, topic: str) -> str:
        return "running"


@pytest.mark.asyncio
async def test_the_schema_and_metrics_name_classify_and_never_a_classifier(
    tmp_path: Path,
) -> None:
    path = tmp_path / "url4.toml"
    path.write_text(_WORLD)
    stream = InMemoryEventStream()
    runner = _Runner(stream)
    app = create_app(Settings(jwt_secret="classify-world-secret"), stream=stream, job_runner=runner)  # type: ignore[arg-type]
    table = await derive_mount_table(
        env={job_env.RUNNER_CONFIG: str(path)}, engine_routes=engine_route_paths(app)
    )
    register_mounts(app, table)
    context = json.dumps({"model": _CLASSIFIER, "input": "hello"})

    async with httpx.AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.get("/classify", params={"q": f"({context})!classify"}, headers=_EMAIL)
        schema = (await client.get("/openapi.json")).json()
        metrics = (await client.get("/metrics")).text

    assert resp.status_code == 200
    assert runner.targets and runner.targets[0].startswith("/classify?q=")
    assert "/classify" in schema["paths"]
    assert _ENDPOINT not in json.dumps(schema)
    assert 'screamingface_engine_mount_calls_total{path="/classify",status="200"} 1.0' in metrics
    assert _ENDPOINT not in metrics


# --- deployment review ----------------------------------------------------------------------------

_GATEWAY_FILE = f"""
schema_version = 1

[[endpoints]]
id = "{_ENDPOINT}"
display_name = "Research Lab"
enabled = false
origin = "https://private-lab.example"
allowed_account_ids = ["acct-1"]
validation_target = "model_v1"

[[endpoints.targets]]
alias = "model_v1"
task = "chat"
contract = "openai-chat-basic-v1"
request_path = "/v1/chat/completions"
upstream_model = "lab/model"

[[endpoints.targets]]
alias = "classifier_v1"
task = "text-classification"
contract = "hf-text-classification-v1"
request_path = "/"
response_envelope = "single-batch"
score_semantics = "bounded-score"
"""


def test_check_publication_passes_a_classifier_target_the_world_does_not_declare(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A classifier runs through `/classify` and is never declared to the Engine, so the review
    has nothing of it to publish."""
    world = tmp_path / "url4.toml"
    world.write_text(_WORLD)
    endpoints = tmp_path / "endpoints.toml"
    endpoints.write_text(_GATEWAY_FILE)
    monkeypatch.setenv(job_env.RUNNER_CONFIG, str(world))

    cli.main(["admin", "check-publication", "--endpoints", str(endpoints)])

    out = capsys.readouterr()
    assert "1 of 2 configured target(s) declared in this world; 0 problem(s)" in out.out
    assert "classifier_v1" not in out.out + out.err
    assert "private-lab" not in out.out + out.err
