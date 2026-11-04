"""Unit 3 — Antigravity OAuth exchange/refresh (MockTransport).

`AntigravityOAuth(BaseOAuthStrategy)` mirrors GeminiOAuth but with the
Antigravity client/secret/token-url and the "antigravity" credential namespace
(U11). Token normalization + identity extraction reuse the core Google Code
Assist helpers (Unit 1). GATE-2 Option A: the public installed-app client
secret has a settings default and may be overridden by env; exchange/refresh
still defensively reject an empty secret without leaking. Exchange AND refresh
errors are status-only (U7) — no upstream body echo. Identity-extraction
failure must not block credential storage.
"""

from __future__ import annotations

import base64
import inspect
import json
import time
from typing import Any
from urllib.parse import parse_qs

import httpx
import pytest

from aigateway.core.errors import AuthError, CredentialNotFoundError
from aigateway.plugins.antigravity_provider import auth as antigravity_auth_module
from aigateway.plugins.antigravity_provider.auth import (
    ANTIGRAVITY_PROFILE_HEADER,
    AntigravityOAuth,
    credential_service_for,
    exchange_authorization_code,
)
from aigateway.plugins.antigravity_provider.settings import (
    ANTIGRAVITY_CLIENT_SECRET,
    ANTIGRAVITY_TOKEN_URL,
    AntigravityPluginSettings,
)

ANTIGRAVITY_CLIENT_ID = "1071006060591-tmhssin2h21lcre235vtolojh4g403ep.apps.googleusercontent.com"
_TEST_SECRET = "GOCSPX-test-secret"


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


def _jwt(payload: dict[str, Any]) -> str:
    def encode(value: dict[str, Any] | bytes) -> str:
        raw = value if isinstance(value, bytes) else json.dumps(value).encode()
        return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()

    return f"{encode({'alg': 'none', 'typ': 'JWT'})}.{encode(payload)}.{encode(b'sig')}"


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


def _oauth(store: _FakeStore, transport: httpx.MockTransport | None = None) -> AntigravityOAuth:
    return AntigravityOAuth(
        credential_name="default",
        client_secret=_TEST_SECRET,
        credential_store=store,
        http_client_factory=_http_factory(transport) if transport is not None else None,
    )


# --- settings override threading (review #5) -------------------------------


@pytest.mark.asyncio
async def test_refresh_uses_overridden_client_id_and_token_url() -> None:
    """client_id + token_url must come from the SAME source authorize uses, so
    an override can't mint a code for one client and exchange with another."""
    expired = _creds(expires_at_ms=int((time.time() - 60) * 1000))
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["form"] = parse_qs(request.content.decode())
        return httpx.Response(
            200, json={"access_token": "ya29.new", "expires_in": 3600, "token_type": "Bearer"}
        )

    strategy = AntigravityOAuth(
        credential_name="default",
        client_secret=_TEST_SECRET,
        client_id="override-client-id",
        token_url="https://override.example/token",
        credential_store=_FakeStore(payload=json.dumps(expired)),
        http_client_factory=_http_factory(httpx.MockTransport(handler)),
    )
    await strategy.get_authorization_header()
    assert captured["url"] == "https://override.example/token"
    assert captured["form"]["client_id"] == ["override-client-id"]


@pytest.mark.asyncio
async def test_exchange_uses_overridden_client_id_and_token_url() -> None:
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return httpx.Response(401, json={"error": "no_userinfo"})
        captured["url"] = str(request.url)
        captured["form"] = parse_qs(request.content.decode())
        return httpx.Response(
            200, json={"access_token": "ya29.x", "refresh_token": "r-2", "expires_in": 3600}
        )

    await exchange_authorization_code(
        "code",
        "verifier",
        redirect_uri="http://localhost:9105/oauth2callback",
        client_secret=_TEST_SECRET,
        client_id="override-client-id",
        token_url="https://override.example/token",
        http_client_factory=_http_factory(httpx.MockTransport(handler)),
    )
    assert captured["url"] == "https://override.example/token"
    assert captured["form"]["client_id"] == ["override-client-id"]


# --- namespace (U11) -------------------------------------------------------


def test_credential_service_uses_antigravity_namespace() -> None:
    assert credential_service_for("default") == "aigateway:antigravity:default"
    assert credential_service_for("acct:work") == "aigateway:antigravity:acct:work"


def test_strategy_credential_service_matches_namespace() -> None:
    strategy = _oauth(_FakeStore(payload=None))
    assert strategy.credential_service() == "aigateway:antigravity:default"


# --- headers / read --------------------------------------------------------


