"""Fixtures shared by the direct-OpenAI route suites.

WHY these two are fixtures in a conftest while the rest of the route arrangement is a
plain helper module: they are the only pieces pytest itself has to resolve by NAME from a
test signature. Everything else (the store double, the dispatch double, the body and
posting helpers) is ordinary code and lives in ``route_harness``, imported explicitly so
each suite's dependencies are visible in its own header.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def _cache_env(monkeypatch):
    # INVARIANT: listed BEFORE ``client`` in every dependent fixture, so the operator
    # switch is in the environment before the app is constructed. Set afterwards it
    # would be read as off and every dependent test would pass for the wrong reason —
    # which is why each one also positively asserts a non-``bypass`` status.
    monkeypatch.setenv("AIGW_REQUEST_CACHE_ENABLED", "true")


@pytest.fixture
def cache_client(_cache_env, client: TestClient) -> TestClient:
    response = client.post(
        "/v1/auth/login",
        json={"username": "admin", "password": "test-admin-password"},
    )
    assert response.status_code == 200, response.text
    client.headers.update({"Authorization": f"Bearer {response.json()['token']}"})
    return client
