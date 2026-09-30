"""CORS grants for the Studio frontend (spec: docs/spec/2026-09-29-engine-cors-studio.md).

FEATURE (OME-1308, E18 · A local app): the Studio webview calls the Engine's REST surface
cross-origin, so the Engine must grant Studio's origins — and only those.
"""

from __future__ import annotations

import httpx
import pytest
from fastapi.testclient import TestClient

from screamingface_engine.app import create_app
from screamingface_engine.config import Settings

STUDIO_ORIGINS = [
    "http://localhost:3000",
    "tauri://localhost",
    "http://tauri.localhost",
    "https://tauri.localhost",
]
FOREIGN_ORIGIN = "https://evil.example"


def _preflight(client: TestClient, origin: str) -> httpx.Headers:
    return client.options(
        "/healthz",
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "authorization",
        },
    ).headers


def test_default_origins_are_exactly_studios() -> None:
    # INVARIANT: the default grants Studio only — dev server + Tauri 2 packaged origins.
    assert Settings().cors_allowed_origins == STUDIO_ORIGINS


@pytest.mark.parametrize("origin", STUDIO_ORIGINS)
def test_preflight_from_studio_origin_is_granted(origin: str) -> None:
    headers = _preflight(TestClient(create_app()), origin)
    assert headers["access-control-allow-origin"] == origin
    assert "authorization" in headers["access-control-allow-headers"].lower()


def test_simple_request_from_studio_origin_carries_grant() -> None:
    client = TestClient(create_app())
    resp = client.get("/healthz", headers={"Origin": "http://localhost:3000"})
    assert resp.status_code == 200
    assert resp.headers["access-control-allow-origin"] == "http://localhost:3000"


def test_error_response_carries_grant() -> None:
    # WHY: Studio must be able to read an Engine problem body (e.g. a 404), not a CORS failure.
    client = TestClient(create_app())
    resp = client.get("/no-such-route", headers={"Origin": "tauri://localhost"})
    assert resp.status_code == 404
    assert resp.headers["access-control-allow-origin"] == "tauri://localhost"


def test_foreign_origin_is_not_granted() -> None:
    client = TestClient(create_app())
    assert "access-control-allow-origin" not in _preflight(client, FOREIGN_ORIGIN)
    resp = client.get("/healthz", headers={"Origin": FOREIGN_ORIGIN})
    assert "access-control-allow-origin" not in resp.headers


def test_credentials_are_not_allowed() -> None:
    # WHY: Engine auth is header-borne, never cookies — a credentials grant would only widen
    # what a granted origin can do.
    client = TestClient(create_app())
    headers = _preflight(client, "http://localhost:3000")
    assert "access-control-allow-credentials" not in headers


def test_env_override_replaces_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("URL4_CLOUD_CORS_ALLOWED_ORIGINS", '["https://studio.example"]')
    settings = Settings()
    assert settings.cors_allowed_origins == ["https://studio.example"]
    client = TestClient(create_app(settings))
    assert _preflight(client, "https://studio.example")["access-control-allow-origin"] == (
        "https://studio.example"
    )
    assert "access-control-allow-origin" not in _preflight(client, "http://localhost:3000")


def test_empty_list_grants_no_origin() -> None:
    # INVARIANT: fail closed — an emptied list grants nothing, it does not fall back to "*".
    client = TestClient(create_app(Settings(cors_allowed_origins=[])))
    for origin in [*STUDIO_ORIGINS, FOREIGN_ORIGIN]:
        assert "access-control-allow-origin" not in _preflight(client, origin)
