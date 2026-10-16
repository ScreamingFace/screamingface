from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from screamingface_engine import job_env
from screamingface_engine.catalog import build_executable_catalog_service
from screamingface_engine.catalog.cache import CachedCatalog
from screamingface_engine.catalog.executable import ExecutableCatalog
from screamingface_engine.catalog.local_models import LocalCatalogSource, LocalModels
from screamingface_engine.catalog.port import (
    Credential,
    ModelCatalog,
    ModelParameterResponse,
    compute_etag,
)
from screamingface_engine.config import Settings

pytestmark = pytest.mark.asyncio


class _Gateway:
    counters = None
    entry_count = 0

    def __init__(self, ids: list[str]) -> None:
        self.ids = ids
        self.fetches = 0
        self.seen_parameters: list[str] = []
        self.model_parameter_source = self
        self.parameter_content: bytes | None = None

    async def fetch(self, credential: Credential) -> ModelCatalog:
        self.fetches += 1
        body = {
            "object": "list",
            "data": [{"id": model_id, "object": "model"} for model_id in self.ids],
        }
        return ModelCatalog(body=body, etag=compute_etag(body))

    async def fetch_model_parameters(
        self,
        credential: Credential,
        model: str,
        *,
        traceparent: str | None = None,
    ) -> ModelParameterResponse:
        del credential, traceparent
        self.seen_parameters.append(model)
        return ModelParameterResponse(
            status=200,
            content=self.parameter_content or json.dumps({"model": {"id": model}}).encode(),
        )

    def max_age_s(self, credential: Credential) -> int:
        return 60

    async def aclose(self) -> None:
        return None


def _ids(catalog: ModelCatalog) -> list[str]:
    data = catalog.body["data"]
    assert isinstance(data, list)
    return [row["id"] for row in data if isinstance(row, dict) and isinstance(row.get("id"), str)]


async def test_local_rows_are_encoded_once_and_join_the_run_snapshot() -> None:
    gateway = _Gateway(
        [
            "local/fixture:model",
            "ollama/llama3:8b",
            "openrouter/openai/gpt-5",
        ]
    )
    local = LocalModels(prefixes=("local", "ollama"))
    source = CachedCatalog(LocalCatalogSource(gateway, local), parameter_source=gateway)
    catalog = ExecutableCatalog(source, frozenset(), local=local)

    result = await catalog.fetch(Credential.derive())

    assert _ids(result) == [
        "local/fixture~model",
        "ollama/llama3~8b",
    ]
    assert local.raw_ids == ("local/fixture:model", "ollama/llama3:8b")
    assert catalog.admitted_model_ids == ("local/fixture~model", "ollama/llama3~8b")


async def test_a_healthy_catalog_replaces_the_complete_local_snapshot() -> None:
    gateway = _Gateway(["local/old"])
    local = LocalModels(prefixes=("local", "ollama"))
    source = CachedCatalog(LocalCatalogSource(gateway, local), parameter_source=gateway)
    catalog = ExecutableCatalog(source, frozenset(), local=local)
    await catalog.fetch(Credential.derive())

    gateway.ids = ["local/new"]
    source.invalidate()
    result = await catalog.fetch(Credential.derive())

    assert _ids(result) == ["local/new"]
    assert local.raw_ids == ("local/new",)
    assert catalog.admitted_model_ids == ("local/new",)


async def test_model_parameter_lookup_decodes_the_route_to_the_raw_gateway_id() -> None:
    gateway = _Gateway(["local/fixture:model"])
    local = LocalModels(prefixes=("local", "ollama"))
    source = CachedCatalog(LocalCatalogSource(gateway, local), parameter_source=gateway)
    catalog = ExecutableCatalog(source, frozenset(), local=local)
    await catalog.fetch(Credential.derive())
    assert catalog.model_parameter_source is not None

    response = await catalog.model_parameter_source.fetch_model_parameters(
        Credential.derive(),
        "local/fixture~model",
    )
    second = await catalog.model_parameter_source.fetch_model_parameters(
        Credential.derive(),
        "local/fixture~model",
    )

    assert response.status == 200
    assert second.status == 200
    assert gateway.fetches == 1
    assert gateway.seen_parameters == ["local/fixture:model", "local/fixture:model"]
    assert json.loads(response.content)["model"]["id"] == "local/fixture~model"


async def test_cold_model_parameter_lookup_refreshes_the_local_snapshot() -> None:
    gateway = _Gateway(["local/fixture:model"])
    local = LocalModels(prefixes=("local", "ollama"))
    source = CachedCatalog(LocalCatalogSource(gateway, local), parameter_source=gateway)
    catalog = ExecutableCatalog(source, frozenset(), local=local)
    assert catalog.model_parameter_source is not None
    assert catalog.admitted_model_ids == ()

    response = await catalog.model_parameter_source.fetch_model_parameters(
        Credential.derive(),
        "local/fixture~model",
    )

    assert response.status == 200
    assert gateway.fetches == 1
    assert gateway.seen_parameters == ["local/fixture:model"]
    assert catalog.admitted_model_ids == ("local/fixture~model",)


