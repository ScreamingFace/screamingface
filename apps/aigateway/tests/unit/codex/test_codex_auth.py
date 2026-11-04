from __future__ import annotations

import base64
import json
import time
from typing import Any
from urllib.parse import parse_qs

import httpx
import pytest

from aigateway.core.errors import AuthError, CredentialNotFoundError
from aigateway.plugins.codex_provider.auth import (
    CodexOAuth,
    account_label_from_credentials,
    credential_service_for,
    exchange_authorization_code,
)
from aigateway.plugins.codex_provider.oauth_config import CODEX_CLIENT_ID, CODEX_TOKEN_URL


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


def _token_payload(account_id: str = "acct-1", **extra: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "sub": "sub-1",
        "exp": int(time.time()) + 3600,
        "https://api.openai.com/auth": {"chatgpt_account_id": account_id},
    }
    payload.update(extra)
    return payload


def _creds(**extra: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "access_token": _jwt(_token_payload()),
        "refresh_token": "refresh-1",
        "id_token": _jwt(_token_payload(email="user@example.com", name="User")),
        "expires_at_ms": int((time.time() + 3600) * 1000),
        "token_type": "Bearer",
        "account_id": "acct-1",
    }
    data.update(extra)
    return data


def _http_factory(transport: httpx.MockTransport):
    def factory():
        return httpx.AsyncClient(transport=transport, timeout=httpx.Timeout(5.0))

    return factory


def test_credential_service_uses_aigateway_namespace() -> None:
    assert credential_service_for("default") == "aigateway:codex:default"
    assert credential_service_for("work") == "aigateway:codex:work"


@pytest.mark.asyncio
async def test_missing_credential_raises() -> None:
    strategy = CodexOAuth(credential_name="default", credential_store=_FakeStore(payload=None))

    with pytest.raises(CredentialNotFoundError):
        await strategy.get_authorization_header()


@pytest.mark.asyncio
async def test_fresh_credential_yields_codex_headers() -> None:
    strategy = CodexOAuth(
        credential_name="default",
        credential_store=_FakeStore(payload=json.dumps(_creds())),
    )

    headers = await strategy.get_authorization_header()

    assert headers["Authorization"].startswith("Bearer ")
    assert headers["ChatGPT-Account-Id"] == "acct-1"


@pytest.mark.asyncio
async def test_unknown_expiry_does_not_force_refresh_loop() -> None:
    called = False

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal called
        called = True
        return httpx.Response(200, json={})

    strategy = CodexOAuth(
        credential_name="default",
        credential_store=_FakeStore(
            payload=json.dumps(
                _creds(
                    access_token="opaque-access-token",
                    id_token="opaque-id-token",
                    expires_at_ms=0,
                )
            )
        ),
        http_client_factory=_http_factory(httpx.MockTransport(handler)),
    )

    headers = await strategy.get_authorization_header()

    assert headers["Authorization"] == "Bearer opaque-access-token"
    assert called is False


@pytest.mark.asyncio
async def test_expired_credential_refreshes_with_scope_and_preserves_refresh_token() -> None:
    expired = _creds(expires_at_ms=int((time.time() - 60) * 1000))
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["content_type"] = request.headers["content-type"]
        captured["form"] = parse_qs(request.content.decode())
        return httpx.Response(
            200,
            json={
                "access_token": _jwt(_token_payload(account_id="acct-2")),
                "id_token": _jwt(_token_payload(account_id="acct-2", email="new@example.com")),
                "token_type": "Bearer",
            },
        )

    store = _FakeStore(payload=json.dumps(expired))
    strategy = CodexOAuth(
        credential_name="default",
        credential_store=store,
        http_client_factory=_http_factory(httpx.MockTransport(handler)),
    )

    headers = await strategy.get_authorization_header()

    assert captured["url"] == CODEX_TOKEN_URL
    assert captured["content_type"] == "application/x-www-form-urlencoded"
    assert captured["form"]["client_id"] == [CODEX_CLIENT_ID]
    assert captured["form"]["grant_type"] == ["refresh_token"]
    assert captured["form"]["refresh_token"] == ["refresh-1"]
    assert captured["form"]["scope"] == ["openid profile email"]
    assert headers["ChatGPT-Account-Id"] == "acct-2"
    written = json.loads(store.writes[0][2])
    assert written["refresh_token"] == "refresh-1"
    assert written["account_id"] == "acct-2"


@pytest.mark.asyncio
async def test_refresh_http_error_raises_auth_error() -> None:
    expired = _creds(expires_at_ms=int((time.time() - 60) * 1000))

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": "invalid_grant"})

    strategy = CodexOAuth(
        credential_name="default",
        credential_store=_FakeStore(payload=json.dumps(expired)),
        http_client_factory=_http_factory(httpx.MockTransport(handler)),
    )

    with pytest.raises(AuthError, match="401"):
        await strategy.get_authorization_header()


@pytest.mark.asyncio
async def test_exchange_authorization_code_uses_form_encoded_body() -> None:
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["content_type"] = request.headers["content-type"]
        captured["form"] = parse_qs(request.content.decode())
        return httpx.Response(
            200,
            json={
                "access_token": _jwt(_token_payload()),
                "refresh_token": "refresh-2",
                "id_token": _jwt(_token_payload(email="user@example.com")),
            },
        )

    creds = await exchange_authorization_code(
        "auth-code",
        "verifier",
        redirect_uri="http://localhost:9105/auth/callback",
        http_client_factory=_http_factory(httpx.MockTransport(handler)),
    )

    assert captured["url"] == CODEX_TOKEN_URL
    assert captured["content_type"] == "application/x-www-form-urlencoded"
    assert captured["form"]["grant_type"] == ["authorization_code"]
    assert captured["form"]["code"] == ["auth-code"]
    assert captured["form"]["redirect_uri"] == ["http://localhost:9105/auth/callback"]
    assert captured["form"]["client_id"] == [CODEX_CLIENT_ID]
    assert captured["form"]["code_verifier"] == ["verifier"]
    assert creds["refresh_token"] == "refresh-2"
    assert creds["account_id"] == "acct-1"


def test_account_label_prefers_email_then_name_then_account_id_then_subject() -> None:
    assert (
        account_label_from_credentials(
            _creds(id_token=_jwt(_token_payload(email="user@example.com", name="User")))
        )
        == "user@example.com"
    )
    assert (
        account_label_from_credentials(_creds(id_token=_jwt(_token_payload(name="Named User"))))
        == "Named User"
    )
    assert account_label_from_credentials(_creds(id_token=_jwt(_token_payload()))) == "acct-1"
    assert (
        account_label_from_credentials(
            _creds(
                access_token="opaque",
                id_token=_jwt({"sub": "subject-only", "exp": int(time.time()) + 3600}),
                account_id=None,
            )
        )
        == "subject-only"
    )
