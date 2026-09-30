"""Support: what a replay call leaves in the capture table (OME-1307, GW-replay).

FEATURE: OME-1307 (E14) - a replay run is itself a traced run, so it can be frozen again.
INVARIANT (CV-D8): a `version_hit` row keeps the served body inline, because no live cache row
holds it.
INVARIANT (CV-3): a refused grant records an `error` row, like every failed call.
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import patch

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi.testclient import TestClient

from aigateway.core.cache_versions.models import CacheCaptureEntry
from aigateway.core.request_cache.models import RequestCacheEntry
from tests.unit.cache_versions.conftest import (
    BODY_NEW,
    BODY_S,
    frozen_version,
    mint_grant,
    traceparent,
)
from tests.unit.test_chat_global_cache_route import _CHAT_PATH, _PATCH_TARGET, _DispatchCounter

_REPLAY_TRACE = "c3" * 16


def _client(client: TestClient) -> Any:
    """The client typed as ``Any``: Starlette's ``portal`` is Optional in its stubs."""
    return client


def _rows(client: Any, trace_id: str) -> list[CacheCaptureEntry]:
    async def _load() -> list[CacheCaptureEntry]:
        return await CacheCaptureEntry.filter(trace_id=trace_id).order_by("ordinal")

    return client.portal.call(_load)


def _replay(client: TestClient, body: dict[str, Any], grant: str) -> Any:
    headers = {"X-AIGW-Cache-Replay": grant, "traceparent": traceparent(_REPLAY_TRACE)}
    with patch(_PATCH_TARGET, _DispatchCounter()):
        return client.post(_CHAT_PATH, json=body, headers=headers)


def test_version_hit_is_captured_with_inline_body(
    replay_client: TestClient, credential_blobs: Any, grant_key: Ed25519PrivateKey
) -> None:
    version = frozen_version(replay_client, credential_blobs)

    async def _empty_live_cache() -> None:
        await RequestCacheEntry.all().delete()

    _client(replay_client).portal.call(_empty_live_cache)
    resp = _replay(replay_client, BODY_S, mint_grant(grant_key, sub="admin", vid=version))

    assert resp.headers["X-AIGW-Cache-Version"] == "hit"
    (row,) = _rows(replay_client, _REPLAY_TRACE)
    assert row.outcome == "version_hit"
    served = {k: v for k, v in resp.json().items() if k != "_aigw"}
    assert json.loads(row.response_json) == served

    frozen_again = replay_client.post("/v1/cache-versions", json={"trace_id": _REPLAY_TRACE})
    assert frozen_again.status_code == 201, frozen_again.text
    assert frozen_again.json()["coverage_status"] == "complete"
    assert frozen_again.json()["missing_count"] == 0


def test_a_refused_grant_is_captured_as_an_error_row(
    replay_client: TestClient, credential_blobs: Any
) -> None:
    version = frozen_version(replay_client, credential_blobs)
    forged = mint_grant(Ed25519PrivateKey.generate(), sub="admin", vid=version)

    resp = _replay(replay_client, BODY_NEW, forged)

    assert resp.status_code == 403
    (row,) = _rows(replay_client, _REPLAY_TRACE)
    assert row.outcome == "error"
    assert row.response_json is None


def test_a_traced_miss_is_captured_like_a_live_call(
    replay_client: TestClient, credential_blobs: Any, grant_key: Ed25519PrivateKey
) -> None:
    version = frozen_version(replay_client, credential_blobs)

    resp = _replay(replay_client, BODY_NEW, mint_grant(grant_key, sub="admin", vid=version))

    assert resp.headers["X-AIGW-Cache-Version"] == "miss"
    (row,) = _rows(replay_client, _REPLAY_TRACE)
    assert row.outcome == "stored"
