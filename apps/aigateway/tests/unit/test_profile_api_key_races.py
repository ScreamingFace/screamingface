from __future__ import annotations

import asyncio
import json
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

import httpx

from aigateway.core.api_key_validation import (
    ApiKeyValidationResult,
    ApiKeyValidationStage,
    ApiKeyValidationState,
)
from aigateway.core.credential_names import credential_name_for
from aigateway.plugins.anthropic_provider.auth import credential_service_for

_API_KEY = "sk-ant-api03-profile-race-key"


@dataclass
class _ValidValidationService:
    async def validate(self, _plugin, _provider: str, _api_key: str) -> ApiKeyValidationResult:
        return ApiKeyValidationResult(
            ApiKeyValidationState.VALID,
            stage=ApiKeyValidationStage.READINESS,
        )


def test_profile_api_key_wins_over_older_inflight_oauth_callback(
    authenticated_client,
    credential_blobs,
) -> None:
    exchange_started = threading.Event()
    release_exchange = threading.Event()

    async def token_handler(_request: httpx.Request) -> httpx.Response:
        exchange_started.set()
        if not await asyncio.to_thread(release_exchange.wait, 5):
            raise TimeoutError("OAuth exchange was not released")
        return httpx.Response(
            200,
            json={
                "access_token": "oauth-access-token",
                "refresh_token": "oauth-refresh-token",
                "expires_in": 3600,
                "token_type": "Bearer",
            },
        )

    authenticated_client.app.state.anthropic_http_factory = lambda: httpx.AsyncClient(
        transport=httpx.MockTransport(token_handler),
        timeout=httpx.Timeout(5.0),
    )
    authenticated_client.app.state.api_key_validation_service = _ValidValidationService()
    started = authenticated_client.post(
        "/v1/auth/anthropic/profiles",
        json={"name": "work"},
    )
    assert started.status_code == 201

    with ThreadPoolExecutor(max_workers=1) as executor:
        callback = executor.submit(
            authenticated_client.get,
            "/v1/auth/anthropic/callback",
            params={"code": "oauth-code", "state": started.json()["state"]},
            follow_redirects=False,
        )
        assert exchange_started.wait(5), "callback never reached token exchange"

        api_key_response = authenticated_client.put(
            "/v1/auth/anthropic/profiles/work/api-key",
            json={"api_key": _API_KEY},
        )
        release_exchange.set()
        callback_response = callback.result(timeout=5)

    assert api_key_response.status_code == 200
    assert callback_response.status_code == 409
    assert callback_response.json()["detail"]["code"] == "profile_auth_conflict"
    profile = authenticated_client.get("/v1/auth/anthropic/profiles/work").json()
    # INVARIANT: the later explicit API-key choice wins as one coherent profile/blob state.
    assert profile["auth_type"] == "api_key"
    assert profile["state"] == "authenticated"
    account_id = authenticated_client.get("/v1/auth/me").json()["id"]
    service = credential_service_for(credential_name_for(account_id, "work"))
    blob = credential_blobs.read(service, "default")
    assert json.loads(blob) == {"auth_type": "api_key", "api_key": _API_KEY}
