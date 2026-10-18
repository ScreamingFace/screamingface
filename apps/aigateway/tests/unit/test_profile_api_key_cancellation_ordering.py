"""OME-307 Unit 5 — pending-OAuth cancellation ordering in ``set_profile_api_key``.

FEATURE: switching a profile from an in-flight OAuth login to a raw API key.
STORY: as a user who started an OAuth login for a profile and then tries an API key that
fails to persist (transient store error, or the request is cancelled), my original OAuth
login must still be completable — the failed API-key attempt must not strand the profile.

INVARIANT: ``set_profile_api_key`` must not irreversibly cancel pending OAuth state (pop
the pending entry, close the loopback listener) until the API-key credential+profile
publication COMMITS. Publication runs in one short transaction; a failed or cancelled
publication rolls back the credential and never reaches the pending-state teardown, so the
older OAuth flow remains usable and no orphan credential is left behind. Because Python
3.12 ``asyncio.CancelledError`` derives from ``BaseException``, the ordering — not a
best-effort ``except`` — is what guarantees this for both failures and cancellations.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import json
import threading

import httpx
import pytest

from aigateway.core.api_key_validation import (
    ApiKeyValidationResult,
    ApiKeyValidationStage,
    ApiKeyValidationState,
)
from aigateway.core.credential_names import credential_name_for
from aigateway.plugins.anthropic_provider.auth import credential_service_for

_API_KEY = "sk-ant-api03-cancellation-ordering-key"


class _ValidValidationService:
    async def validate(self, _plugin, _provider: str, _api_key: str) -> ApiKeyValidationResult:
        return ApiKeyValidationResult(
            ApiKeyValidationState.VALID,
            stage=ApiKeyValidationStage.READINESS,
        )


def _token_factory(token: str):
    async def token_handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "access_token": token,
                "refresh_token": f"refresh-{token}",
                "expires_in": 3600,
                "token_type": "Bearer",
            },
        )

    return lambda: httpx.AsyncClient(
        transport=httpx.MockTransport(token_handler), timeout=httpx.Timeout(5.0)
    )


def _start_pending_oauth(client) -> tuple[str, str]:
    """Start an OAuth flow for profile ``work`` and return (state, credential service)."""
    client.app.state.api_key_validation_service = _ValidValidationService()
    started = client.post("/v1/auth/anthropic/profiles", json={"name": "work"})
    assert started.status_code == 201
    account_id = client.get("/v1/auth/me").json()["id"]
    service = credential_service_for(credential_name_for(account_id, "work"))
    return started.json()["state"], service


def _complete_oauth(client, state: str, token: str) -> httpx.Response:
    client.app.state.anthropic_http_factory = _token_factory(token)
    return client.get(
        "/v1/auth/anthropic/callback",
        params={"code": "oauth-code", "state": state},
        follow_redirects=False,
    )


def test_failed_api_key_publication_preserves_pending_oauth_flow(
    authenticated_client,
    credential_blobs,
    monkeypatch,
) -> None:
    """Schedule: OAuth flow is pending; an API-key set fails at the durable index write
    (after the blob write, inside the transaction). The rollback+compensation must leave
    no orphan credential AND leave the OAuth flow intact so it can still complete."""
    state_oauth, service = _start_pending_oauth(authenticated_client)

    index = authenticated_client.app.state.profile_index
    original_upsert = index.upsert

    async def _boom(_profile, **_kwargs):
        # INVARIANT: fail at the real durable boundary (index publication), after the
        # credential blob has been written inside the transaction. The pending profile is
        # observed-existing, so the caller passes require_present=True (OME-307 Unit 3).
        raise RuntimeError("simulated profile-index write failure")

    monkeypatch.setattr(index, "upsert", _boom)
    # The publication raises inside the transaction, so nothing commits. (The TestClient
    # re-raises an unhandled server error rather than returning a synthesized 500.)
    with pytest.raises(RuntimeError, match="simulated profile-index write failure"):
        authenticated_client.put(
            "/v1/auth/anthropic/profiles/work/api-key",
            json={"api_key": _API_KEY},
        )
    monkeypatch.setattr(index, "upsert", original_upsert)

    # No orphan credential survived the rolled-back, non-committed publication.
    assert credential_blobs.read(service, "default") is None
    # The profile was never re-authenticated as api_key; it is still the pending OAuth one.
    profile = authenticated_client.get("/v1/auth/anthropic/profiles/work").json()
    assert profile["state"] == "pending"

    # The pending OAuth flow remains usable and completes with its own credentials.
    callback = _complete_oauth(authenticated_client, state_oauth, "oauth-after-failure")
    assert callback.status_code == 200
    authenticated = authenticated_client.get("/v1/auth/anthropic/profiles/work").json()
    assert authenticated["state"] == "authenticated"
    assert authenticated["auth_type"] == "oauth"
    blob = json.loads(credential_blobs.read(service, "default"))
    assert blob["access_token"] == "oauth-after-failure"


def test_cancelled_api_key_publication_preserves_pending_oauth_flow(
    authenticated_client,
    credential_blobs,
    monkeypatch,
) -> None:
    """Same ordering guarantee under cancellation: ``asyncio.CancelledError`` is a
    ``BaseException`` in 3.12, so only performing the pending-state teardown AFTER commit
    keeps the OAuth flow alive when the publication task is cancelled mid-transaction."""
    state_oauth, service = _start_pending_oauth(authenticated_client)

    index = authenticated_client.app.state.profile_index
    original_upsert = index.upsert
    reached = threading.Event()

    async def _cancel(_profile, **_kwargs):
        reached.set()
        raise asyncio.CancelledError

    monkeypatch.setattr(index, "upsert", _cancel)
    # The sync TestClient surfaces an in-request asyncio.CancelledError as the
    # concurrent.futures variant once it crosses the blocking-portal boundary.
    with pytest.raises(concurrent.futures.CancelledError):
        authenticated_client.put(
            "/v1/auth/anthropic/profiles/work/api-key",
            json={"api_key": _API_KEY},
        )
    assert reached.is_set(), "publication never reached the durable index write"
    monkeypatch.setattr(index, "upsert", original_upsert)

    # Cancellation left no orphan credential (invariant: cancellation cannot orphan a blob).
    assert credential_blobs.read(service, "default") is None
    profile = authenticated_client.get("/v1/auth/anthropic/profiles/work").json()
    assert profile["state"] == "pending"

    # The OAuth flow survived the cancelled API-key attempt and still completes.
    callback = _complete_oauth(authenticated_client, state_oauth, "oauth-after-cancel")
    assert callback.status_code == 200
    authenticated = authenticated_client.get("/v1/auth/anthropic/profiles/work").json()
    assert authenticated["state"] == "authenticated"
    assert authenticated["auth_type"] == "oauth"
    blob = json.loads(credential_blobs.read(service, "default"))
    assert blob["access_token"] == "oauth-after-cancel"
