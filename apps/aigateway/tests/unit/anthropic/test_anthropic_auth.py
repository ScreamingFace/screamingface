from __future__ import annotations

import json
import time
from typing import Any

import httpx
import pytest

from aigateway.core.errors import AuthError, CredentialNotFoundError
from aigateway.plugins.anthropic_provider.auth import (
    AnthropicOAuth,
    credential_service_for,
    exchange_authorization_code,
)
from aigateway.plugins.anthropic_provider.settings import AnthropicPluginSettings


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


def _wrap(creds: dict) -> str:
    """Token payload as stored in aigateway:anthropic:<name>."""
    return json.dumps(creds)


def _fresh_creds(expires_in_ms: int = 3_600_000) -> dict:
    return {
        "access_token": "tok-fresh",
        "refresh_token": "rt-1",
        "expires_at_ms": int(time.time() * 1000) + expires_in_ms,
        "token_type": "Bearer",
    }


def _http_factory(transport: httpx.MockTransport):
    def factory():
        return httpx.AsyncClient(transport=transport, timeout=httpx.Timeout(5.0))

    return factory


def _settings(**overrides: Any) -> AnthropicPluginSettings:
    return AnthropicPluginSettings(**overrides)


@pytest.mark.asyncio
async def test_credential_service_uses_aigateway_namespace() -> None:
    """Profiles are stored under aigateway:anthropic:<name>."""
    assert credential_service_for("default") == "aigateway:anthropic:default"
    assert credential_service_for("work") == "aigateway:anthropic:work"


@pytest.mark.asyncio
async def test_missing_credential_raises() -> None:
    strat = AnthropicOAuth(
        credential_name="default",
        credential_store=_FakeStore(payload=None),
        settings=_settings(),
    )
    with pytest.raises(CredentialNotFoundError):
        await strat.get_authorization_header()


@pytest.mark.asyncio
async def test_malformed_json_raises_auth_error() -> None:
    strat = AnthropicOAuth(
        credential_name="default",
        credential_store=_FakeStore(payload="{not json"),
        settings=_settings(),
    )
    with pytest.raises(AuthError, match="not valid JSON"):
        await strat.get_authorization_header()


@pytest.mark.asyncio
async def test_missing_required_field_raises() -> None:
    strat = AnthropicOAuth(
        credential_name="default",
        credential_store=_FakeStore(payload=json.dumps({"access_token": "t"})),
        settings=_settings(),
    )
    with pytest.raises(AuthError, match="missing required field"):
        await strat.get_authorization_header()


@pytest.mark.asyncio
async def test_fresh_credential_yields_three_headers() -> None:
    creds = _fresh_creds()
    strat = AnthropicOAuth(
        credential_name="default",
        credential_store=_FakeStore(payload=_wrap(creds)),
        settings=_settings(),
    )
    headers = await strat.get_authorization_header()
    assert headers["Authorization"] == "Bearer tok-fresh"
    assert headers["anthropic-version"] == "2023-06-01"
    assert "oauth-2025-04-20" in headers["anthropic-beta"]


@pytest.mark.asyncio
async def test_expired_credential_triggers_refresh() -> None:
    expired = _fresh_creds(expires_in_ms=-1000)
    expired["access_token"] = "tok-old"

    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["body"] = json.loads(request.content.decode())
        return httpx.Response(
            200,
            json={
                "access_token": "tok-new",
                "refresh_token": "rt-2",
                "expires_in": 3600,
            },
        )

    store = _FakeStore(payload=_wrap(expired))
    settings = _settings()
    strat = AnthropicOAuth(
        credential_name="default",
        credential_store=store,
        http_client_factory=_http_factory(httpx.MockTransport(handler)),
        settings=settings,
    )
    headers = await strat.get_authorization_header()

    assert headers["Authorization"] == "Bearer tok-new"
    assert captured["url"] == settings.token_url
    assert captured["body"]["grant_type"] == "refresh_token"
    assert captured["body"]["refresh_token"] == "rt-1"
    assert captured["body"]["scope"] == " ".join(settings.refresh_scopes)

    assert len(store.writes) == 1
    written = json.loads(store.writes[0][2])
    assert written["access_token"] == "tok-new"
    assert written["refresh_token"] == "rt-2"