async def test_model_parameter_route_id_rewrite_preserves_every_other_byte() -> None:
    gateway = _Gateway(["local/fixture:model"])
    gateway.parameter_content = (
        b'{"future_number":1e999,"model" : {"id" : "local/fixture:model",'
        b'"nested":{"id":"local/fixture:model"}}}'
    )
    local = LocalModels(prefixes=("local", "ollama"))
    source = CachedCatalog(LocalCatalogSource(gateway, local), parameter_source=gateway)
    catalog = ExecutableCatalog(source, frozenset(), local=local)
    await catalog.fetch(Credential.derive())
    assert catalog.model_parameter_source is not None

    response = await catalog.model_parameter_source.fetch_model_parameters(
        Credential.derive(),
        "local/fixture~model",
    )

    assert response.content == (
        b'{"future_number":1e999,"model" : {"id" : "local/fixture~model",'
        b'"nested":{"id":"local/fixture:model"}}}'
    )


@pytest.mark.parametrize(
    "content",
    [
        b'{"model":{"id":"local/fixture:model"},"bad":garbage}',
        b'{"model":{"id":"local/fixture:model"},}',
        b'{"model":{"id":"local/fixture:model"},"x":[1,]}',
        (b'{"model":{"id":"local/fixture:model"},"model":{"id":"other"}}'),
        (
            b'{"model":{"id":"local/fixture:model"},"deep":'
            + (b"[" * 129)
            + b"0"
            + (b"]" * 129)
            + b"}"
        ),
    ],
)
async def test_model_parameter_route_id_rewrite_leaves_ambiguous_json_unchanged(
    content: bytes,
) -> None:
    gateway = _Gateway(["local/fixture:model"])
    gateway.parameter_content = content
    local = LocalModels(prefixes=("local", "ollama"))
    source = CachedCatalog(LocalCatalogSource(gateway, local), parameter_source=gateway)
    catalog = ExecutableCatalog(source, frozenset(), local=local)
    await catalog.fetch(Credential.derive())
    assert catalog.model_parameter_source is not None

    response = await catalog.model_parameter_source.fetch_model_parameters(
        Credential.derive(),
        "local/fixture~model",
    )

    assert response.content == content


@pytest.mark.parametrize(
    "model_id",
    [
        "local/bad~id",
        "local/space id",
        "local/",
        "other/fixture:model",
    ],
)
async def test_invalid_or_unapproved_rows_never_enter_the_local_overlay(model_id: str) -> None:
    gateway = _Gateway([model_id])
    local = LocalModels(prefixes=("local", "ollama"))
    source = CachedCatalog(LocalCatalogSource(gateway, local), parameter_source=gateway)
    catalog = ExecutableCatalog(source, frozenset(), local=local)

    result = await catalog.fetch(Credential.derive())

    assert result.body["data"] == []
    assert local.raw_ids == ()
    assert catalog.admitted_model_ids == ()


class _CallerGateway(_Gateway):
    async def fetch(self, credential: Credential) -> ModelCatalog:
        model_id = (
            "local/old" if credential.identity.get("X-User-Email") == "a@test" else "local/new"
        )
        body = {"object": "list", "data": [{"id": model_id}]}
        return ModelCatalog(body=body, etag=compute_etag(body))


async def test_a_warm_caller_cache_cannot_resurrect_an_older_local_snapshot() -> None:
    gateway = _CallerGateway([])
    local = LocalModels(prefixes=("local", "ollama"))
    source = CachedCatalog(LocalCatalogSource(gateway, local), parameter_source=gateway)
    catalog = ExecutableCatalog(source, frozenset(), local=local)
    caller_a = Credential.derive({"X-User-Email": "a@test"})
    caller_b = Credential.derive({"X-User-Email": "b@test"})

    await catalog.fetch(caller_a)
    await catalog.fetch(caller_b)
    assert local.raw_ids == ("local/new",)

    result = await catalog.fetch(caller_a)

    assert result.body["data"] == []
    assert local.raw_ids == ("local/new",)


async def test_builder_enables_local_rows_only_when_explicitly_requested(tmp_path: Path) -> None:
    config = tmp_path / "url4.toml"
    config.write_text("")

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"object": "list", "data": [{"id": "local/fixture:model"}]},
        )

    def client_factory(base_url: str) -> httpx.AsyncClient:
        return httpx.AsyncClient(base_url=base_url, transport=httpx.MockTransport(handler))

    settings = Settings(aigateway_base_url="http://127.0.0.1:9105")
    env = {job_env.RUNNER_CONFIG: str(config)}
    closed = build_executable_catalog_service(settings, env, client_factory=client_factory)
    local = build_executable_catalog_service(
        settings,
        env,
        client_factory=client_factory,
        local_model_prefixes=("local", "ollama"),
    )
    assert closed is not None and local is not None

    closed_rows = (await closed.fetch(Credential.derive())).body["data"]
    local_rows = (await local.fetch(Credential.derive())).body["data"]

    assert closed_rows == []
    assert local_rows == [{"id": "local/fixture~model"}]
    await closed.aclose()
    await local.aclose()
