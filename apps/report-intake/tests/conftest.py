from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncGenerator, Generator
from pathlib import Path

import pytest
import pytest_asyncio
from fastapi.testclient import TestClient
from tortoise import Tortoise
from tortoise.migrations.api import migrate

from report_intake.config import ENV_PREFIX, Settings
from report_intake.db import build_tortoise_config, close_db, init_db
from report_intake.main import create_app


@pytest.fixture(autouse=True)
def hermetic_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Start every test from an environment this service reads nothing out of.

    `create_app` deliberately refuses to start on an unrecognised `REPORT_INTAKE_*` variable, so
    a developer with one exported would otherwise see the whole suite fail for a reason that has
    nothing to do with their change. It also keeps `FORWARDED_ALLOW_IPS` — which is uvicorn's,
    not ours, and is therefore plausibly already set on a machine — out of the guard tests.
    """
    for key in list(os.environ):
        if key.upper().startswith(ENV_PREFIX):
            monkeypatch.delenv(key, raising=False)
    monkeypatch.delenv("FORWARDED_ALLOW_IPS", raising=False)


async def _apply_migrations(database_url: str) -> None:
    try:
        await migrate(config=build_tortoise_config(database_url))
    finally:
        await Tortoise.close_connections()


@pytest.fixture
def database_url(tmp_path: Path) -> str:
    """A private database per test, with the schema built by the COMMITTED migration.

    Not `Tortoise.generate_schemas()`, which builds from the models and would leave the one file
    an operator actually runs untested — `apps/scoreboard` carries a hand-written guard against
    exactly that gap. Running the real migration here means every store and route test below is
    also a test that `0001_initial` still matches the models.

    A file rather than `sqlite://:memory:`, because a memory database belongs to one connection
    and this schema is applied on one while the app under test opens another.
    """
    url = f"sqlite://{tmp_path / 'report-intake.sqlite3'}"
    asyncio.run(_apply_migrations(url))
    return url


@pytest_asyncio.fixture
async def storage(database_url: str) -> AsyncGenerator[None, None]:
    """Tortoise open against the migrated database, for tests that talk to the store directly."""
    await init_db(database_url)
    try:
        yield
    finally:
        await close_db()


@pytest.fixture
def client(hermetic_environment: None, database_url: str) -> Generator[TestClient, None, None]:
    """The default posture: `auth_mode=disabled`, which is loopback-only.

    WHY the peer and the base URL are set explicitly: starlette's TestClient defaults to
    `("testclient", 50000)` — not an address — and `http://testserver`, so
    `LoopbackOnlyMiddleware` would refuse every request in this suite and `apps/aigateway` carries
    the same workaround for the same reason. Set here rather than per test, because a route test
    that has to know about the auth posture is a route test that will be wrong after the next
    change to it.
    """
    app = create_app(Settings(database_url=database_url))
    with TestClient(app, base_url="http://127.0.0.1", client=("127.0.0.1", 50000)) as test_client:
        yield test_client


MESH_NETWORK = "10.0.0.0/8"
MESH_PEER = "10.1.2.3"
"""The mesh proxy, which is the peer on EVERY request in a deployment — including an anonymous
one. That is the whole shape of spec §7: the two caller classes are not two peers, they are one
peer that either did or did not inject an identity header, which is what plan §10's two-hostname
topology produces. A test that made the anonymous caller a stranger from the internet would be
testing a request no deployment ever sees."""


class StubTurnstile:
    """Cloudflare, as far as a test is concerned. ``answer`` is what siteverify decided; set it to
    an exception to make the gate unevaluable."""

    def __init__(self) -> None:
        self.answer: bool | Exception = True
        self.tokens: list[str] = []

    async def verify(self, token: str) -> bool:
        self.tokens.append(token)
        if isinstance(self.answer, Exception):
            raise self.answer
        return self.answer


@pytest.fixture
def turnstile() -> StubTurnstile:
    return StubTurnstile()


@pytest.fixture
def mesh_client(
    hermetic_environment: None, database_url: str, turnstile: StubTurnstile
) -> Generator[TestClient, None, None]:
    """The deployed posture: `auth_mode=mesh_or_turnstile`, reached through the mesh.

    No loopback guard is installed in this mode, so the base URL is the public hostname a real
    caller uses. Whether a request is mesh-verified or anonymous is decided by the identity
    header alone — the peer is the same either way.
    """
    app = create_app(
        Settings.model_validate(
            {
                "database_url": database_url,
                "auth_mode": "mesh_or_turnstile",
                "allowed_networks": MESH_NETWORK,
                "turnstile_secret": "a-test-secret",
            }
        )
    )
    # The one seam the real adapter sits on. Installed before the lifespan runs, so nothing in
    # this suite can reach Cloudflare even if a case forgets to arrange an answer.
    app.state.turnstile_verifier = turnstile
    base_url = "http://reports.example.test"
    with TestClient(app, base_url=base_url, client=(MESH_PEER, 50000)) as test_client:
        yield test_client
