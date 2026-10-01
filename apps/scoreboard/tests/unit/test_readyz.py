"""Readiness is split from liveness (OME-944).

Both k8s probes used to hit the static `/healthz`, so a pod whose database was gone stayed Ready
and kept receiving traffic — every submission then 503'd. `/readyz` asks the database; `/healthz`
must never do so, because a dependency-coupled liveness probe turns one bad backend into a
restart loop across every replica.
"""

from __future__ import annotations

import asyncio
from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient

from scoreboard.config import Settings
from scoreboard.main import create_app
from scoreboard.routes import health

# Port 1 on loopback: nothing listens there, so the connect is refused immediately. A real
# unreachable database, not a mock — the failure the probe exists for, end to end.
_DOWN_DATABASE_URL = "postgres://scoreboard:unused@127.0.0.1:1/scoreboard"


@pytest.fixture
def down_client() -> Generator[TestClient, None, None]:
    settings = Settings(database_url=_DOWN_DATABASE_URL, cors_origins=[])
    with TestClient(create_app(settings)) as test_client:
        yield test_client


def test_readyz_is_ready_when_the_database_answers(client: TestClient) -> None:
    response = client.get("/readyz")

    assert response.status_code == 200
    assert response.json() == {"status": "ready"}


def test_readyz_fails_when_the_db_is_down(down_client: TestClient) -> None:
    # STORY: as the operator, a pod that cannot reach its database leaves the Service instead of
    # answering every submission with a 503.
    response = down_client.get("/readyz")

    assert response.status_code == 503
    assert response.json() == {"status": "not ready"}


def test_healthz_stays_live_when_the_db_is_down(down_client: TestClient) -> None:
    # INVARIANT: liveness never depends on the database — a dead DB must not restart every pod.
    response = down_client.get("/healthz")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


class _SlowConnection:
    async def execute_query(self, query: str) -> None:
        await asyncio.sleep(5)


class _BrokenConnection:
    async def execute_query(self, query: str) -> None:
        raise RuntimeError("tortoise was never initialised")


def test_readyz_fails_closed_when_the_check_exceeds_its_deadline(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A hung connect is the likeliest DB failure; the kubelet would time the probe out anyway,
    # but the app must answer within its own bound rather than tie up a worker.
    monkeypatch.setattr(health, "PROBE_TIMEOUT_S", 0.01)
    monkeypatch.setattr(health.connections, "get", lambda alias: _SlowConnection())

    response = client.get("/readyz")

    assert response.status_code == 503


def test_readyz_fails_closed_on_a_non_database_error(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    # An uninitialised Tortoise raises a bare RuntimeError, not an ORM error; the probe must
    # still answer 503 (a status the kubelet understands), never a 500.
    monkeypatch.setattr(health.connections, "get", lambda alias: _BrokenConnection())

    response = client.get("/readyz")

    assert response.status_code == 503
    assert response.json() == {"status": "not ready"}
