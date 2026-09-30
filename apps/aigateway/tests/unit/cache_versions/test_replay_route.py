"""CV-16, CV-17, CV-18 (route row), RP-5: the chat route with a replay grant, on a real database.

FEATURE: OME-1307 (E14) - a call that carries `X-AIGW-Cache-Replay` is answered from the frozen
version when the version holds its key, and is refused with 403 when the grant is bad.
INVARIANT (CV-E4): a refused grant never falls through to the live path.
INVARIANT (CV-H4): a version hit reads no credential and dispatches nothing.
INVARIANT (RP-D1): a grant reused by another account is refused (reason `subject`).
"""

from __future__ import annotations

import json
import logging
from typing import Any, cast
from unittest.mock import patch
from uuid import UUID

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi.testclient import TestClient

from aigateway.core.cache_versions.models import CacheVersionEntry
from aigateway.core.credential_blob.store import ORMStore
from aigateway.core.request_cache.models import RequestCacheEntry
from aigateway.routes.chat_cache_stage import KEY_PREFIX_LENGTH
from tests.unit.cache_versions.conftest import BODY_NEW, BODY_S, frozen_version, mint_grant
from tests.unit.test_chat_global_cache_route import _CHAT_PATH, _PATCH_TARGET, _DispatchCounter

_GRANT_HEADER = "X-AIGW-Cache-Replay"


def _send(
    client: TestClient, body: dict[str, Any], grant: str, **headers: str
) -> tuple[Any, _DispatchCounter]:
    """POST ``body`` with the grant; return the response and the provider dispatch counter."""
    counter = _DispatchCounter()
    with patch(_PATCH_TARGET, counter):
        resp = client.post(_CHAT_PATH, json=body, headers={_GRANT_HEADER: grant, **headers})
    return resp, counter


def test_invalid_grant_is_403_and_never_falls_through(
    replay_client: TestClient, credential_blobs: Any
) -> None:
    version = frozen_version(replay_client, credential_blobs)
    forged = mint_grant(Ed25519PrivateKey.generate(), sub="admin", vid=version)

    # WHY BODY_NEW: no live cache row holds it, so a fall-through would DISPATCH. That makes the
    # empty dispatch counter below a real check and not a live-cache accident.
    resp, counter = _send(replay_client, BODY_NEW, forged)

    assert resp.status_code == 403, resp.text
    detail = resp.json()["detail"]
    assert detail["code"] == "replay_grant_invalid"
    assert detail["reason"] == "signature"
    assert detail["message"]
    assert counter.calls == [], "a refused grant must not reach the provider"


def test_gateway_rejects_grant_reused_by_other_subject(
    replay_client: TestClient,
    credential_blobs: Any,
    grant_key: Ed25519PrivateKey,
    provisioned_user_factory: Any,
) -> None:
    version = frozen_version(replay_client, credential_blobs)
    grant = mint_grant(grant_key, sub="admin", vid=version)
    provisioned_user_factory("bruno", "brunos-password-1")
    login = replay_client.post(
        "/v1/auth/login", json={"username": "bruno", "password": "brunos-password-1"}
    )
    assert login.status_code == 200, login.text
    bruno = {"Authorization": f"Bearer {login.json()['token']}"}

    refused, refused_counter = _send(replay_client, BODY_NEW, grant, **bruno)
    control, _ = _send(replay_client, BODY_S, grant)

    assert refused.status_code == 403, refused.text
    assert refused.json()["detail"]["reason"] == "subject"
    assert refused_counter.calls == []
    assert control.status_code != 403, "positive control: the grant works for its own subject"


def test_cloudflare_headers_subject_is_the_verified_email(
    replay_client: TestClient, credential_blobs: Any, grant_key: Ed25519PrivateKey
) -> None:
    # STORY (D5): production runs `cloudflare_headers`. The account username is the lowercased
    # verified `X-User-Email`, and the grant `sub` carries that same email.
    version: UUID = frozen_version(replay_client, credential_blobs)
    # `current_account` reads the mode per request, so flipping it on the built app takes the
    # production-shaped path (exemplar: tests/unit/auth/test_cloudflare_identity.py).
    cast(Any, replay_client.app).state.settings.auth_mode = "cloudflare_headers"
    ana = {"X-User-Email": "Ana@Example.org"}

    own, _ = _send(
        replay_client, BODY_S, mint_grant(grant_key, sub="ana@example.org", vid=version), **ana
    )
    other, other_counter = _send(
        replay_client, BODY_NEW, mint_grant(grant_key, sub="bruno@example.org", vid=version), **ana
    )

    assert own.status_code != 403, own.text
    assert other.status_code == 403, other.text
    assert other.json()["detail"]["reason"] == "subject"
    assert other_counter.calls == []


def _second_call(client: Any, version: UUID) -> tuple[str, dict[str, Any]]:
    """The key hash and the frozen answer of the second call of the trace (call S)."""

    async def _load() -> tuple[str, dict[str, Any]]:
        entry = (
            await CacheVersionEntry.filter(version_id=version)
            .order_by("first_ordinal")
            .select_related("blob")
        )[1]
        return entry.key_hash, json.loads(entry.blob.response_json)

    return client.portal.call(_load)


def _delete_live_cache(client: Any) -> None:
    async def _delete() -> None:
        await RequestCacheEntry.all().delete()

    client.portal.call(_delete)


