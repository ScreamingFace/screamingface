"""Deterministic unstubbed backstops for the API-key writers (OME-307 D1/F3).

FEATURE: mandatory API-key validation before any credential write.
STORY: as an operator, when I create/replace an API-key connection, a bad key is rejected
before anything is persisted, and a good key is stored.

The third writer, the Profile API-key set, retired at OME-1209 Stage E3 with its tests: the
route answers 410 `legacy_profile_api_retired` (`test_legacy_profile_routes_retired.py`), and the
two Connection writers below are its successors.

Unlike the frozen route tests (which stub ``ApiKeyValidationService.validate`` via the
conftest allowlist), this module runs the REAL chain end to end:
route -> ``require_valid_api_key`` -> real ``ApiKeyValidationService`` -> real Anthropic
validator -> bounded ``ValidationHttpSession`` -> a deterministic mock transport. Only the
outermost HTTP transport is replaced, so no real network I/O occurs. This module is
deliberately kept OUT of the ``conftest`` compatibility allowlist.
"""

from __future__ import annotations

import json
import logging

import httpx
import pytest

from aigateway.core.oauth.store import credential_key_for
from aigateway.plugins.anthropic_provider.auth import (
    credential_service_for as anthropic_service_for,
)

_KEY_A = "sk-ant-api03-alpha-integration-key"
_KEY_B = "sk-ant-api03-beta-integration-key"


def _auth_ok() -> httpx.Response:
    return httpx.Response(200, json={"data": []})


def _readiness_ok() -> httpx.Response:
    return httpx.Response(200, json={"type": "message", "content": []})


def _auth_reject() -> httpx.Response:
    # 401 authentication_error is the evidence for INVALID; the route maps it to 422.
    return httpx.Response(
        401,
        json={"type": "error", "error": {"type": "authentication_error", "message": "bad key"}},
    )


class _Responder:
    """Serves queued upstream responses to the real validator's mock transport."""

    def __init__(self) -> None:
        self.queue: list[httpx.Response] = []
        self.requests: list[httpx.Request] = []

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return self.queue.pop(0)


@pytest.fixture
def anthropic_transport(monkeypatch) -> _Responder:
    responder = _Responder()

    def _factory(**_kwargs) -> httpx.MockTransport:
        # WHY: replace only the outermost production transport so the real validator,
        # session, bounding, and classifier all run against canned responses.
        return httpx.MockTransport(responder.handle)

    monkeypatch.setattr(
        "aigateway.core.api_key_validation_http.httpx.AsyncHTTPTransport",
        _factory,
    )
    return responder


def _create_connection(client, *, api_key: str, label: str):
    return client.post(
        "/v1/oauth/connections/api-key",
        json={"provider": "anthropic", "api_key": api_key, "label": label},
    )


def _connection_blob(credential_blobs, data: dict) -> dict | None:
    service = anthropic_service_for(credential_key_for(data["account_id"], data["id"]))
    raw = credential_blobs.read(service, "default")
    return None if raw is None else json.loads(raw)


# --- Writer 1: connection create ------------------------------------------------


def test_connection_create_valid_persists_after_real_validation(
    authenticated_client, anthropic_transport, credential_blobs
) -> None:
    anthropic_transport.queue = [_auth_ok(), _readiness_ok()]

    resp = _create_connection(authenticated_client, api_key=_KEY_A, label="work")

    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert data["status"] == "active"
    # Both stages of the real two-stage validation ran.
    assert [r.method for r in anthropic_transport.requests] == ["GET", "POST"]
    # The key was written to exactly the chat-read slot, encrypted.
    assert _connection_blob(credential_blobs, data) == {"auth_type": "api_key", "api_key": _KEY_A}
    assert _KEY_A not in resp.text


def test_connection_create_invalid_writes_nothing(
    authenticated_client, anthropic_transport
) -> None:
    anthropic_transport.queue = [_auth_reject()]

    resp = _create_connection(authenticated_client, api_key=_KEY_A, label="work")

    assert resp.status_code == 422
    assert resp.json()["detail"]["code"] == "api_key_invalid"
    # Auth-stage rejection short-circuits: readiness is never attempted.
    assert [r.method for r in anthropic_transport.requests] == ["GET"]
    # No connection row was created.
    listing = authenticated_client.get("/v1/oauth/connections")
    assert listing.json()["connections"] == []


def test_connection_create_transport_error_is_sanitized_and_writes_nothing(
    authenticated_client, anthropic_transport
) -> None:
    anthropic_transport.queue = [httpx.Response(200, content=b"not-json")]

    resp = _create_connection(authenticated_client, api_key=_KEY_A, label="work")

    assert resp.status_code == 503
    assert resp.json()["detail"] == {
        "code": "api_key_validation_unavailable",
        "provider": "anthropic",
        "message": "The provider could not complete validation. Try again later.",
        "state": "unavailable",
        "stage": "authentication",
        "retryable": True,
        "retry_after_seconds": None,
        "probe_model": "claude-haiku-4-5",
    }
    assert _KEY_A not in resp.text
    assert [r.method for r in anthropic_transport.requests] == ["GET"]
    assert authenticated_client.get("/v1/oauth/connections").json()["connections"] == []