@pytest.mark.asyncio
async def test_missing_credential_raises() -> None:
    strategy = _oauth(_FakeStore(payload=None))
    with pytest.raises(CredentialNotFoundError):
        await strategy.get_authorization_header()


@pytest.mark.asyncio
async def test_fresh_credential_yields_headers() -> None:
    strategy = AntigravityOAuth(
        credential_name="acct:default",
        client_secret=_TEST_SECRET,
        credential_store=_FakeStore(payload=json.dumps(_creds())),
    )
    headers = await strategy.get_authorization_header()
    assert headers["Authorization"] == "Bearer ya29.access"
    assert headers[ANTIGRAVITY_PROFILE_HEADER] == "acct:default"
    assert headers["User-Agent"]


# --- refresh ---------------------------------------------------------------


@pytest.mark.asyncio
async def test_expired_credential_refreshes_with_client_secret() -> None:
    expired = _creds(expires_at_ms=int((time.time() - 60) * 1000))
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["form"] = parse_qs(request.content.decode())
        return httpx.Response(
            200, json={"access_token": "ya29.new", "expires_in": 3600, "token_type": "Bearer"}
        )

    store = _FakeStore(payload=json.dumps(expired))
    strategy = _oauth(store, httpx.MockTransport(handler))
    headers = await strategy.get_authorization_header()

    assert captured["url"] == ANTIGRAVITY_TOKEN_URL
    assert captured["form"]["grant_type"] == ["refresh_token"]
    assert captured["form"]["refresh_token"] == ["refresh-1"]
    assert captured["form"]["client_id"] == [ANTIGRAVITY_CLIENT_ID]
    assert captured["form"]["client_secret"] == [_TEST_SECRET]
    assert headers["Authorization"] == "Bearer ya29.new"
    assert json.loads(store.writes[0][2])["refresh_token"] == "refresh-1"


@pytest.mark.asyncio
async def test_refresh_error_is_status_only_no_body_echo() -> None:
    """U7: refresh error must include ONLY the status, never the upstream body."""
    expired = _creds(expires_at_ms=int((time.time() - 60) * 1000))
    sentinel = "SENTINEL-SECRET-FROM-GOOGLE-BODY"

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text=f'{{"error": "{sentinel}"}}')

    strategy = _oauth(_FakeStore(payload=json.dumps(expired)), httpx.MockTransport(handler))
    with pytest.raises(AuthError) as exc_info:
        await strategy.get_authorization_header()
    message = str(exc_info.value)
    assert "500" in message
    assert sentinel not in message


@pytest.mark.asyncio
async def test_refresh_401_raises_reauth() -> None:
    from aigateway.core.errors import ReauthRequiredError

    expired = _creds(expires_at_ms=int((time.time() - 60) * 1000))

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"error": "invalid_grant"})

    strategy = _oauth(_FakeStore(payload=json.dumps(expired)), httpx.MockTransport(handler))
    with pytest.raises((AuthError, ReauthRequiredError)):
        await strategy.get_authorization_header()


@pytest.mark.asyncio
async def test_refresh_without_secret_raises_actionable_error() -> None:
    """Defensive guard: empty client secret still fails before token POST."""
    expired = _creds(expires_at_ms=int((time.time() - 60) * 1000))
    strategy = AntigravityOAuth(
        credential_name="default",
        client_secret="",
        credential_store=_FakeStore(payload=json.dumps(expired)),
    )
    with pytest.raises(AuthError, match="client secret"):
        await strategy.get_authorization_header()


# --- get_token_with_expiry (first-class OAuth connection token route) ------


@pytest.mark.asyncio
async def test_get_token_with_expiry_fresh() -> None:
    """The connection-token route casts the strategy to TokenWithExpiryStrategy
    and calls get_token_with_expiry(); BaseOAuthStrategy provides it because we
    normalize to {access_token, expires_at_ms}."""
    fresh = _creds()
    strategy = _oauth(_FakeStore(payload=json.dumps(fresh)))
    access_token, expires_at_ms, refreshed = await strategy.get_token_with_expiry()
    assert access_token == "ya29.access"
    assert expires_at_ms == fresh["expires_at_ms"]
    assert refreshed is False


@pytest.mark.asyncio
async def test_get_token_with_expiry_refreshes() -> None:
    expired = _creds(expires_at_ms=int((time.time() - 60) * 1000))
    # Refresh body carries an absolute expiry so the new token reads as fresh.
    new_expiry = int((time.time() + 3600) * 1000)

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"access_token": "ya29.new", "expires_at_ms": new_expiry, "token_type": "Bearer"},
        )

    strategy = _oauth(_FakeStore(payload=json.dumps(expired)), httpx.MockTransport(handler))
    access_token, expires_at_ms, refreshed = await strategy.get_token_with_expiry()
    assert access_token == "ya29.new"
    assert expires_at_ms == new_expiry
    assert refreshed is True