def test_valid_grant_hit_serves_version_without_provider_call(
    replay_client: TestClient, credential_blobs: Any, grant_key: Ed25519PrivateKey
) -> None:
    version = frozen_version(replay_client, credential_blobs)
    key_hash, frozen_answer = _second_call(replay_client, version)
    # WHY: the live cache is emptied, so only the frozen version can answer S.
    _delete_live_cache(replay_client)
    grant = mint_grant(grant_key, sub="admin", vid=version)
    services: list[str] = []
    original = ORMStore.read

    async def _recording(self: Any, service: str, account: str) -> Any:
        services.append(service)
        return await original(self, service, account)

    with patch.object(ORMStore, "read", _recording):
        resp, counter = _send(replay_client, BODY_S, grant)

    assert resp.status_code == 200, resp.text
    assert resp.json()["choices"] == frozen_answer["choices"]
    assert counter.calls == [], "a version hit dispatches nothing"
    prefix = key_hash[:KEY_PREFIX_LENGTH]
    assert resp.headers["X-AIGW-Cache-Version"] == "hit"
    assert resp.headers["Cache-Status"] == f'aigateway; hit; detail=version; key="{prefix}"'
    assert resp.headers["X-AIGW-Cache"] == "hit"
    assert resp.headers["X-AIGW-Cache-Key"] == prefix
    # INVARIANT (CV-H4): a version hit touches `credential_blobs` not at all: no provider
    # credential and no profile index.
    assert services == [], f"a version hit read a credential row: {services}"

    # Control: a call that is not in the version resolves its credential target, which reads the
    # profile index. Without this the empty list above could be a wrong recording seam.
    with patch.object(ORMStore, "read", _recording):
        miss, _ = _send(replay_client, BODY_NEW, grant)
    assert miss.status_code == 200, miss.text
    assert services, "the control read nothing, so the recording seam proves nothing"


def test_valid_grant_miss_falls_through_and_marks_miss(
    replay_client: TestClient, credential_blobs: Any, grant_key: Ed25519PrivateKey
) -> None:
    version = frozen_version(replay_client, credential_blobs)
    grant = mint_grant(grant_key, sub="admin", vid=version)

    resp, counter = _send(replay_client, BODY_NEW, grant)

    assert resp.status_code == 200, resp.text
    assert len(counter.calls) == 1, "a miss runs live, once"
    assert resp.headers["X-AIGW-Cache"] == "miss"
    assert resp.headers["X-AIGW-Cache-Write"] == "stored"
    assert resp.headers["X-AIGW-Cache-Version"] == "miss"
    assert "detail=version" not in resp.headers.get("Cache-Status", "")


class _BrokenLookup:
    async def version_exists(self, version_id: UUID) -> bool:
        return True

    async def find(self, version_id: UUID, key_hash: str) -> Any:
        raise RuntimeError("SELECT ... prompt text in the driver message")


def test_a_lookup_error_is_a_miss_with_a_type_only_warning(
    replay_client: TestClient,
    credential_blobs: Any,
    grant_key: Ed25519PrivateKey,
    caplog: pytest.LogCaptureFixture,
) -> None:
    # INVARIANT: the version is never an availability dependency. The call runs live, the miss
    # header keeps it visible, and the log names the exception type only.
    version = frozen_version(replay_client, credential_blobs)
    cast(Any, replay_client.app).state.cache_version_lookup = _BrokenLookup()

    with caplog.at_level(logging.WARNING, logger="aigateway.routes.chat_replay_stage"):
        resp, counter = _send(
            replay_client, BODY_NEW, mint_grant(grant_key, sub="admin", vid=version)
        )

    assert resp.status_code == 200, resp.text
    assert resp.headers["X-AIGW-Cache-Version"] == "miss"
    assert "RuntimeError" in caplog.text
    assert "prompt text" not in caplog.text
    assert len(counter.calls) == 1, "a lookup failure runs the call live"


def test_the_counters_follow_the_outcomes(
    replay_client: TestClient, credential_blobs: Any, grant_key: Ed25519PrivateKey
) -> None:
    version = frozen_version(replay_client, credential_blobs)
    grant = mint_grant(grant_key, sub="admin", vid=version)
    forged = mint_grant(Ed25519PrivateKey.generate(), sub="admin", vid=version)

    _send(replay_client, BODY_S, grant)
    _send(replay_client, BODY_NEW, grant)
    _send(replay_client, BODY_NEW, forged)

    counts = cast(Any, replay_client.app).state.capture_stats.replay_lookups
    assert dict(counts) == {"hit": 1, "miss": 1, "invalid_grant": 1}


def test_a_blank_grant_header_is_a_normal_call(
    replay_client: TestClient, credential_blobs: Any
) -> None:
    frozen_version(replay_client, credential_blobs)

    resp, counter = _send(replay_client, BODY_NEW, "   ")

    assert resp.status_code == 200, resp.text
    assert "X-AIGW-Cache-Version" not in resp.headers
    assert len(counter.calls) == 1


def test_no_subject_check_when_auth_is_disabled(
    replay_client: TestClient, credential_blobs: Any, grant_key: Ed25519PrivateKey
) -> None:
    # CV-19 at the route: `disabled` is a dev/local fallback and keeps its behaviour (RP-D8).
    version = frozen_version(replay_client, credential_blobs)
    cast(Any, replay_client.app).state.settings.auth_mode = "disabled"

    resp, _ = _send(
        replay_client, BODY_S, mint_grant(grant_key, sub="someone-else@example.org", vid=version)
    )

    assert resp.status_code == 200, resp.text
    assert resp.headers["X-AIGW-Cache-Version"] == "hit"
