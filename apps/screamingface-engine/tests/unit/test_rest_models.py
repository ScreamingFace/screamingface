from __future__ import annotations

import httpx
import pytest
from fastapi import FastAPI
from httpx import ASGITransport

from screamingface_engine.app import create_app
from screamingface_engine.catalog.port import (
    CatalogBadResponse,
    CatalogError,
    CatalogRejected,
    CatalogUnavailable,
    Credential,
    ModelCatalog,
    compute_etag,
)
from screamingface_engine.config import Settings
from screamingface_engine.testing import InMemoryEventStream

pytestmark = pytest.mark.asyncio

SECRET = "models-unit-secret"
EMAIL_A = "alice@example.com"
EMAIL_B = "bob@example.com"
PROBLEM_MEDIA_TYPE = "application/problem+json"


class FakeCatalog:
    def __init__(self, *, error: CatalogError | None = None, max_age: int = 247) -> None:
        self.error = error
        self.max_age = max_age
        self.seen: list[Credential] = []

    async def fetch(self, credential: Credential) -> ModelCatalog:
        self.seen.append(credential)
        if self.error is not None:
            raise self.error
        body: dict[str, object] = {
            "object": "list",
            "data": [{"id": f"model-for-{credential.key[:8]}", "object": "model"}],
        }
        return ModelCatalog(body=body, etag=compute_etag(body))

    def max_age_s(self, credential: Credential) -> int:
        return self.max_age


def build_app(catalog: FakeCatalog | None) -> FastAPI:
    return create_app(Settings(jwt_secret=SECRET), stream=InMemoryEventStream(), catalog=catalog)


def client_for(app: FastAPI) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


def auth(email: str) -> dict[str, str]:
    """The verified identity header the mesh gateway injects — this app's only caller signal."""
    return {"X-User-Email": email}


async def test_returns_the_catalog_body() -> None:
    async with client_for(build_app(FakeCatalog())) as client:
        response = await client.get("/v1/models", headers=auth(EMAIL_A))
    assert response.status_code == 200
    assert response.json()["object"] == "list"


async def test_the_response_carries_etag_cache_control_and_vary() -> None:
    async with client_for(build_app(FakeCatalog(max_age=247))) as client:
        response = await client.get("/v1/models", headers=auth(EMAIL_A))
    assert response.headers["ETag"].startswith('"')
    assert response.headers["Cache-Control"] == "private, max-age=247"
    assert response.headers["Vary"] == "X-Profile, X-User-Email"


async def test_max_age_reflects_the_remaining_ttl() -> None:
    async with client_for(build_app(FakeCatalog(max_age=12))) as client:
        response = await client.get("/v1/models", headers=auth(EMAIL_A))
    assert response.headers["Cache-Control"] == "private, max-age=12"


async def test_two_callers_receive_different_catalogs() -> None:
    catalog = FakeCatalog()
    async with client_for(build_app(catalog)) as client:
        first = await client.get("/v1/models", headers=auth(EMAIL_A))
        second = await client.get("/v1/models", headers=auth(EMAIL_B))
    assert first.json() != second.json()
    assert catalog.seen[0].key != catalog.seen[1].key


# INVARIANT: X-User-Email is the ONLY caller signal. A raw Cloudflare assertion and a bearer
# token must both be inert here — Envoy verifies the former and re-injects the result, and no
# aigateway mode this app targets reads the latter.
async def test_neither_an_access_proxy_assertion_nor_a_bearer_token_identifies_a_caller() -> None:
    catalog = FakeCatalog()
    async with client_for(build_app(catalog)) as client:
        await client.get(
            "/v1/models",
            headers={"Cf-Access-Jwt-Assertion": "cf-jwt", "Authorization": "Bearer tok"},
        )
    assert catalog.seen[0].identity == {}
    assert catalog.seen[0].key == Credential.derive().key


async def test_a_profile_is_refused_before_it_can_become_part_of_the_identity() -> None:
    """OME-1381 (Stage D producer-off): was `test_the_profile_becomes_part_of_the_identity`,
    which pinned `seen[0].profile == "team-a"`. The header now selects nothing, so it is refused
    before the catalog is asked and can key no entry."""
    catalog = FakeCatalog()
    async with client_for(build_app(catalog)) as client:
        response = await client.get("/v1/models", headers={**auth(EMAIL_A), "X-Profile": "team-a"})
    assert response.status_code == 400
    assert response.json()["code"] == "x_profile_unsupported"
    assert catalog.seen == []


# A local deployment runs aigateway with auth disabled, so there is no identity to send and the
# request must reach upstream rather than being refused here. Whether it is allowed is
# aigateway's decision, which is the only place that knows its own auth mode.
async def test_a_request_without_an_identity_still_reaches_upstream() -> None:
    catalog = FakeCatalog()
    async with client_for(build_app(catalog)) as client:
        response = await client.get("/v1/models")
    assert response.status_code == 200
    assert catalog.seen[0].identity == {}