@pytest.mark.asyncio
async def test_refresh_uses_injected_settings() -> None:
    expired = _fresh_creds(expires_in_ms=-1000)
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["body"] = json.loads(request.content.decode())
        return httpx.Response(
            200,
            json={
                "access_token": "tok-custom",
                "refresh_token": "rt-custom",
                "expires_in": 3600,
            },
        )

    settings = _settings(
        token_url="https://custom.example/oauth/token",
        client_id="client-custom",
        refresh_scopes=["scope:custom"],
        api_version="2024-01-01",
        beta="beta-custom",
        keychain_account="account-custom",
    )
    store = _FakeStore(payload=_wrap(expired))
    strat = AnthropicOAuth(
        credential_name="default",
        credential_store=store,
        http_client_factory=_http_factory(httpx.MockTransport(handler)),
        settings=settings,
    )

    headers = await strat.get_authorization_header()

    assert captured["url"] == "https://custom.example/oauth/token"
    assert captured["body"]["client_id"] == "client-custom"
    assert captured["body"]["scope"] == "scope:custom"
    assert headers["Authorization"] == "Bearer tok-custom"
    assert headers["anthropic-version"] == "2024-01-01"
    assert headers["anthropic-beta"] == "beta-custom"
    assert store.writes[0][1] == "account-custom"


@pytest.mark.asyncio
async def test_refresh_endpoint_401_raises() -> None:
    expired = _fresh_creds(expires_in_ms=-1000)

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": "invalid_grant"})

    strat = AnthropicOAuth(
        credential_name="default",
        credential_store=_FakeStore(payload=_wrap(expired)),
        http_client_factory=_http_factory(httpx.MockTransport(handler)),
        settings=_settings(),
    )
    with pytest.raises(AuthError, match="401"):
        await strat.get_authorization_header()


@pytest.mark.asyncio
async def test_exchange_authorization_code_uses_injected_settings() -> None:
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["body"] = json.loads(request.content.decode())
        return httpx.Response(
            200,
            json={
                "access_token": "tok-exchanged",
                "refresh_token": "rt-exchanged",
                "expires_in": 3600,
            },
        )

    settings = _settings(
        token_url="https://custom.example/oauth/token",
        client_id="client-custom",
    )

    creds = await exchange_authorization_code(
        "auth-code",
        "verifier",
        redirect_uri="http://localhost:9105/callback",
        state="state-1",
        http_client_factory=_http_factory(httpx.MockTransport(handler)),
        settings=settings,
    )

    assert captured["url"] == "https://custom.example/oauth/token"
    assert captured["body"]["client_id"] == "client-custom"
    assert captured["body"]["code"] == "auth-code"
    assert captured["body"]["code_verifier"] == "verifier"
    assert captured["body"]["redirect_uri"] == "http://localhost:9105/callback"
    assert captured["body"]["state"] == "state-1"
    assert creds["access_token"] == "tok-exchanged"
    assert creds["refresh_token"] == "rt-exchanged"


@pytest.mark.asyncio
async def test_invalidate_drops_cache() -> None:
    creds = _fresh_creds()
    strat = AnthropicOAuth(
        credential_name="default",
        credential_store=_FakeStore(payload=_wrap(creds)),
        settings=_settings(),
    )
    await strat.get_authorization_header()
    assert strat._cached is not None
    await strat.invalidate()
    assert strat._cached is None


@pytest.mark.asyncio
async def test_persist_credentials_persists_and_caches() -> None:
    """persist_credentials() writes to store + populates cache after OAuth callback."""
    store = _FakeStore(payload=None)
    strat = AnthropicOAuth(
        credential_name="default",
        credential_store=store,
        settings=_settings(),
    )
    fresh = _fresh_creds()
    await strat.persist_credentials(fresh)

    headers = await strat.get_authorization_header()
    assert headers["Authorization"] == f"Bearer {fresh['access_token']}"
    assert len(store.writes) == 1
    written = json.loads(store.writes[0][2])
    assert written["access_token"] == fresh["access_token"]


@pytest.mark.asyncio
async def test_credential_service_constant() -> None:
    """Don't change the persisted credential blob namespace."""
    strat = AnthropicOAuth(
        credential_name="work", credential_store=_FakeStore(), settings=_settings()
    )
    assert strat.credential_service() == "aigateway:anthropic:work"
    assert strat.credential_account() == "default"
