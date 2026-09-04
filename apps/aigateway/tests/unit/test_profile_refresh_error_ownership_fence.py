"""Regression coverage for a failing refresh that loses profile ownership."""

from __future__ import annotations

import asyncio
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import pytest
from fastapi.testclient import TestClient

from aigateway.core.errors import AuthError
from aigateway.plugins.anthropic_provider.auth import AnthropicOAuth
from tests.conftest import drain_private_catalog
from tests.unit import test_profile_refresh_ownership_fence as ownership


@pytest.fixture
def oauth_client(
    authenticated_client: TestClient,
    credential_blobs: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> TestClient:
    ownership._accept_api_keys(monkeypatch)
    ownership._authenticate_oauth_profile(authenticated_client)
    authenticated_client._credential_probe = credential_blobs  # noqa: SLF001 - test wiring
    return authenticated_client


def test_a_failing_stale_refresh_keeps_the_replacement_private_listing(
    oauth_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A refresh that lost ownership cannot retire the replacement owner's catalog."""
    http = ownership._enable_private_discovery(oauth_client, monkeypatch)
    started = threading.Event()
    release = threading.Event()

    async def _fail_after_replacement(self: Any, creds: dict) -> dict:
        del self, creds
        started.set()
        if not await asyncio.to_thread(release.wait, 5):
            raise TimeoutError("the parked refresh was never released")
        raise AuthError("canned stale-owner refresh failure")

    monkeypatch.setattr(AnthropicOAuth, "_refresh_credential", _fail_after_replacement)

    with ThreadPoolExecutor(max_workers=1) as executor:
        stale_refresh = executor.submit(oauth_client.post, ownership._REFRESH_URL)
        assert started.wait(5), "the stale refresh never reached the provider window"
        ownership._replace_with_api_key(oauth_client)
        release.set()
        response = stale_refresh.result(timeout=10)

    assert response.status_code == 401, response.text
    drain_private_catalog(oauth_client)
    assert http.dials == 1, "the replacement did not warm its private catalog exactly once"

    listing = oauth_client.get(ownership._LISTING_URL)

    assert listing.status_code == 200, listing.text
    assert listing.json()["status"] == "fresh", listing.json()
    assert http.dials == 1, "the losing refresh retired the replacement owner's listing"