# INVARIANT: an anonymous caller must never be served an identified caller's cached catalog.
async def test_an_anonymous_caller_does_not_share_a_cache_key_with_an_identified_one() -> None:
    catalog = FakeCatalog()
    async with client_for(build_app(catalog)) as client:
        await client.get("/v1/models")
        await client.get("/v1/models", headers=auth(EMAIL_A))
    assert catalog.seen[0].key != catalog.seen[1].key


async def test_a_refused_credential_yields_401_with_a_challenge() -> None:
    catalog = FakeCatalog(error=CatalogRejected("nope"))
    async with client_for(build_app(catalog)) as client:
        response = await client.get("/v1/models", headers=auth(EMAIL_A))
    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"] == "Bearer"


async def test_the_401_body_does_not_describe_the_upstream_configuration() -> None:
    catalog = FakeCatalog(error=CatalogRejected("token audience mismatch for issuer example-idp"))
    async with client_for(build_app(catalog)) as client:
        response = await client.get("/v1/models", headers=auth(EMAIL_A))
    assert "example-idp" not in response.text


@pytest.mark.parametrize(
    ("error", "status"),
    [(CatalogBadResponse("bad"), 502), (CatalogUnavailable("slow"), 504)],
)
async def test_upstream_failures_map_to_rfc9457_problems(error: CatalogError, status: int) -> None:
    async with client_for(build_app(FakeCatalog(error=error))) as client:
        response = await client.get("/v1/models", headers=auth(EMAIL_A))
    assert response.status_code == status
    assert response.headers["content-type"].startswith(PROBLEM_MEDIA_TYPE)
    assert response.json()["status"] == status


async def test_an_unconfigured_catalog_is_a_503() -> None:
    async with client_for(build_app(None)) as client:
        response = await client.get("/v1/models", headers=auth(EMAIL_A))
    assert response.status_code == 503
    assert response.headers["content-type"].startswith(PROBLEM_MEDIA_TYPE)


async def test_no_failure_path_produces_a_500() -> None:
    for error in (CatalogBadResponse("x"), CatalogUnavailable("x"), CatalogRejected("x")):
        async with client_for(build_app(FakeCatalog(error=error))) as client:
            response = await client.get("/v1/models", headers=auth(EMAIL_A))
        assert response.status_code < 500 or response.status_code in (502, 504)


async def test_a_matching_if_none_match_returns_304_without_a_body() -> None:
    async with client_for(build_app(FakeCatalog())) as client:
        first = await client.get("/v1/models", headers=auth(EMAIL_A))
        etag = first.headers["ETag"]
        second = await client.get("/v1/models", headers={**auth(EMAIL_A), "If-None-Match": etag})
    assert second.status_code == 304
    assert second.content == b""
    assert second.headers["ETag"] == etag


async def test_a_weak_validator_still_matches() -> None:
    async with client_for(build_app(FakeCatalog())) as client:
        first = await client.get("/v1/models", headers=auth(EMAIL_A))
        weak = f"W/{first.headers['ETag']}"
        second = await client.get("/v1/models", headers={**auth(EMAIL_A), "If-None-Match": weak})
    assert second.status_code == 304


async def test_a_wildcard_if_none_match_matches() -> None:
    async with client_for(build_app(FakeCatalog())) as client:
        response = await client.get("/v1/models", headers={**auth(EMAIL_A), "If-None-Match": "*"})
    assert response.status_code == 304


async def test_a_stale_validator_returns_the_full_body() -> None:
    async with client_for(build_app(FakeCatalog())) as client:
        response = await client.get(
            "/v1/models", headers={**auth(EMAIL_A), "If-None-Match": '"deadbeefdeadbeef"'}
        )
    assert response.status_code == 200
    assert response.json()["object"] == "list"


async def test_one_callers_validator_does_not_match_another_callers_catalog() -> None:
    async with client_for(build_app(FakeCatalog())) as client:
        first = await client.get("/v1/models", headers=auth(EMAIL_A))
        second = await client.get(
            "/v1/models", headers={**auth(EMAIL_B), "If-None-Match": first.headers["ETag"]}
        )
    assert second.status_code == 200


async def test_the_route_is_published_in_the_openapi_document() -> None:
    app = build_app(FakeCatalog())
    schema = app.openapi()
    assert "/v1/models" in schema["paths"]
    assert "Catalog" in schema["paths"]["/v1/models"]["get"]["tags"]


async def test_the_catalog_tag_is_registered_so_scalar_renders_it() -> None:
    app = build_app(FakeCatalog())
    names = {tag["name"] for tag in app.openapi().get("tags", [])}
    assert "Catalog" in names
