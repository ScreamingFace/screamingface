from __future__ import annotations

import httpx
import pytest

from screamingface_engine.app import create_app
from screamingface_engine.catalog import build_catalog_service
from screamingface_engine.catalog.cache import CachedCatalog
from screamingface_engine.catalog.port import Credential, ModelCatalog, compute_etag
from screamingface_engine.config import Settings
from screamingface_engine.testing import InMemoryEventStream

pytestmark = pytest.mark.asyncio

BODY: dict[str, object] = {"object": "list", "data": [{"id": "m", "object": "model"}]}
TOKEN = "wiring-secret-token"


class FakeCatalog:
    def __init__(self) -> None:
        self.seen: list[Credential] = []

    async def fetch(self, credential: Credential) -> ModelCatalog:
        self.seen.append(credential)
        return ModelCatalog(body=BODY, etag=compute_etag(BODY))

    def max_age_s(self, credential: Credential) -> int:
        return 60


async def test_no_base_url_means_no_catalog_service() -> None:
    assert build_catalog_service(Settings(aigateway_base_url=None)) is None


async def test_a_base_url_yields_a_cached_service() -> None:
    service = build_catalog_service(Settings(aigateway_base_url="http://aigw.test"))
    assert isinstance(service, CachedCatalog)
    await service.aclose()


async def test_the_factory_needs_no_credential_setting() -> None:
    service = build_catalog_service(Settings(aigateway_base_url="http://aigw.test"))
    assert service is not None
    await service.aclose()


async def test_cache_tunables_are_taken_from_settings() -> None:
    settings = Settings(
        aigateway_base_url="http://aigw.test",
        models_cache_ttl_s=11.0,
        models_cache_max_entries=3,
        models_upstream_concurrency=2,
    )
    service = build_catalog_service(settings)
    assert service is not None
    assert service._ttl_s == 11.0  # noqa: SLF001 - asserting the wiring, not behaviour
    assert service._max_entries == 3  # noqa: SLF001
    await service.aclose()


async def test_no_setting_holds_an_aigateway_credential() -> None:
    suspicious = {
        name
        for name in Settings.model_fields
        if any(word in name for word in ("token", "secret", "key", "password", "credential"))
    }
    # Each entry is a reviewed decision, not a waiver. Adding one means answering "where does
    # this value come from, and what does it grant?" — which is the whole point of pinning the set.
    #
    #   jwt_secret              the App's own token-signing secret; value, from a Secret via envFrom
    #   artifact_s3_access_key  an S3 access key ID — an identifier, not a secret; it is the
    #                           public half of the pair and appears in every signed request
    #   artifact_s3_secret_key  a VALUE, from a Secret via envFrom, exactly like jwt_secret.
    #                           WHY the App must hold it (OME-929): it signs its own GETs to stream
    #                           spilled results back, so a name alone cannot work the way it did
    #                           for Tavily, where only the worker's children ever use the
    #                           credential (and the chart attaches that Secret by `envFrom`
    #                           directly — the name-only settings were retired with the Job
    #                           adapter, OME-1092).
    #                           Blast radius if leaked: read/write on the artifact bucket by a peer
    #                           already inside the NetworkPolicy. No provider or model credentials.
    assert suspicious == {
        "jwt_secret",
        "artifact_s3_access_key",
        "artifact_s3_secret_key",
    }, "a new secret-shaped setting appeared — confirm it is sourced from a Secret reference"


async def test_create_app_exposes_an_injected_catalog() -> None:
    catalog = FakeCatalog()
    app = create_app(Settings(jwt_secret="s"), stream=InMemoryEventStream(), catalog=catalog)
    assert app.state.catalog is catalog


async def test_create_app_without_a_catalog_leaves_state_none() -> None:
    app = create_app(Settings(jwt_secret="s"), stream=InMemoryEventStream())
    assert app.state.catalog is None


async def test_the_shutdown_hook_closes_the_upstream_client() -> None:
    closed: list[bool] = []

    async def aclose() -> None:
        closed.append(True)

    service = CachedCatalog(FakeCatalog(), source_aclose=aclose)
    await service.aclose()
    assert closed == [True]


async def test_closing_a_service_with_no_client_is_a_noop() -> None:
    await CachedCatalog(FakeCatalog()).aclose()


async def test_the_built_service_closes_its_own_httpx_client() -> None:
    service = build_catalog_service(Settings(aigateway_base_url="http://aigw.test"))
    assert service is not None
    await service.aclose()
    await service.aclose()


async def test_cache_counters_are_exposed_on_the_metrics_endpoint() -> None:
    catalog = build_catalog_service(
        Settings(aigateway_base_url="http://aigw.test"),
        client_factory=lambda _: httpx.AsyncClient(
            base_url="http://aigw.test",
            transport=httpx.MockTransport(lambda request: httpx.Response(200, json=BODY)),
        ),
    )
    assert catalog is not None
    app = create_app(Settings(jwt_secret="s"), stream=InMemoryEventStream(), catalog=catalog)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        await client.get("/v1/models", headers={"Authorization": f"Bearer {TOKEN}"})
        await client.get("/v1/models", headers={"Authorization": f"Bearer {TOKEN}"})
        scrape = await client.get("/metrics")
    body = scrape.text
    assert "screamingface_engine_catalog_cache_hits" in body
    assert "screamingface_engine_catalog_cache_misses" in body
    assert "screamingface_engine_catalog_entries" in body
    await catalog.aclose()


async def test_no_metric_line_ever_carries_a_credential_or_cache_key() -> None:
    catalog = build_catalog_service(
        Settings(aigateway_base_url="http://aigw.test"),
        client_factory=lambda _: httpx.AsyncClient(
            base_url="http://aigw.test",
            transport=httpx.MockTransport(lambda request: httpx.Response(200, json=BODY)),
        ),
    )
    assert catalog is not None
    app = create_app(Settings(jwt_secret="s"), stream=InMemoryEventStream(), catalog=catalog)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        await client.get("/v1/models", headers={"Authorization": f"Bearer {TOKEN}"})
        scrape = await client.get("/metrics")
    assert TOKEN not in scrape.text
    assert Credential.derive(TOKEN).key not in scrape.text
    await catalog.aclose()
