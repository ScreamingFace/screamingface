"""Support: the C2b status codes and error bodies of ``POST /v1/cache-versions``.

FEATURE: OME-1307 (E14) - the kill switch answers 503 before anything is read, and a bad body is
refused by the app's redacting 422 handler.
INVARIANT: capture keeps running when freeze is off (a missing signing key must not stop capture).
"""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi.testclient import TestClient

from aigateway.core.cache_versions.models import CacheCaptureEntry
from tests.unit.cache_versions.conftest import login_admin, raw_private_b64, traceparent
from tests.unit.test_chat_global_cache_route import (
    _CHAT_PATH,
    _PATCH_TARGET,
    _arrange_account,
    _chat_body,
    _DispatchCounter,
)

_FREEZE = "/v1/cache-versions"
_TRACE = "a1" * 16


def _state(client: TestClient) -> Any:
    app: Any = client.app
    return app.state


@pytest.fixture
def _key_but_flag_off_env(monkeypatch: pytest.MonkeyPatch, signing_key: Ed25519PrivateKey) -> None:
    # The default of AIGW_CACHE_VERSIONS_ENABLED is off. A key is set, so ONLY the flag differs.
    monkeypatch.setenv("AIGATEWAY_RECEIPT_SIGNING_KEY", raw_private_b64(signing_key))


def test_flag_off_answers_503_capture_disabled(_key_but_flag_off_env: None, client: Any) -> None:
    login_admin(client)

    resp = client.post(_FREEZE, json={"trace_id": _TRACE})

    assert resp.status_code == 503
    assert resp.json()["detail"]["code"] == "capture_disabled"
    assert _state(client).cache_version_freezer is None


def test_flag_on_without_a_signing_key_answers_503_and_capture_still_runs(
    capture_client: TestClient, credential_blobs: Any
) -> None:
    _arrange_account(capture_client, credential_blobs)
    with patch(_PATCH_TARGET, _DispatchCounter()):
        capture_client.post(
            _CHAT_PATH, json=_chat_body(), headers={"traceparent": traceparent(_TRACE)}
        )

    resp = capture_client.post(_FREEZE, json={"trace_id": _TRACE})

    assert resp.status_code == 503
    assert resp.json()["detail"]["code"] == "capture_disabled"

    async def _count() -> int:
        return await CacheCaptureEntry.filter(trace_id=_TRACE).count()

    client: Any = capture_client
    assert client.portal.call(_count) == 1


_BAD_BODIES = [
    pytest.param({"trace_id": "AB" * 16}, id="upper-case"),
    pytest.param({"trace_id": "ab" * 15}, id="short"),
    pytest.param({"trace_id": "ab" * 17}, id="long"),
    pytest.param({"trace_id": "ab" * 16, "extra": 1}, id="extra-field"),
    pytest.param({}, id="missing"),
]


@pytest.mark.parametrize("payload", _BAD_BODIES)
def test_a_bad_body_is_422_and_never_echoed(
    payload: dict[str, Any], freeze_client: TestClient
) -> None:
    resp = freeze_client.post(_FREEZE, json=payload)

    assert resp.status_code == 422
    # The redacting handler drops the echoed `input` of every error.
    assert all("input" not in error for error in resp.json()["detail"])


def test_freeze_needs_a_login(_freeze_env: None, client: TestClient) -> None:
    resp = client.post(_FREEZE, json={"trace_id": _TRACE})

    assert resp.status_code == 401