_REFUSAL_LOGGER = "aigateway.routes.api_key_validation"


def _refusal_lines(caplog: pytest.LogCaptureFixture) -> list[tuple[int, str]]:
    """The (level, message) of every line the validation route logged."""
    return [
        (record.levelno, record.getMessage())
        for record in caplog.records
        if record.name == _REFUSAL_LOGGER
    ]


def test_an_unavailable_validation_logs_which_call_failed(
    authenticated_client, anthropic_transport, caplog: pytest.LogCaptureFixture
) -> None:
    """INVARIANT: a 503 on connecting a key names the failing call in the gateway log.

    The check is two outbound calls, and `unavailable` and `misconfigured` both answer 503. A
    client that flattens the response body leaves a bare 503 in the access log; a paid smoke
    press died on one with no way to tell which call failed (run 45538646440). Here the first
    call (authentication) returns a body that is not JSON.
    """
    anthropic_transport.queue = [httpx.Response(200, content=b"not-json")]

    with caplog.at_level(logging.INFO, logger=_REFUSAL_LOGGER):
        resp = _create_connection(authenticated_client, api_key=_KEY_A, label="work")

    assert resp.status_code == 503
    assert _refusal_lines(caplog) == [
        (
            logging.WARNING,
            "api_key_validation_refused provider=anthropic state=unavailable "
            "stage=authentication probe_model=claude-haiku-4-5 retryable=True",
        )
    ]


def test_a_rejected_key_logs_at_info_and_never_the_key_or_the_provider_text(
    authenticated_client, anthropic_transport, caplog: pytest.LogCaptureFixture
) -> None:
    """INVARIANT: the line holds gateway-authored values only.

    A bad key is the key owner's to fix, so it is INFO, not a warning for the operator. The
    provider's own words ("bad key") and the key itself must never reach the log.
    """
    anthropic_transport.queue = [_auth_reject()]

    with caplog.at_level(logging.DEBUG):
        resp = _create_connection(authenticated_client, api_key=_KEY_A, label="work")

    assert resp.status_code == 422
    assert _refusal_lines(caplog) == [
        (
            logging.INFO,
            "api_key_validation_refused provider=anthropic state=invalid "
            "stage=authentication probe_model=claude-haiku-4-5 retryable=False",
        )
    ]
    assert _KEY_A not in caplog.text
    assert "bad key" not in caplog.text


def test_a_valid_key_logs_no_refusal(
    authenticated_client, anthropic_transport, caplog: pytest.LogCaptureFixture
) -> None:
    """A key that passes both calls writes nothing: the line means a refusal, always."""
    anthropic_transport.queue = [_auth_ok(), _readiness_ok()]

    with caplog.at_level(logging.DEBUG, logger=_REFUSAL_LOGGER):
        resp = _create_connection(authenticated_client, api_key=_KEY_A, label="work")

    assert resp.status_code == 201, resp.text
    assert _refusal_lines(caplog) == []


# --- Writer 2: connection replace -----------------------------------------------


def test_connection_replace_valid_swaps_stored_key(
    authenticated_client, anthropic_transport, credential_blobs
) -> None:
    anthropic_transport.queue = [_auth_ok(), _readiness_ok()]
    created = _create_connection(authenticated_client, api_key=_KEY_A, label="work").json()

    anthropic_transport.queue = [_auth_ok(), _readiness_ok()]
    resp = authenticated_client.put(
        f"/v1/oauth/connections/{created['id']}/api-key",
        json={"api_key": _KEY_B},
    )

    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "active"
    assert [r.method for r in anthropic_transport.requests] == ["GET", "POST", "GET", "POST"]
    assert anthropic_transport.queue == []
    assert _connection_blob(credential_blobs, created) == {
        "auth_type": "api_key",
        "api_key": _KEY_B,
    }


def test_connection_replace_invalid_preserves_previous_key(
    authenticated_client, anthropic_transport, credential_blobs
) -> None:
    anthropic_transport.queue = [_auth_ok(), _readiness_ok()]
    created = _create_connection(authenticated_client, api_key=_KEY_A, label="work").json()

    anthropic_transport.queue = [_auth_reject()]
    resp = authenticated_client.put(
        f"/v1/oauth/connections/{created['id']}/api-key",
        json={"api_key": _KEY_B},
    )

    assert resp.status_code == 422
    assert resp.json()["detail"]["code"] == "api_key_invalid"
    assert [r.method for r in anthropic_transport.requests] == ["GET", "POST", "GET"]
    assert anthropic_transport.queue == []
    # The prior blob survives unchanged; the rejected key is never stored.
    assert _connection_blob(credential_blobs, created) == {
        "auth_type": "api_key",
        "api_key": _KEY_A,
    }
    connection = next(
        item
        for item in authenticated_client.get("/v1/oauth/connections").json()["connections"]
        if item["id"] == created["id"]
    )
    assert connection["status"] == "active"
    assert connection["label"] == "work"
    assert _KEY_B not in resp.text
