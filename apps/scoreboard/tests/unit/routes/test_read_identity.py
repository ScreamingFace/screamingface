"""The READ-path identity dependency (OME-894).

Its trust decision lives in `core.auth.cloudflare_identity.optional_identity` and is tested
there. These tests cover the adapter: that it reads the four inputs off the real request and
Settings, so a wiring mistake cannot pass by being tested against a hand-made stub.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI

from scoreboard.config import Settings
from scoreboard.routes.dependencies import ReadIdentity

pytestmark = pytest.mark.asyncio


def _app(settings: Settings) -> FastAPI:
    app = FastAPI()
    app.state.settings = settings

    @app.get("/whoami")
    async def whoami(identity: ReadIdentity) -> dict[str, str | None]:
        return {"identity": identity}

    return app


@pytest_asyncio.fixture
async def header_mode_client() -> AsyncIterator[httpx.AsyncClient]:
    # ASGITransport reports the peer as "127.0.0.1", so the trusted network must contain it.
    settings = Settings.model_validate(
        {
            "database_url": "sqlite://:memory:",
            "cors_origins": [],
            "auth_mode": "cloudflare_headers",
            "allowed_networks": "127.0.0.0/8",
        }
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=_app(settings)), base_url="http://test"
    ) as client:
        yield client


@pytest_asyncio.fixture
async def disabled_mode_client() -> AsyncIterator[httpx.AsyncClient]:
    settings = Settings(database_url="sqlite://:memory:", cors_origins=[])
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=_app(settings)), base_url="http://test"
    ) as client:
        yield client


async def test_a_verified_header_reaches_the_route(
    header_mode_client: httpx.AsyncClient,
) -> None:
    response = await header_mode_client.get(
        "/whoami", headers={"X-User-Email": "alice@example.test"}
    )

    assert response.json() == {"identity": "alice@example.test"}


async def test_no_header_is_anonymous_and_not_an_error(
    header_mode_client: httpx.AsyncClient,
) -> None:
    # INVARIANT: reads never 401. A public board stays anonymously readable.
    response = await header_mode_client.get("/whoami")

    assert response.status_code == 200
    assert response.json() == {"identity": None}


async def test_disabled_mode_ignores_a_supplied_header(
    disabled_mode_client: httpx.AsyncClient,
) -> None:
    # INVARIANT (OME-894 D2): with auth disabled there is no verified identity, so a header is an
    # unverified claim. Honouring it would let anyone read a private board by setting one.
    response = await disabled_mode_client.get(
        "/whoami", headers={"X-User-Email": "attacker@evil.example"}
    )

    assert response.status_code == 200
    assert response.json() == {"identity": None}
