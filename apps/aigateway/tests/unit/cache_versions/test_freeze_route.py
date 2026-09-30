"""CV-7, CV-8, CV-9, CV-10, CV-14, CV-27: ``POST /v1/cache-versions`` on a real (SQLite) database.

FEATURE: OME-1307 (E14) - a run is seeded through the real chat route with a ``traceparent`` (a
live-cache hit, a stored fill and an opt-out bypass), then frozen.
INVARIANT (CV-D3): freezing twice gives one version. INVARIANT (CV-D2): a trace is visible to its
own account only.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import patch

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi.testclient import TestClient

from aigateway.core.cache_versions.models import (
    CacheCaptureEntry,
    CacheVersion,
    CacheVersionBlob,
    CacheVersionEntry,
    RequestCachePrompt,
)
from aigateway.core.request_cache.canonical import canonical_material
from aigateway.core.request_cache.models.request_cache_entry import RequestCacheEntry
from tests.unit.cache_versions.conftest import traceparent
from tests.unit.test_chat_global_cache_route import (
    _CHAT_PATH,
    _PATCH_TARGET,
    _arrange_account,
    _chat_body,
    _DispatchCounter,
)

_TRACE = "a1" * 16
_FREEZE = "/v1/cache-versions"
_HIT_BODY = _chat_body(messages=[{"role": "user", "content": "H: primes below 100?"}])
_STORED_BODY = _chat_body(messages=[{"role": "user", "content": "S: primes below 200?"}])
_BYPASS_BODY = _chat_body(
    messages=[{"role": "user", "content": "B: primes below 300?"}], cache={"use-cache": False}
)


def _run(client: Any, fn: Any) -> Any:
    return client.portal.call(fn)


def _seed_run(client: TestClient, credential_blobs: Any, *, trace_id: str = _TRACE) -> list[str]:
    """Trace ``trace_id``: H (hit), S (stored), B (bypass). Returns the three key hashes."""
    _arrange_account(client, credential_blobs)
    counter = _DispatchCounter()
    headers = {"traceparent": traceparent(trace_id)}
    with patch(_PATCH_TARGET, counter):
        # An UNTRACED call fills body H in the live cache and leaves no capture row.
        assert client.post(_CHAT_PATH, json=_HIT_BODY).headers["X-AIGW-Cache-Write"] == "stored"
        for body in (_HIT_BODY, _STORED_BODY, _BYPASS_BODY):
            assert client.post(_CHAT_PATH, json=body, headers=headers).status_code == 200

    async def _keys() -> list[str]:
        rows = await CacheCaptureEntry.filter(trace_id=trace_id).order_by("ordinal")
        return [str(r.key_hash) for r in rows]

    keys = _run(client, _keys)
    assert len(keys) == 3
    return keys


def _freeze(client: TestClient, trace_id: str = _TRACE, **kwargs: Any) -> Any:
    return client.post(_FREEZE, json={"trace_id": trace_id}, **kwargs)


def _decode(token: str, key: Ed25519PrivateKey) -> dict[str, Any]:
    return jwt.decode(token, key.public_key(), algorithms=["EdDSA"], audience="scoreboard")


def test_freeze_copies_full_request_and_response_for_each_call(
    freeze_client: TestClient, credential_blobs: Any
) -> None:
    hit_key, stored_key, bypass_key = _seed_run(freeze_client, credential_blobs)

    resp = _freeze(freeze_client)

    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert (body["call_count"], body["entry_count"], body["missing_count"]) == (3, 3, 0)
    assert body["coverage_status"] == "complete"
    assert set(body) == {
        "receipt",
        "cache_version_id",
        "entry_count",
        "call_count",
        "missing_count",
        "coverage_status",
        "archive_sha256",
    }

    async def _load() -> tuple[list[Any], dict[str, Any], Any]:
        entries = await CacheVersionEntry.all().order_by("first_ordinal").select_related("blob")
        live = {r.key_hash: r for r in await RequestCacheEntry.all()}
        inline = await CacheCaptureEntry.get(key_hash=bypass_key)
        return entries, live, inline

    entries, live, inline = _run(freeze_client, _load)
    assert [e.key_hash for e in entries] == [hit_key, stored_key, bypass_key]
    assert [e.first_ordinal for e in entries] == [0, 1, 2], "position in the trace, not the ordinal"
    for entry in entries:
        request = json.loads(entry.blob.request_json)
        # The request is the prompt material of the key: its sha256 is the key hash.
        assert hashlib.sha256(canonical_material(request).encode()).hexdigest() == entry.key_hash
        assert entry.blob_id == entry.blob.sha256
    for entry, key in zip(entries[:2], (hit_key, stored_key), strict=True):
        assert json.loads(entry.blob.response_json) == json.loads(live[key].response_json)
    assert json.loads(entries[2].blob.response_json) == json.loads(inline.response_json)


def test_freeze_is_idempotent_same_vid_same_sha(
    freeze_client: TestClient, credential_blobs: Any, signing_key: Ed25519PrivateKey
) -> None:
    _seed_run(freeze_client, credential_blobs)

    first, second = _freeze(freeze_client), _freeze(freeze_client)

    assert (first.status_code, second.status_code) == (201, 200)
    assert first.json()["cache_version_id"] == second.json()["cache_version_id"]
    assert first.json()["archive_sha256"] == second.json()["archive_sha256"]
    claims = [_decode(r.json()["receipt"], signing_key) for r in (first, second)]
    assert claims[0]["vid"] == claims[1]["vid"] == first.json()["cache_version_id"]
    assert claims[0]["sha"] == claims[1]["sha"] == first.json()["archive_sha256"]
    assert (claims[0]["n"], claims[0]["c"], claims[0]["cov"]) == (3, 3, "complete")
    assert claims[0]["tid"] == _TRACE
    assert _run(freeze_client, lambda: CacheVersion.all().count()) == 1


def test_freeze_of_other_accounts_trace_is_404(
    freeze_client: TestClient, credential_blobs: Any, provisioned_user_factory: Any
) -> None:
    _seed_run(freeze_client, credential_blobs)
    provisioned_user_factory("bob", "bobs-password-1")
    login = freeze_client.post(
        "/v1/auth/login", json={"username": "bob", "password": "bobs-password-1"}
    )
    assert login.status_code == 200, login.text
    bob = {"Authorization": f"Bearer {login.json()['token']}"}

    other = _freeze(freeze_client, headers=bob)

    assert other.status_code == 404
    assert other.json()["detail"]["code"] == "trace_not_captured"
    assert _run(freeze_client, lambda: CacheVersion.all().count()) == 0
    assert _freeze(freeze_client).status_code == 201


def test_freeze_of_unknown_trace_is_404_with_a_coded_body(freeze_client: TestClient) -> None:
    resp = _freeze(freeze_client, "0f" * 16)

    assert resp.status_code == 404
    assert resp.json()["detail"]["code"] == "trace_not_captured"
    assert "message" in resp.json()["detail"]


def test_freeze_counts_pruned_row_as_missing_partial(
    freeze_client: TestClient, credential_blobs: Any
) -> None:
    _, stored_key, _ = _seed_run(freeze_client, credential_blobs)

    async def _prune() -> None:
        await RequestCacheEntry.filter(key_hash=stored_key).delete()

    _run(freeze_client, _prune)

    resp = _freeze(freeze_client)

    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert (body["missing_count"], body["entry_count"], body["call_count"]) == (1, 2, 3)
    assert body["coverage_status"] == "partial"


def test_late_freeze_after_six_months_is_complete(
    freeze_client: TestClient, credential_blobs: Any
) -> None:
    # INVARIANT (CV-D4): no input expires. A freeze half a year late sees the same run.
    _seed_run(freeze_client, credential_blobs)
    old = datetime.now(UTC) - timedelta(days=183)

    async def _age() -> None:
        await CacheCaptureEntry.all().update(created_at=old)
        await RequestCachePrompt.all().update(created_at=old)
        await RequestCacheEntry.all().update(created_at=old)

    _run(freeze_client, _age)

    resp = _freeze(freeze_client)

    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert (body["call_count"], body["entry_count"], body["missing_count"]) == (3, 3, 0)
    assert body["coverage_status"] == "complete"


def test_an_expired_live_row_is_missing(freeze_client: TestClient, credential_blobs: Any) -> None:
    _, stored_key, _ = _seed_run(freeze_client, credential_blobs)

    async def _expire() -> None:
        past = datetime.now(UTC) - timedelta(seconds=5)
        await RequestCacheEntry.filter(key_hash=stored_key).update(expires_at=past)

    _run(freeze_client, _expire)

    body = _freeze(freeze_client).json()

    assert (body["missing_count"], body["coverage_status"]) == (1, "partial")


def test_freeze_shares_a_blob_between_two_versions(
    freeze_client: TestClient, credential_blobs: Any
) -> None:
    # Two traces that make the same call and get the same answer keep one blob row.
    _seed_run(freeze_client, credential_blobs)
    second_trace = "b2" * 16
    with patch(_PATCH_TARGET, _DispatchCounter()):
        freeze_client.post(
            _CHAT_PATH, json=_HIT_BODY, headers={"traceparent": traceparent(second_trace)}
        )

    assert _freeze(freeze_client).status_code == 201
    assert _freeze(freeze_client, second_trace).status_code == 201

    async def _counts() -> tuple[int, int, int]:
        return (
            await CacheVersion.all().count(),
            await CacheVersionEntry.all().count(),
            await CacheVersionBlob.all().count(),
        )

    assert _run(freeze_client, _counts) == (2, 4, 3)


_LIMITS = [
    pytest.param(("AIGW_CACHE_VERSION_MAX_ENTRIES", "2", "entries"), id="entry-cap"),
    pytest.param(("AIGW_CACHE_VERSION_MAX_ARCHIVE_BYTES", "64", "archive_bytes"), id="byte-cap"),
]


@pytest.fixture(params=_LIMITS)
def _limit(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> tuple[str, str, str]:
    name, value, limit = request.param
    monkeypatch.setenv(name, value)
    return name, value, limit


def test_freeze_too_large_413_and_nothing_written(
    _limit: tuple[str, str, str], freeze_client: TestClient, credential_blobs: Any
) -> None:
    _seed_run(freeze_client, credential_blobs)

    resp = _freeze(freeze_client)

    assert resp.status_code == 413, resp.text
    detail = resp.json()["detail"]
    assert detail["code"] == "cache_version_too_large"
    assert detail["limit"] == _limit[2]

    async def _counts() -> list[int]:
        return [await m.all().count() for m in (CacheVersion, CacheVersionEntry, CacheVersionBlob)]

    assert _run(freeze_client, _counts) == [0, 0, 0]
