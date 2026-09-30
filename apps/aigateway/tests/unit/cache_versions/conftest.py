"""Shared arrangement for the E14 capture tests (OME-1307, GW-capture).

FEATURE: OME-1307 (E14) - the fixtures switch capture on, log in as the admin, and give the tests
a valid W3C ``traceparent`` for a chosen trace id.

AIDEV-NOTE: ``_versions_env`` MUST come before ``client`` in a fixture's parameter list. The app
reads ``Settings`` when ``client`` builds it, so the environment must be set first.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


def traceparent(trace_id: str) -> str:
    """A valid version-00, sampled ``traceparent`` header value for ``trace_id``."""
    return f"00-{trace_id}-{'a' * 16}-01"


@pytest.fixture
def _versions_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AIGW_CACHE_VERSIONS_ENABLED", "true")
    monkeypatch.setenv("AIGW_REQUEST_CACHE_ENABLED", "true")


def login_admin(client: TestClient) -> TestClient:
    """Log ``client`` in as the admin and return it."""
    response = client.post(
        "/v1/auth/login",
        json={"username": "admin", "password": "test-admin-password"},
    )
    assert response.status_code == 200, response.text
    client.headers.update({"Authorization": f"Bearer {response.json()['token']}"})
    return client


@pytest.fixture
def capture_client(_versions_env: None, client: TestClient) -> TestClient:
    return login_admin(client)
