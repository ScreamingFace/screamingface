from __future__ import annotations

import pytest
from fastapi import APIRouter
from fastapi.testclient import TestClient


@pytest.mark.asyncio
async def test_create_app_fake_anthropic_oauth_factory(monkeypatch) -> None:
    monkeypatch.setenv("AIGATEWAY_FAKE_ANTHROPIC_OAUTH", "1")

    from aigateway.main import create_app

    app = create_app()
    # WHY no index (OME-1209 E4b): the app wires none; the credential store stands alone.
    assert not hasattr(app.state, "profile_index")

    async with app.state.anthropic_http_factory() as client:
        token = await client.post("https://platform.claude.com/oauth/token")
        unmapped = await client.post("https://example.com/oauth/token")

    assert token.status_code == 200
    assert token.json()["access_token"] == "fake-tok"
    assert unmapped.status_code == 404


@pytest.mark.asyncio
async def test_create_app_fake_anthropic_oauth_fail_mode(monkeypatch) -> None:
    monkeypatch.setenv("AIGATEWAY_FAKE_ANTHROPIC_OAUTH", "1")
    monkeypatch.setenv("AIGATEWAY_FAKE_ANTHROPIC_OAUTH_FAIL", "1")

    from aigateway.main import create_app

    app = create_app()

    async with app.state.anthropic_http_factory() as client:
        token = await client.post("https://console.anthropic.com/oauth/token")

    assert token.status_code == 400
    assert token.json() == {"error": "invalid_grant"}


@pytest.mark.asyncio
async def test_create_app_fake_codex_oauth_factory(monkeypatch) -> None:
    monkeypatch.setenv("AIGATEWAY_FAKE_CODEX_OAUTH", "1")

    from aigateway.main import create_app

    app = create_app()

    async with app.state.codex_http_factory() as client:
        token = await client.post("https://auth.openai.com/oauth/token")
        unmapped = await client.post("https://example.com/oauth/token")

    assert token.status_code == 200
    assert token.json()["refresh_token"] == "fake-codex-rt"
    assert unmapped.status_code == 404


def test_create_app_mounts_provider_auth_router(monkeypatch) -> None:
    from aigateway import main as main_module

    class _Plugin:
        custom_llm_provider = "dummy"

        def register_models(self) -> list:
            return []

        def auth_router(self) -> APIRouter:
            router = APIRouter()

            @router.get("/ping")
            async def ping() -> dict[str, bool]:
                return {"ok": True}

            return router

    def _load_plugins(registry) -> None:
        registry.register(_Plugin())

    monkeypatch.setattr(main_module, "load_plugins", _load_plugins)

    app = main_module.create_app()

    # WHY: FastAPI 0.141 stopped flattening included routers into `app.routes` — it stores
    # lazy `_IncludedRouter` wrappers instead, so the previous `route.path` scan found
    # nothing even though the endpoint served normally. Asserting through a real request is
    # strictly stronger than the scan it replaces: it proves the route is reachable and
    # serving, not merely that an object sits in a list. See OME-735.
    # INVARIANT: a plugin's auth_router is mounted under /v1/auth/<custom_llm_provider>.
    response = TestClient(app).get("/v1/auth/dummy/ping")
    assert response.status_code == 200
    assert response.json() == {"ok": True}
