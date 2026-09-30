"""Shared arrangement for the E14 capture tests (OME-1307, GW-capture).

FEATURE: OME-1307 (E14) - the fixtures switch capture on, log in as the admin, and give the tests
a valid W3C ``traceparent`` for a chosen trace id.

AIDEV-NOTE: ``_versions_env`` MUST come before ``client`` in a fixture's parameter list. The app
reads ``Settings`` when ``client`` builds it, so the environment must be set first.
"""

from __future__ import annotations

import base64
import hashlib
import json

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi.testclient import TestClient

from aigateway.core.cache_versions.models import CacheCaptureEntry, RequestCachePrompt
from aigateway.core.request_cache.canonical import canonical_material
from aigateway.core.request_cache.models import RequestCacheEntry


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


# --- FEATURE: OME-1307 (E14, GW-freeze) - the freeze route arrangement (appended) ---------------


def raw_private_b64(key: Ed25519PrivateKey) -> str:
    """Standard base64 of the raw 32-byte private key: the form of AIGATEWAY_RECEIPT_SIGNING_KEY."""
    raw = key.private_bytes(
        serialization.Encoding.Raw,
        serialization.PrivateFormat.Raw,
        serialization.NoEncryption(),
    )
    return base64.b64encode(raw).decode()


@pytest.fixture
def signing_key() -> Ed25519PrivateKey:
    return Ed25519PrivateKey.generate()


@pytest.fixture
def _freeze_env(monkeypatch: pytest.MonkeyPatch, signing_key: Ed25519PrivateKey) -> None:
    monkeypatch.setenv("AIGATEWAY_RECEIPT_SIGNING_KEY", raw_private_b64(signing_key))
    monkeypatch.setenv("AIGW_CACHE_VERSIONS_ENABLED", "true")
    monkeypatch.setenv("AIGW_REQUEST_CACHE_ENABLED", "true")


@pytest.fixture
def freeze_client(_freeze_env: None, client: TestClient) -> TestClient:
    return login_admin(client)


async def seed_stored_calls(
    account_id: str, trace_id: str, count: int, *, answer_bytes: int = 64
) -> list[str]:
    """Write ``count`` traced `stored` calls (capture, prompt and live rows) through the models.

    Returns the key hashes in call order. For a test that needs a frozen version without the chat
    route. Bulk inserts keep a 5,000-call trace cheap.
    """
    keys: list[str] = []
    prompts: list[RequestCachePrompt] = []
    live: list[RequestCacheEntry] = []
    for index in range(count):
        material = canonical_material(
            {"model": "m", "messages": [{"role": "user", "content": f"{trace_id}:{index}"}]}
        )
        key = hashlib.sha256(material.encode()).hexdigest()
        answer = json.dumps({"choices": [{"message": {"content": "x" * answer_bytes}}]})
        keys.append(key)
        prompts.append(RequestCachePrompt(key_hash=key, request_json=material))
        live.append(
            RequestCacheEntry(
                key_hash=key,
                prompt_hash=key,
                provider="test",
                model="m",
                response_json=answer,
                response_size_bytes=len(answer),
                expires_at=None,
            )
        )
    await RequestCachePrompt.bulk_create(prompts, ignore_conflicts=True, batch_size=500)
    await RequestCacheEntry.bulk_create(live, ignore_conflicts=True, batch_size=500)
    await CacheCaptureEntry.bulk_create(
        [
            CacheCaptureEntry(
                account_id=account_id, trace_id=trace_id, key_hash=key, outcome="stored"
            )
            for key in keys
        ],
        batch_size=500,
    )
    return keys