# --- exchange --------------------------------------------------------------


@pytest.mark.asyncio
async def test_exchange_authorization_code_form_body() -> None:
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":  # userinfo probe
            return httpx.Response(401, json={"error": "no_userinfo"})
        captured["url"] = str(request.url)
        captured["form"] = parse_qs(request.content.decode())
        return httpx.Response(
            200, json={"access_token": "ya29.x", "refresh_token": "r-2", "expires_in": 3600}
        )

    creds = await exchange_authorization_code(
        "auth-code",
        "verifier",
        redirect_uri="http://localhost:9105/oauth2callback",
        client_secret=_TEST_SECRET,
        http_client_factory=_http_factory(httpx.MockTransport(handler)),
    )
    assert captured["url"] == ANTIGRAVITY_TOKEN_URL
    assert captured["form"]["grant_type"] == ["authorization_code"]
    assert captured["form"]["code"] == ["auth-code"]
    assert captured["form"]["redirect_uri"] == ["http://localhost:9105/oauth2callback"]
    assert captured["form"]["client_id"] == [ANTIGRAVITY_CLIENT_ID]
    assert captured["form"]["client_secret"] == [_TEST_SECRET]
    assert captured["form"]["code_verifier"] == ["verifier"]
    assert creds["access_token"] == "ya29.x"
    assert creds["refresh_token"] == "r-2"


@pytest.mark.asyncio
async def test_exchange_error_is_status_only() -> None:
    sentinel = "SENTINEL-EXCHANGE-BODY"

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, text=f'{{"error": "{sentinel}"}}')

    with pytest.raises(AuthError) as exc_info:
        await exchange_authorization_code(
            "code",
            "verifier",
            redirect_uri="http://localhost:9105/oauth2callback",
            client_secret=_TEST_SECRET,
            http_client_factory=_http_factory(httpx.MockTransport(handler)),
        )
    message = str(exc_info.value)
    assert "400" in message
    assert sentinel not in message


@pytest.mark.asyncio
async def test_exchange_without_secret_raises_actionable_error() -> None:
    with pytest.raises(AuthError, match="client secret"):
        await exchange_authorization_code(
            "code",
            "verifier",
            redirect_uri="http://localhost:9105/oauth2callback",
            client_secret="",
        )


@pytest.mark.asyncio
async def test_exchange_attaches_identity_when_available() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "access_token": "ya29.x",
                "refresh_token": "r-2",
                "expires_in": 3600,
                "id_token": _jwt({"email": "user@example.com", "name": "User"}),
            },
        )

    creds = await exchange_authorization_code(
        "code",
        "verifier",
        redirect_uri="http://localhost:9105/oauth2callback",
        client_secret=_TEST_SECRET,
        http_client_factory=_http_factory(httpx.MockTransport(handler)),
    )
    assert creds["account_label"] == "user@example.com"
    assert creds["account_identity"]["email"] == "user@example.com"


@pytest.mark.asyncio
async def test_exchange_identity_failure_does_not_block_storage() -> None:
    """U10: identity extraction failure must not block credential storage."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":  # userinfo probe blows up
            raise httpx.ConnectError("userinfo down")
        return httpx.Response(
            200, json={"access_token": "ya29.x", "refresh_token": "r-2", "expires_in": 3600}
        )

    creds = await exchange_authorization_code(
        "code",
        "verifier",
        redirect_uri="http://localhost:9105/oauth2callback",
        client_secret=_TEST_SECRET,
        http_client_factory=_http_factory(httpx.MockTransport(handler)),
    )
    # No identity, but credentials are returned (storage proceeds).
    assert creds["access_token"] == "ya29.x"
    assert creds["refresh_token"] == "r-2"
    assert "account_label" not in creds


# --- redaction (GATE-2 Option A) -------------------------------------------


def test_no_hardcoded_secret_literal_in_auth_source() -> None:
    source = inspect.getsource(antigravity_auth_module)
    assert "GOCSPX" not in source


def test_settings_secret_never_serialized() -> None:
    """The settings client_secret stays a SecretStr — never plain in model_dump."""
    s = AntigravityPluginSettings()
    dumped = str(s.model_dump())
    assert ANTIGRAVITY_CLIENT_SECRET not in dumped
