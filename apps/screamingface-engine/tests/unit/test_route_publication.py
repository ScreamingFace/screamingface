"""A declared route can be executable without being published (OME-1770).

FEATURE: hosted BYOM, Unit 2. A configured-endpoint chat route is declared in the private world
config like any other `[[aigateway.models]]` entry, so a run can address it, but it belongs to the
accounts the Gateway grants. `public_schema = false` keeps it off every surface the Engine shares
with all callers: `/openapi.json`, the `/metrics` labels, and the details answer an ungranted
caller gets.

INVARIANT: publication is declared, never inferred. Nothing reads privacy from a provider prefix,
and every existing declaration keeps today's public default.
"""

from __future__ import annotations

import json
import tomllib
from pathlib import Path
from typing import Any

import httpx
import pytest
from httpx import ASGITransport

from screamingface_engine import job_env
from screamingface_engine.app import create_app
from screamingface_engine.catalog import build_executable_catalog_service
from screamingface_engine.catalog.executable import (
    ExecutableCatalog,
    ExecutableModelParameterSource,
)
from screamingface_engine.catalog.port import (
    Credential,
    ModelCatalog,
    ModelNotInstalled,
    ModelParameterResponse,
    compute_etag,
)
from screamingface_engine.config import Settings
from screamingface_engine.rest.mounts import register_mounts
from screamingface_engine.testing import InMemoryEventStream
from screamingface_engine.world.config import (
    ModelSpec,
    WorldConfig,
    WorldConfigError,
    parse_config,
)
from screamingface_engine.world.models.registry import EMPTY_MODEL_WORLD
from screamingface_engine.world.publication import (
    private_model_ids,
    private_mount_paths,
    private_route_ids,
)
from screamingface_engine.world.serving import MountDescriptor, MountTable, derive_mount_table
from url4.streaming.protocol import ResultData, ResultEvent, TerminatedData, TerminatedEvent
from url4.streaming.protocol.envelope import source_for

_ENDPOINT = "byom_" + "0123456789abcdef" * 2
_PRIVATE = f"{_ENDPOINT}/model_v1"
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


def _parse(text: str) -> WorldConfig:
    return parse_config(tomllib.loads(text), {}, registry=EMPTY_MODEL_WORLD)


def _declared(*models: str) -> WorldConfig:
    return _parse(f'[aigateway]\ndefault_route = "/{_PUBLIC}"\nmodels = [{", ".join(models)}]\n')


# --- the declaration ------------------------------------------------------------------------


def test_a_route_is_public_unless_it_says_otherwise() -> None:
    section = _declared(
        f'"{_PUBLIC}"', f'{{ id = "{_PRIVATE}", web_search = false, public_schema = false }}'
    ).aigateway

    assert section is not None
    assert section.models == (
        ModelSpec(id=_PUBLIC),
        ModelSpec(id=_PRIVATE, web_search=False, public_schema=False),
    )
    assert section.models[0].public_schema is True


def test_a_configured_endpoint_id_is_not_private_because_of_its_prefix() -> None:
    config = _declared(f'"{_PUBLIC}"', f'{{ id = "{_PRIVATE}" }}')

    assert private_route_ids(config) == frozenset()


def test_a_non_boolean_public_schema_is_rejected() -> None:
    with pytest.raises(WorldConfigError, match="public_schema must be a boolean"):
        _declared(f'"{_PUBLIC}"', f'{{ id = "{_PRIVATE}", public_schema = "no" }}')


def test_the_private_set_has_one_form_per_surface() -> None:
    tilde = "byom_" + "f" * 32 + "/model.v1~x"
    config = _declared(
        f'"{_PUBLIC}"',
        f'{{ id = "{_PRIVATE}", public_schema = false }}',
        f'{{ id = "{tilde}", public_schema = false }}',
    )

    assert private_route_ids(config) == {_PRIVATE, tilde}
    assert private_mount_paths(config) == {f"/{_PRIVATE}", f"/{tilde}"}
    assert private_model_ids(config) == {_PRIVATE, tilde.replace("~", ":")}


def test_a_world_without_a_gateway_section_has_no_private_routes() -> None:
    assert private_route_ids(WorldConfig()) == frozenset()


@pytest.mark.asyncio
async def test_the_mount_table_marks_only_the_private_route(tmp_path: Path) -> None:
    path = tmp_path / "url4.toml"
    path.write_text(_WORLD)

    table = await derive_mount_table(env={job_env.RUNNER_CONFIG: str(path)}, engine_routes=())

    flags = {mount.path: mount.public_schema for mount in table.mounts}
    assert flags[f"/{_PRIVATE}"] is False
    assert flags[f"/{_PUBLIC}"] is True
    assert [p for p, public in flags.items() if not public] == [f"/{_PRIVATE}"]


# --- the shared surfaces ----------------------------------------------------------------------


