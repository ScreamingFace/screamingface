from __future__ import annotations

import inspect
import json
import time
from typing import Any
from urllib.parse import parse_qs

import httpx
import pytest

from aigateway.core.errors import AuthError, CredentialNotFoundError
from aigateway.plugins.gemini_provider import auth as gemini_auth_module
from aigateway.plugins.gemini_provider.auth import (
    GEMINI_PROFILE_HEADER,
    GeminiOAuth,
    credential_service_for,
    exchange_authorization_code,
)
from aigateway.plugins.gemini_provider.oauth_config import (
    GEMINI_CLIENT_ID,
    GEMINI_CLIENT_SECRET,
    GEMINI_TOKEN_URL,
)


class _FakeStore:
    def __init__(self, payload: str | None = None) -> None:
        self.payload = payload
        self.writes: list[tuple[str, str, str]] = []

    async def read(self, service: str, account: str) -> str | None:
        return self.payload

    async def write(self, service: str, account: str, value: str) -> None:
        self.writes.append((service, account, value))
        self.payload = value

    async def delete(self, service: str, account: str) -> None:
        self.payload = None

    async def mutate(self, service: str, account: str, mutator) -> None:
        next_value = mutator(await self.read(service, account))
        if next_value is None:
            await self.delete(service, account)
        else:
            await self.write(service, account, next_value)


def _creds(**extra: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "access_token": "ya29.access",
        "refresh_token": "refresh-1",
        "expires_at_ms": int((time.time() + 3600) * 1000),
        "token_type": "Bearer",
    }
    data.update(extra)
    return data


def _http_factory(transport: httpx.MockTransport):
    def factory():
        return httpx.AsyncClient(transport=transport, timeout=httpx.Timeout(5.0))

    return factory


def test_credential_service_uses_aigateway_namespace() -> None:
    assert credential_service_for("default") == "aigateway:gemini:default"
    assert credential_service_for("acct:work") == "aigateway:gemini:acct:work"


def test_auth_module_does_not_read_gemini_cli_oauth_file() -> None:
    source = inspect.getsource(gemini_auth_module)
    assert "oauth_creds.json" not in source
    assert "~/.gemini" not in source


@pytest.mark.asyncio
async def test_missing_credential_raises() -> None:
    strategy = GeminiOAuth(credential_name="default", credential_store=_FakeStore(payload=None))

    with pytest.raises(CredentialNotFoundError):
        await strategy.get_authorization_header()


@pytest.mark.asyncio
async def test_fresh_credential_yields_code_assist_headers() -> None:
    strategy = GeminiOAuth(
        credential_name="acct:default",
        credential_store=_FakeStore(payload=json.dumps(_creds())),
    )

    headers = await strategy.get_authorization_header()

    assert headers["Authorization"] == "Bearer ya29.access"
    assert headers[GEMINI_PROFILE_HEADER] == "acct:default"
    assert headers["User-Agent"].startswith("GeminiCLI/0.42.0/")


@pytest.mark.asyncio
async def test_expired_credential_refreshes_and_preserves_refresh_token() -> None:
    expired = _creds(expires_at_ms=int((time.time() - 60) * 1000))
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["content_type"] = request.headers["content-type"]
        captured["form"] = parse_qs(request.content.decode())
        return httpx.Response(
            200,
            json={
                "access_token": "ya29.new",
                "expires_in": 3600,
                "token_type": "Bearer",
            },
        )

    store = _FakeStore(payload=json.dumps(expired))
    strategy = GeminiOAuth(
        credential_name="default",
        credential_store=store,
        http_client_factory=_http_factory(httpx.MockTransport(handler)),
    )

    headers = await strategy.get_authorization_header()

    assert captured["url"] == GEMINI_TOKEN_URL
    assert captured["content_type"] == "application/x-www-form-urlencoded"
    assert captured["form"]["client_id"] == [GEMINI_CLIENT_ID]
    assert captured["form"]["client_secret"] == [GEMINI_CLIENT_SECRET]
    assert captured["form"]["grant_type"] == ["refresh_token"]
    assert captured["form"]["refresh_token"] == ["refresh-1"]
    assert headers["Authorization"] == "Bearer ya29.new"
    written = json.loads(store.writes[0][2])
    assert written["refresh_token"] == "refresh-1"


@pytest.mark.asyncio
async def test_gemini_refresh_normalizes_fresh_expiry_from_expires_in_over_stale_previous() -> None:
    """Regression lock (shared core, review round 2 finding A): a refresh body
    carrying only `expires_in` over an EXPIRED previous must persist a FRESH
    future expiry, not the stale absolute one — otherwise the new token reads
    as already-expired and the strategy refresh-loops. Locks gemini alongside
    antigravity on the shared `expires_at_ms` helper."""
    stale = int((time.time() - 3600) * 1000)
    now_ms = int(time.time() * 1000)
    expired = _creds(expires_at_ms=stale)

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"access_token": "ya29.new", "expires_in": 3600, "token_type": "Bearer"},
        )

    store = _FakeStore(payload=json.dumps(expired))
    strategy = GeminiOAuth(
        credential_name="default",
        credential_store=store,
        http_client_factory=_http_factory(httpx.MockTransport(handler)),
    )

    await strategy.get_authorization_header()

    written = json.loads(store.writes[0][2])
    assert written["expires_at_ms"] > now_ms
    assert written["expires_at_ms"] > stale + 60_000


@pytest.mark.asyncio
async def test_refresh_401_raises_auth_error() -> None:
    expired = _creds(expires_at_ms=int((time.time() - 60) * 1000))

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": "invalid_grant"})

    strategy = GeminiOAuth(
        credential_name="default",
        credential_store=_FakeStore(payload=json.dumps(expired)),
        http_client_factory=_http_factory(httpx.MockTransport(handler)),
    )

    with pytest.raises(AuthError, match="401"):
        await strategy.get_authorization_header()


@pytest.mark.asyncio
async def test_exchange_authorization_code_uses_google_form_body() -> None:
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return httpx.Response(401, json={"error": "no_userinfo_in_this_test"})
        captured["url"] = str(request.url)
        captured["content_type"] = request.headers["content-type"]
        captured["form"] = parse_qs(request.content.decode())
        return httpx.Response(
            200,
            json={
                "access_token": "ya29.exchange",
                "refresh_token": "refresh-2",
                "expires_in": 3600,
            },
        )

    creds = await exchange_authorization_code(
        "auth-code",
        "verifier",
        redirect_uri="http://localhost:9105/oauth2callback",
        http_client_factory=_http_factory(httpx.MockTransport(handler)),
    )

    assert captured["url"] == GEMINI_TOKEN_URL
    assert captured["content_type"] == "application/x-www-form-urlencoded"
    assert captured["form"]["grant_type"] == ["authorization_code"]
    assert captured["form"]["code"] == ["auth-code"]
    assert captured["form"]["redirect_uri"] == ["http://localhost:9105/oauth2callback"]
    assert captured["form"]["client_id"] == [GEMINI_CLIENT_ID]
    assert captured["form"]["client_secret"] == [GEMINI_CLIENT_SECRET]
    assert captured["form"]["code_verifier"] == ["verifier"]
    assert creds["access_token"] == "ya29.exchange"
    assert creds["refresh_token"] == "refresh-2"


# Identity extraction and account-label behavior are owned by core now and
# tested in tests/unit/test_google_code_assist.py (the single source of truth
# after the findings-U5 extraction). gemini imports those helpers directly from
# core, so there is no gemini-level re-export left to wiring-test here.