class _Runner:
    """Queues each direct run and answers it at once with one result and a terminal frame."""

    def __init__(self, stream: InMemoryEventStream) -> None:
        self._stream = stream
        self.targets: list[str] = []

    async def schedule(self, topic: str, url4: str, deadline_s: int, **_: Any) -> str:
        self.targets.append(url4)
        source = source_for(topic)
        await self._stream.publish(
            topic, ResultEvent(id="r", source=source, subject=topic, data=ResultData(body="ok"))
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


def _mounted_app() -> tuple[Any, _Runner]:
    stream = InMemoryEventStream()
    runner = _Runner(stream)
    app = create_app(Settings(jwt_secret="publication-secret"), stream=stream, job_runner=runner)  # type: ignore[arg-type]
    table = MountTable(
        mounts=(
            MountDescriptor(f"/{_PUBLIC}", "endpoint", None),
            MountDescriptor(f"/{_PRIVATE}", "endpoint", None, public_schema=False),
        ),
        config_digest=None,
    )
    register_mounts(app, table)
    return app, runner


def _client(app: Any) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


@pytest.mark.asyncio
async def test_a_private_mount_runs_but_the_shared_schema_never_names_it() -> None:
    """STORY: as a granted caller I run my endpoint's model by its route without listing it,
    while the schema every caller can read does not reveal that the route exists."""
    app, runner = _mounted_app()
    async with _client(app) as client:
        schema = (await client.get("/openapi.json")).json()
        resp = await client.get(f"/{_PRIVATE}?q=('')!'go'", headers=_EMAIL)

    assert f"/{_PUBLIC}" in schema["paths"]
    assert _ENDPOINT not in json.dumps(schema)
    assert resp.status_code == 200
    assert runner.targets == [f"/{_PRIVATE}?q=('')!'go'"]


@pytest.mark.asyncio
async def test_metrics_label_a_private_mount_without_its_path() -> None:
    app, _ = _mounted_app()
    async with _client(app) as client:
        await client.get(f"/{_PRIVATE}?q=('')!'go'", headers=_EMAIL)
        await client.post(f"/{_PRIVATE}")
        await client.get(f"/{_PUBLIC}?q=('')!'go'", headers=_EMAIL)
        metrics = (await client.get("/metrics")).text

    assert _ENDPOINT not in metrics
    assert 'screamingface_engine_mount_calls_total{path="<private>",status="200"} 1.0' in metrics
    assert 'method="GET",path="<private>",status="200"' in metrics
    assert 'method="POST",path="<unmatched>",status="404"' in metrics
    assert f'screamingface_engine_mount_calls_total{{path="/{_PUBLIC}",status="200"}} 1.0' in (
        metrics
    )


# --- the details answer -----------------------------------------------------------------------


class _Gateway:
    """Answers every details request with one fixed status and body, recording what it saw."""

    def __init__(self, status: int, body: dict[str, Any]) -> None:
        self._status, self._content = status, json.dumps(body).encode()
        self.seen: list[str] = []

    async def fetch_model_parameters(
        self, credential: Credential, model: str, *, traceparent: str | None = None
    ) -> ModelParameterResponse:
        self.seen.append(model)
        return ModelParameterResponse(status=self._status, content=self._content)

    async def aclose(self) -> None:
        pass


class _EmptyCatalog:
    counters = None
    entry_count = 0
    model_parameter_source = None

    async def fetch(self, credential: Credential) -> ModelCatalog:
        body: dict[str, object] = {"object": "list", "data": []}
        return ModelCatalog(body=body, etag=compute_etag(body))

    def max_age_s(self, credential: Credential) -> int:
        return 60

    async def aclose(self) -> None:
        pass


def _details_app(gateway: _Gateway) -> Any:
    declared = frozenset({_PUBLIC, _PRIVATE})
    return create_app(
        Settings(jwt_secret="publication-secret"),
        stream=InMemoryEventStream(),
        catalog=ExecutableCatalog(_EmptyCatalog(), declared),
        model_parameters=ExecutableModelParameterSource(
            gateway, declared, private=frozenset({_PRIVATE})
        ),
    )


_UNKNOWN = {"detail": f"unknown provider: {_ENDPOINT}"}


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [400, 404])
async def test_an_ungranted_caller_gets_the_undeclared_answer_for_a_private_route(
    status: int,
) -> None:
    gateway = _Gateway(status, _UNKNOWN)
    async with _client(_details_app(gateway)) as client:
        private = await client.get("/v1/model-parameters", params={"model": _PRIVATE})
        undeclared = await client.get("/v1/model-parameters", params={"model": "never/declared"})

    assert gateway.seen == [_PRIVATE]
    assert private.status_code == undeclared.status_code == 404
    assert private.json()["detail"] == undeclared.json()["detail"]
    assert _ENDPOINT not in private.text


@pytest.mark.asyncio
async def test_a_public_route_keeps_the_gateway_answer() -> None:
    gateway = _Gateway(400, {"detail": "unknown provider: anthropic"})
    async with _client(_details_app(gateway)) as client:
        resp = await client.get("/v1/model-parameters", params={"model": _PUBLIC})

    assert resp.status_code == 400
    assert resp.json() == {"detail": "unknown provider: anthropic"}


@pytest.mark.asyncio
async def test_a_granted_caller_gets_the_private_contract_unchanged() -> None:
    body = {"model": {"id": _PRIVATE}, "execution_access": "configured"}
    async with _client(_details_app(_Gateway(200, body))) as client:
        resp = await client.get("/v1/model-parameters", params={"model": _PRIVATE})

    assert resp.status_code == 200
    assert resp.json() == body


@pytest.mark.asyncio
async def test_the_production_builder_reads_the_private_set_from_the_world(
    tmp_path: Path,
) -> None:
    path = tmp_path / "url4.toml"
    path.write_text(_WORLD)
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.path)
        return httpx.Response(400, json=_UNKNOWN)

    service = build_executable_catalog_service(
        Settings(aigateway_base_url="http://aigateway.test"),
        {job_env.RUNNER_CONFIG: str(path)},
        client_factory=lambda base_url: httpx.AsyncClient(
            base_url=base_url, transport=httpx.MockTransport(handler)
        ),
    )
    assert service is not None
    source = service.model_parameter_source
    assert source is not None

    with pytest.raises(ModelNotInstalled):
        await source.fetch_model_parameters(Credential.derive(), _PRIVATE)
    public = await source.fetch_model_parameters(Credential.derive(), _PUBLIC)

    assert public.status == 400
    assert seen == ["/v1/model-parameters", "/v1/model-parameters"]
    await service.aclose()
