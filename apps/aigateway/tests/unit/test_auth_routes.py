from __future__ import annotations

import asyncio
import base64
import json
import logging
import threading
import time
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import cast
from urllib.parse import parse_qs, urlparse
from uuid import uuid4

import httpx
import pytest
from fastapi import HTTPException
from tortoise import Tortoise
from tortoise.exceptions import IntegrityError, OperationalError

from aigateway.core.credential_blob.store import CredentialBlobMutationConflict
from aigateway.core.credential_names import profile_id_for
from aigateway.core.oauth.store import OAuthConnectionStore, credential_key_for
from aigateway.core.pending_auth import PendingAuthEntry
from aigateway.core.plugin_base import OAuthCodeExchangeRequest, OAuthConfig
from aigateway.core.profile_models import Profile, ProfileState
from aigateway.db import init_db
from aigateway.plugins.codex_provider.oauth_config import CODEX_CLIENT_ID
from aigateway.routes.auth import (
    _close_loopback_callback,
    _complete_oauth_for_app,
    _connection_label,
    _expire_loopback_callback,
    _handle_loopback_callback,
    _http_response,
    _loopback_host_allowed,
    close_loopback_callbacks,
)


@pytest.fixture
def client_with_index(authenticated_client, credential_blobs):
    return authenticated_client, credential_blobs


@contextmanager
def _server_errors_as_responses(client) -> Iterator[None]:
    transport = getattr(client, "_transport")
    previous = transport.raise_server_exceptions
    transport.raise_server_exceptions = False
    try:
        yield
    finally:
        transport.raise_server_exceptions = previous


def _account_id(client) -> str:
    return client.get("/v1/auth/me").json()["id"]


def _pending_profile(account_id: str, provider: str, name: str) -> Profile:
    return Profile(
        id=profile_id_for(account_id, provider, name),
        account_id=account_id,
        provider=provider,
        name=name,
        state=ProfileState.PENDING,
    )


def _open_flow(
    client, provider: str, name: str, *, redirect_uri: str | None = None
) -> tuple[str, str]:
    # FEATURE: OME-1209 Stage E3b — every pending flow is a native Connection flow. A PENDING
    # compat document of the same name is seeded first, so the callback's D14 mirror flips it as
    # the retired Profile start left it; returns the flow's `state` and `connection_id`.
    client.portal.call(
        client.app.state.profile_index.upsert,
        _pending_profile(_account_id(client), provider, name),
    )
    body: dict[str, str] = {"provider": provider, "label": name}
    if redirect_uri is not None:
        body["redirect_uri"] = redirect_uri
    started = client.post("/v1/oauth/connections", json=body)
    assert started.status_code == 201, started.text
    return started.json()["state"], started.json()["connection_id"]


def _indexed_profile(client, provider: str, name: str) -> dict:
    # WHY: the retired `GET .../profiles/{name}` returned this exact projection of the index row.
    profile = client.portal.call(
        client.app.state.profile_index.get, _account_id(client), provider, name
    )
    assert profile is not None
    return profile.model_dump(mode="json")


def test_start_oauth_returns_authorize_url(client_with_index) -> None:
    client, _ = client_with_index
    account_id = _account_id(client)
    resp = client.post("/v1/oauth/connections", json={"provider": "anthropic", "label": "work"})
    assert resp.status_code == 201
    body = resp.json()
    parsed = urlparse(body["authorize_url"])
    connection = client.get(f"/v1/oauth/connections/{body['connection_id']}").json()
    assert (connection["account_id"], connection["provider"], connection["label"]) == (
        account_id,
        "anthropic",
        "work",
    )
    assert parsed.scheme == "https"
    assert parsed.netloc == "claude.com"
    assert parsed.path == "/cai/oauth/authorize"
    assert "state=" in body["authorize_url"]
    assert "code_challenge=" in body["authorize_url"]
    assert "code_challenge_method=S256" in body["authorize_url"]
    # Required by the public Claude Code OAuth app to surface the consent screen
    assert "code=true" in body["authorize_url"]
    # Claude subscription OAuth must request the user scope set, not
    # org:create_api_key, otherwise the flow is routed toward Console/API-key
    # billing rather than Claude subscription capacity.
    assert "user%3Asessions%3Aclaude_code" in body["authorize_url"]
    assert "org%3Acreate_api_key" not in body["authorize_url"]
    # redirect_uri must be http://localhost:*/callback (not 127.0.0.1 and not
    # a per-provider path) — the public Claude Code OAuth client only allows
    # this canonical shape.
    assert "redirect_uri=http%3A%2F%2Flocalhost%3A" in body["authorize_url"]
    assert "%2Fcallback&" in body["authorize_url"]


def test_start_oauth_invalid_host_falls_back_to_app_port(client_with_index) -> None:
    client, _ = client_with_index

    resp = client.post(
        "/v1/oauth/connections",
        json={"provider": "anthropic", "label": "fallback-port"},
        headers={"host": "127.0.0.1:not-a-port"},
    )

    assert resp.status_code == 201
    query = parse_qs(urlparse(resp.json()["authorize_url"]).query)
    assert query["redirect_uri"] == [f"http://localhost:{client.app.state.settings.port}/callback"]


@pytest.mark.parametrize(
    "redirect_uri",
    [
        "https://localhost:9105/callback",
        "http://example.com:9105/callback",
        "http://localhost:9105/oauth2callback",
        "http://localhost:9105/callback?x=1",
        "http://localhost:9105/callback#frag",
        "http://user:pass@localhost:9105/callback",
        "http://localhost/callback",
        "http://localhost:0/callback",
    ],
)
def test_start_oauth_rejects_invalid_redirect_uri_override(
    client_with_index,
    redirect_uri: str,
) -> None:
    client, _ = client_with_index

    resp = client.post(
        "/v1/oauth/connections",
        json={"provider": "anthropic", "label": "bad-redirect", "redirect_uri": redirect_uri},
    )

    assert resp.status_code == 400
    assert resp.json()["detail"]["code"] == "invalid_redirect_uri"


@pytest.mark.parametrize("port", [1455, 1457])
def test_start_oauth_codex_accepts_configured_redirect_override_port(
    client_with_index,
    port: int,
) -> None:
    client, _ = client_with_index
    redirect_uri = f"http://localhost:{port}/auth/callback"

    resp = client.post(
        "/v1/oauth/connections",
        json={"provider": "codex", "label": f"codex-{port}", "redirect_uri": redirect_uri},
    )

    assert resp.status_code == 201
    query = parse_qs(urlparse(resp.json()["authorize_url"]).query)
    assert query["redirect_uri"] == [redirect_uri]


def test_start_oauth_for_codex_returns_openai_authorize_url(client_with_index) -> None:
    client, _ = client_with_index
    account_id = _account_id(client)

    resp = client.post("/v1/oauth/connections", json={"provider": "codex", "label": "work"})

    assert resp.status_code == 201
    body = resp.json()
    connection = client.get(f"/v1/oauth/connections/{body['connection_id']}").json()
    assert (connection["account_id"], connection["provider"], connection["label"]) == (
        account_id,
        "codex",
        "work",
    )
    parsed = urlparse(body["authorize_url"])
    query = parse_qs(parsed.query)
    assert parsed.scheme == "https"
    assert parsed.netloc == "auth.openai.com"
    assert parsed.path == "/oauth/authorize"
    assert query["client_id"] == [CODEX_CLIENT_ID]
    assert query["response_type"] == ["code"]
    assert query["code_challenge_method"] == ["S256"]
    assert query["redirect_uri"][0] in {
        "http://localhost:1455/auth/callback",
        "http://localhost:1457/auth/callback",
    }
    assert "offline_access" in query["scope"][0].split()
    assert "api.connectors.invoke" in query["scope"][0].split()
    assert query["id_token_add_organizations"] == ["true"]
    assert query["codex_cli_simplified_flow"] == ["true"]
    assert query["originator"] == ["codex_cli_rs"]


def test_start_oauth_public_url_overrides_loopback_redirect_ports_for_codex(
    client_with_index,
) -> None:
    client, _ = client_with_index
    client.app.state.settings.public_url = "https://aigateway.example.com"

    resp = client.post("/v1/oauth/connections", json={"provider": "codex", "label": "public-codex"})

    assert resp.status_code == 201
    query = parse_qs(urlparse(resp.json()["authorize_url"]).query)
    assert query["redirect_uri"] == ["https://aigateway.example.com/auth/callback"]


def test_start_oauth_loopback_unavailable_returns_503(client_with_index, monkeypatch) -> None:
    client, _ = client_with_index

    async def fail_start_server(*_args, **_kwargs):
        raise OSError("port unavailable")

    monkeypatch.setattr(asyncio, "start_server", fail_start_server)

    resp = client.post(
        "/v1/oauth/connections", json={"provider": "codex", "label": "loopback-busy"}
    )

    assert resp.status_code == 503
    assert resp.json()["detail"]["code"] == "oauth_loopback_unavailable"


def test_top_level_callback_dispatches_by_state(client_with_index) -> None:
    """The /callback route looks up the provider from the pending-auth
    state, so the same path serves every provider — matching what Claude Code
    accepts as a redirect_uri."""
    client, _ = client_with_index
    client.app.state.anthropic_http_factory = _mock_token_factory()

    state, _ = _open_flow(client, "anthropic", "topcb")

    auth_header = client.headers.pop("Authorization")
    try:
        resp = client.get(
            "/callback",
            params={"code": "auth-code-top", "state": state},
            follow_redirects=False,
        )
    finally:
        client.headers["Authorization"] = auth_header
    assert resp.status_code == 200
    prof = _indexed_profile(client, "anthropic", "topcb")
    assert prof["state"] == "authenticated"


def test_oauth2callback_alias_completes_auth(client_with_index) -> None:
    client, _ = client_with_index
    client.app.state.anthropic_http_factory = _mock_token_factory()

    state, _ = _open_flow(client, "anthropic", "oauth2cb")

    auth_header = client.headers.pop("Authorization")
    try:
        resp = client.get(
            "/oauth2callback",
            params={"code": "auth-code-oauth2", "state": state},
            follow_redirects=False,
        )
    finally:
        client.headers["Authorization"] = auth_header
    assert resp.status_code == 200
    prof = _indexed_profile(client, "anthropic", "oauth2cb")
    assert prof["state"] == "authenticated"


def test_top_level_callback_unknown_state_400(client_with_index) -> None:
    client, _ = client_with_index
    auth_header = client.headers.pop("Authorization")
    try:
        resp = client.get("/callback", params={"code": "x", "state": "never-issued"})
    finally:
        client.headers["Authorization"] = auth_header
    assert resp.status_code == 400


class _RecordingStrategy:
    def __init__(self) -> None:
        self.creds: dict | None = None
        self.deleted = False
        self.refreshed = False

    async def get_authorization_header(self) -> dict[str, str]:
        return {}

    async def persist_credentials(self, creds: dict) -> None:
        self.creds = creds

    async def delete_credentials(self) -> None:
        self.deleted = True

    async def refresh_credentials(self) -> None:
        self.refreshed = True

    def credential_service(self) -> str:
        return "aigateway:generic:test"

    def credential_account(self) -> str:
        return "default"


class _GenericOAuthPlugin:
    custom_llm_provider = "generic"

    def __init__(self) -> None:
        self.strategy = _RecordingStrategy()
        self.exchange_request: OAuthCodeExchangeRequest | None = None

    def register_models(self) -> list:
        return []

    def oauth_config(self) -> OAuthConfig:
        return OAuthConfig(
            authorize_url="https://example.test/oauth/authorize",
            token_url="https://example.test/oauth/token",
            client_id="client-id",
            scopes=["scope-a", "scope-b"],
            redirect_path="/callback",
            extra_authorize_params={"extra": "1"},
        )

    def oauth_strategy_for(self, _profile_name: str, **_kwargs) -> _RecordingStrategy:
        return self.strategy

    def requires_oauth_connection_label(self) -> bool:
        return False

    async def exchange_oauth_code(self, request: OAuthCodeExchangeRequest) -> dict:
        self.exchange_request = request
        return {
            "access_token": "generic-token",
            "refresh_token": "generic-refresh",
            "expires_at_ms": 9999999999999,
            "token_type": "Bearer",
        }

    def account_label_from_credentials(self, _credentials: dict) -> str | None:
        return None


class _DelayedOAuthPlugin(_GenericOAuthPlugin):
    def __init__(self) -> None:
        super().__init__()
        self.exchange_count = 0

    async def exchange_oauth_code(self, request: OAuthCodeExchangeRequest) -> dict:
        self.exchange_count += 1
        await asyncio.sleep(0.01)
        return await super().exchange_oauth_code(request)


class _ExplodingOAuthPlugin(_GenericOAuthPlugin):
    async def exchange_oauth_code(self, _request: OAuthCodeExchangeRequest) -> dict:
        raise RuntimeError("<script>bad</script>")


class _FakeReader:
    def __init__(self, data: bytes | None = None, exc: Exception | None = None) -> None:
        self.data = data
        self.exc = exc

    async def readuntil(self, _separator: bytes) -> bytes:
        if self.exc is not None:
            raise self.exc
        assert self.data is not None
        return self.data


class _FakeWriter:
    def __init__(self) -> None:
        self.writes: list[bytes] = []
        self.closed = False

    @property
    def response(self) -> bytes:
        return b"".join(self.writes)

    def write(self, data: bytes) -> None:
        self.writes.append(data)

    async def drain(self) -> None:
        pass

    def close(self) -> None:
        self.closed = True

    async def wait_closed(self) -> None:
        pass


class _FakeServer:
    def __init__(self) -> None:
        self.closed = False
        self.waited = False

    def close(self) -> None:
        self.closed = True

    async def wait_closed(self) -> None:
        self.waited = True


def _as_stream_reader(reader: _FakeReader) -> asyncio.StreamReader:
    return cast(asyncio.StreamReader, reader)


def _as_stream_writer(writer: _FakeWriter) -> asyncio.StreamWriter:
    return cast(asyncio.StreamWriter, writer)


def _raw_loopback_request(target: str, *, method: str = "GET", host: str = "localhost") -> bytes:
    return f"{method} {target} HTTP/1.1\r\nHost: {host}\r\n\r\n".encode("ascii")


def _close_testclient_tortoise_connections(client) -> None:
    # Some tests call async route internals directly on pytest's loop after
    # TestClient has opened Tortoise connections on its portal loop.
    client.portal.call(Tortoise.close_connections)


async def _move_tortoise_to_pytest_loop(client, credential_blobs) -> None:
    _close_testclient_tortoise_connections(client)
    await init_db(f"sqlite://{credential_blobs.db_path}")


async def _seed_pending_flow(
    client,
    account_id: str,
    provider: str,
    name: str,
    state: str,
) -> str:
    # WHY no HTTP start: these tests drive the loopback callback on pytest's loop. Mirror what the
    # native start leaves — the pending Connection, the pending entry naming it — plus a PENDING
    # compat document of the same name for the D14 mirror; returns the Connection id.
    connection_id = uuid4()
    await OAuthConnectionStore().create_pending(
        account_id=account_id, provider=provider, label=name, connection_id=connection_id
    )
    await client.app.state.profile_index.upsert(_pending_profile(account_id, provider, name))
    client.app.state.pending_auth.put(
        state,
        PendingAuthEntry(
            account_id=account_id,
            provider=provider,
            profile_name=name,
            code_verifier="verifier",
            redirect_uri="http://localhost:1455/callback",
            connection_id=str(connection_id),
            requested_label=name,
        ),
    )
    return str(connection_id)


@pytest.mark.parametrize(
    ("host", "allowed"),
    [
        (None, False),
        ("", False),
        ("localhost", True),
        ("localhost.", True),
        ("127.0.0.1:1455", True),
        ("[::1]:1455", True),
        ("192.168.1.10:1455", False),
        ("example.com", False),
        ("[::1", False),
    ],
)
def test_loopback_host_allowed_accepts_only_loopback(host, allowed) -> None:
    assert _loopback_host_allowed(host) is allowed


def test_loopback_http_response_serializes_body_and_headers() -> None:
    response = _http_response(418, "teapot", content_type="text/plain")

    assert response.startswith(b"HTTP/1.1 418 Internal Server Error\r\n")
    assert b"content-type: text/plain; charset=utf-8\r\n" in response
    assert b"content-length: 6\r\n" in response
    assert response.endswith(b"\r\n\r\nteapot")


@pytest.mark.asyncio
async def test_expire_loopback_callback_closes_registered_server(client_with_index) -> None:
    client, _ = client_with_index
    state = "expires-now"
    server = _FakeServer()
    client.app.state.loopback_oauth_callbacks = {state: server}

    await _expire_loopback_callback(client.app, state, 0)

    assert server.closed is True
    assert server.waited is True
    assert state not in client.app.state.loopback_oauth_callbacks


@pytest.mark.asyncio
async def test_close_loopback_callback_cancels_expiry_task(client_with_index) -> None:
    client, _ = client_with_index
    state = "state-to-close"
    server = _FakeServer()
    task = asyncio.create_task(asyncio.sleep(600))
    client.app.state.loopback_oauth_callbacks = {state: server}
    client.app.state.loopback_oauth_callback_tasks = {state: task}

    await _close_loopback_callback(client.app, state)

    assert server.closed is True
    assert server.waited is True
    assert task.done() is True
    assert client.app.state.loopback_oauth_callbacks == {}
    assert client.app.state.loopback_oauth_callback_tasks == {}


@pytest.mark.asyncio
async def test_close_loopback_callbacks_cleans_all_servers_and_tasks(client_with_index) -> None:
    client, _ = client_with_index
    servers = {"state-1": _FakeServer(), "state-2": _FakeServer()}
    tasks = {
        "state-1": asyncio.create_task(asyncio.sleep(600)),
        "state-2": asyncio.create_task(asyncio.sleep(600)),
    }
    client.app.state.loopback_oauth_callbacks = servers.copy()
    client.app.state.loopback_oauth_callback_tasks = tasks.copy()

    await close_loopback_callbacks(client.app)

    assert all(server.closed and server.waited for server in servers.values())
    assert all(task.done() for task in tasks.values())
    assert client.app.state.loopback_oauth_callbacks == {}
    assert client.app.state.loopback_oauth_callback_tasks == {}


def test_connection_label_uses_plugin_account_label_fallback() -> None:
    class _LabelPlugin:
        def account_label_from_credentials(self, _credentials: dict) -> str | None:
            return "derived-label"

    pending = PendingAuthEntry(
        account_id="account-1",
        provider="generic",
        profile_name="fallback-profile",
        code_verifier="verifier",
        redirect_uri="http://localhost/callback",
        connection_id="connection-1",
    )

    assert (
        _connection_label(pending, _LabelPlugin(), {"access_token": "tok"}, None) == "derived-label"
    )


@pytest.mark.asyncio
async def test_handle_loopback_callback_completes_oauth(client_with_index) -> None:
    client, credential_blobs = client_with_index
    account_id = _account_id(client)
    await _move_tortoise_to_pytest_loop(client, credential_blobs)
    state = "loopback-state"
    plugin = _GenericOAuthPlugin()
    server = _FakeServer()
    client.app.state.providers._plugins["generic"] = plugin
    client.app.state.loopback_oauth_callbacks = {state: server}
    await _seed_pending_flow(client, account_id, "generic", "loopback", state)

    writer = _FakeWriter()
    await _handle_loopback_callback(
        client.app,
        "generic",
        "/callback",
        state,
        _as_stream_reader(
            _FakeReader(_raw_loopback_request(f"/callback?code=loop-code&state={state}"))
        ),
        _as_stream_writer(writer),
    )

    assert writer.response.startswith(b"HTTP/1.1 200 OK\r\n")
    assert writer.closed is True
    assert plugin.exchange_request is not None
    assert plugin.exchange_request.code == "loop-code"
    assert plugin.strategy.creds is not None
    assert plugin.strategy.creds["access_token"] == "generic-token"
    assert server.closed is True
    assert server.waited is True
    assert state not in client.app.state.loopback_oauth_callbacks
    profile = await client.app.state.profile_index.get(account_id, "generic", "loopback")
    assert profile is not None
    assert profile.state == ProfileState.AUTHENTICATED
    await Tortoise.close_connections()


@pytest.mark.parametrize(
    ("reader", "expected_status", "expected_body"),
    [
        (
            _FakeReader(exc=asyncio.IncompleteReadError(partial=b"", expected=1)),
            b"400 Bad Request",
            b"Malformed callback request",
        ),
        (
            _FakeReader(b"GET\r\nHost: localhost\r\n\r\n"),
            b"400 Bad Request",
            b"Malformed callback request",
        ),
        (
            _FakeReader(_raw_loopback_request("/callback?code=c&state=expected", host="evil.test")),
            b"403 Forbidden",
            b"Forbidden callback host",
        ),
        (
            _FakeReader(_raw_loopback_request("/other?code=c&state=expected")),
            b"404 Not Found",
            b"Unknown callback path",
        ),
        (
            _FakeReader(_raw_loopback_request("/callback?state=expected")),
            b"400 Bad Request",
            b"Missing callback code or state",
        ),
        (
            _FakeReader(_raw_loopback_request("/callback?code=c&state=wrong")),
            b"400 Bad Request",
            b"OAuth state not recognized or expired",
        ),
    ],
)
@pytest.mark.asyncio
async def test_handle_loopback_callback_rejects_bad_requests(
    client_with_index, reader, expected_status, expected_body
) -> None:
    client, _ = client_with_index
    writer = _FakeWriter()

    await _handle_loopback_callback(
        client.app,
        "generic",
        "/callback",
        "expected",
        _as_stream_reader(reader),
        _as_stream_writer(writer),
    )

    assert expected_status in writer.response
    assert expected_body in writer.response
    assert writer.closed is True


@pytest.mark.parametrize(
    "reader",
    [
        _FakeReader(_raw_loopback_request("/other?code=c&state=expected")),
        _FakeReader(_raw_loopback_request("/callback?code=c&state=wrong")),
        _FakeReader(_raw_loopback_request("/callback?code=c&state=expected", host="evil.test")),
    ],
)
@pytest.mark.asyncio
async def test_handle_loopback_callback_keeps_listener_for_stray_requests(
    client_with_index,
    reader,
) -> None:
    client, _ = client_with_index
    server = _FakeServer()
    client.app.state.loopback_oauth_callbacks = {"expected": server}

    await _handle_loopback_callback(
        client.app,
        "generic",
        "/callback",
        "expected",
        _as_stream_reader(reader),
        _as_stream_writer(_FakeWriter()),
    )

    assert server.closed is False
    assert server.waited is False
    assert client.app.state.loopback_oauth_callbacks == {"expected": server}


@pytest.mark.asyncio
async def test_handle_loopback_callback_sanitizes_completion_errors(client_with_index) -> None:
    client, credential_blobs = client_with_index
    account_id = _account_id(client)
    await _move_tortoise_to_pytest_loop(client, credential_blobs)
    state = "loopback-error-state"
    server = _FakeServer()
    client.app.state.providers._plugins["generic"] = _ExplodingOAuthPlugin()
    client.app.state.loopback_oauth_callbacks = {state: server}
    connection_id = await _seed_pending_flow(client, account_id, "generic", "loopback-error", state)

    writer = _FakeWriter()
    await _handle_loopback_callback(
        client.app,
        "generic",
        "/callback",
        state,
        _as_stream_reader(_FakeReader(_raw_loopback_request(f"/callback?code=boom&state={state}"))),
        _as_stream_writer(writer),
    )

    assert b"HTTP/1.1 500 Internal Server Error" in writer.response
    assert b"&lt;script&gt;bad&lt;/script&gt;" not in writer.response
    assert b"<script>bad</script>" not in writer.response
    assert b"OAuth callback failed. Try again." in writer.response
    assert server.closed is True
    assert server.waited is True
    # WHY the Connection: since OME-1209 Stage E3b a failed callback marks its own Connection.
    connection = await OAuthConnectionStore().get(account_id, connection_id)
    assert connection is not None
    assert connection.status == "error"
    await Tortoise.close_connections()


def test_exchange_code_uses_provider_exchange_hook(client_with_index) -> None:
    client, _ = client_with_index
    account_id = _account_id(client)
    plugin = _GenericOAuthPlugin()
    client.app.state.providers._plugins["generic"] = plugin

    redirect_uri = "http://localhost:1455/callback"
    state, _ = _open_flow(client, "generic", "work", redirect_uri=redirect_uri)

    resp = client.post(
        "/v1/auth/generic/exchange-code",
        json={"code": "generic-code", "state": state},
    )

    assert resp.status_code == 200
    assert plugin.exchange_request is not None
    assert plugin.exchange_request.code == "generic-code"
    assert plugin.exchange_request.redirect_uri == redirect_uri
    assert plugin.exchange_request.state == state
    assert plugin.strategy.creds is not None
    assert plugin.strategy.creds["access_token"] == "generic-token"
    profile = _indexed_profile(client, "generic", "work")
    assert profile["id"] == profile_id_for(account_id, "generic", "work")
    assert profile["state"] == "authenticated"


def test_connection_exchange_uses_redirect_uri_override(client_with_index) -> None:
    client, _ = client_with_index
    plugin = _GenericOAuthPlugin()
    client.app.state.providers._plugins["generic"] = plugin
    redirect_uri = "http://localhost:9105/callback"

    start = client.post(
        "/v1/oauth/connections",
        json={
            "provider": "generic",
            "label": "generic-override",
            "redirect_uri": redirect_uri,
        },
    )
    assert start.status_code == 201

    resp = client.post(
        "/v1/auth/generic/exchange-code",
        json={"code": "generic-code", "state": start.json()["state"]},
    )

    assert resp.status_code == 200
    assert plugin.exchange_request is not None
    assert plugin.exchange_request.redirect_uri == redirect_uri


def test_connection_delete_wins_over_stalled_oauth_completion(client_with_index) -> None:
    """A callback consumed before DELETE must not reactivate the revoked connection.

    INVARIANT: OAuth activation conditionally transitions the stable connection row before
    writing credentials in the same transaction. Once DELETE commits revoked, the callback
    conflicts without writing an orphan credential.
    """
    client, _ = client_with_index
    exchange_started = threading.Event()
    release_exchange = threading.Event()

    class _BlockingConnectionOAuthPlugin(_GenericOAuthPlugin):
        async def exchange_oauth_code(self, request: OAuthCodeExchangeRequest) -> dict:
            exchange_started.set()
            if not await asyncio.to_thread(release_exchange.wait, 5):
                raise TimeoutError("OAuth exchange was not released")
            return await super().exchange_oauth_code(request)

    plugin = _BlockingConnectionOAuthPlugin()
    client.app.state.providers._plugins["generic"] = plugin
    start = client.post(
        "/v1/oauth/connections",
        json={"provider": "generic", "label": "delete-race"},
    )
    assert start.status_code == 201
    connection_id = start.json()["connection_id"]

    with ThreadPoolExecutor(max_workers=1) as executor:
        callback = executor.submit(
            client.post,
            "/v1/auth/generic/exchange-code",
            json={"code": "generic-code", "state": start.json()["state"]},
        )
        assert exchange_started.wait(5), "callback never consumed state and reached exchange"
        deleted = client.delete(f"/v1/oauth/connections/{connection_id}")
        release_exchange.set()
        completed = callback.result(timeout=5)

    assert deleted.status_code == 204
    assert completed.status_code == 409
    assert completed.json()["detail"]["code"] == "connection_conflict"
    assert plugin.strategy.creds is None
    assert client.get(f"/v1/oauth/connections/{connection_id}").json()["status"] == "revoked"


def test_connection_delete_wins_over_stalled_oauth_failure(client_with_index) -> None:
    """A stale exchange failure must not rewrite a committed revoke to ERROR."""
    client, _ = client_with_index
    exchange_started = threading.Event()
    release_exchange = threading.Event()

    class _FailingConnectionOAuthPlugin(_GenericOAuthPlugin):
        async def exchange_oauth_code(self, request: OAuthCodeExchangeRequest) -> dict:
            self.exchange_request = request
            exchange_started.set()
            if not await asyncio.to_thread(release_exchange.wait, 5):
                raise TimeoutError("OAuth exchange failure was not released")
            raise RuntimeError("provider rejected the consumed code")

    plugin = _FailingConnectionOAuthPlugin()
    client.app.state.providers._plugins["generic"] = plugin
    start = client.post(
        "/v1/oauth/connections",
        json={"provider": "generic", "label": "delete-failure-race"},
    )
    connection_id = start.json()["connection_id"]

    with ThreadPoolExecutor(max_workers=1) as executor:
        callback = executor.submit(
            client.get,
            "/callback",
            params={"code": "generic-code", "state": start.json()["state"]},
            follow_redirects=False,
        )
        assert exchange_started.wait(5), "callback never consumed state and reached exchange"
        deleted = client.delete(f"/v1/oauth/connections/{connection_id}")
        release_exchange.set()
        failed = callback.result(timeout=5)

    assert deleted.status_code == 204
    assert failed.status_code == 500
    assert client.get(f"/v1/oauth/connections/{connection_id}").json()["status"] == "revoked"
    assert plugin.strategy.creds is None


def test_connection_completion_writes_no_credentials_when_activation_conflicts(
    client_with_index, monkeypatch
) -> None:
    client, _ = client_with_index
    plugin = _GenericOAuthPlugin()
    client.app.state.providers._plugins["generic"] = plugin

    async def complete_conflict(*_args, **_kwargs) -> None:
        raise IntegrityError("simulated connection race")

    monkeypatch.setattr(
        "aigateway.routes.auth.OAuthConnectionStore.complete_pending",
        complete_conflict,
    )

    start = client.post(
        "/v1/oauth/connections",
        json={"provider": "generic", "label": "race-generic"},
    )
    assert start.status_code == 201

    resp = client.post(
        "/v1/auth/generic/exchange-code",
        json={"code": "generic-code", "state": start.json()["state"]},
    )

    assert resp.status_code == 409
    assert resp.json()["detail"]["code"] == "connection_conflict"
    assert plugin.strategy.creds is None
    assert plugin.strategy.deleted is False


def test_connection_completion_non_integrity_failure_writes_no_credentials_and_marks_error(
    client_with_index, monkeypatch
) -> None:
    client, _ = client_with_index
    plugin = _GenericOAuthPlugin()
    client.app.state.providers._plugins["generic"] = plugin
    leak_marker = "sk-ant-api03-activation-secret-that-must-not-leak"

    async def complete_failure(*_args, **_kwargs) -> None:
        raise OperationalError(f"database locked while handling {leak_marker}")

    monkeypatch.setattr(
        "aigateway.routes.auth.OAuthConnectionStore.complete_pending",
        complete_failure,
    )

    start = client.post(
        "/v1/oauth/connections",
        json={"provider": "generic", "label": "operational-failure"},
    )
    assert start.status_code == 201
    connection_id = start.json()["connection_id"]

    with _server_errors_as_responses(client):
        resp = client.post(
            "/v1/auth/generic/exchange-code",
            json={"code": "generic-code", "state": start.json()["state"]},
        )

    assert resp.status_code == 503
    assert resp.json()["detail"]["code"] == "connection_activation_failed"
    assert leak_marker not in resp.text
    assert plugin.strategy.creds is None
    assert plugin.strategy.deleted is False
    connection = client.get(f"/v1/oauth/connections/{connection_id}").json()
    assert connection["status"] == "error"
    assert leak_marker not in json.dumps(connection)


def test_connection_completion_conflict_needs_no_delete_compensation(
    client_with_index, monkeypatch, caplog
) -> None:
    client, _ = client_with_index
    plugin = _GenericOAuthPlugin()
    client.app.state.providers._plugins["generic"] = plugin
    leak_marker = "sk-ant-api03-delete-secret-that-must-not-leak"

    async def complete_conflict(*_args, **_kwargs) -> None:
        raise IntegrityError("simulated connection race")

    async def delete_failure() -> None:
        raise RuntimeError(f"delete failed for {leak_marker}")

    monkeypatch.setattr(
        "aigateway.routes.auth.OAuthConnectionStore.complete_pending",
        complete_conflict,
    )
    monkeypatch.setattr(plugin.strategy, "delete_credentials", delete_failure)
    caplog.set_level(logging.ERROR, logger="aigateway.routes.auth")

    start = client.post(
        "/v1/oauth/connections",
        json={"provider": "generic", "label": "delete-failure"},
    )
    assert start.status_code == 201

    resp = client.post(
        "/v1/auth/generic/exchange-code",
        json={"code": "generic-code", "state": start.json()["state"]},
    )

    assert resp.status_code == 409
    assert resp.json()["detail"]["code"] == "connection_conflict"
    assert plugin.strategy.creds is None
    assert plugin.strategy.deleted is False
    assert "Failed to delete OAuth connection credentials" not in caplog.text
    assert leak_marker not in caplog.text


def test_connection_completion_persist_failure_is_sanitized_and_non_active(
    client_with_index, monkeypatch
) -> None:
    client, _ = client_with_index
    plugin = _GenericOAuthPlugin()
    client.app.state.providers._plugins["generic"] = plugin
    leak_marker = "sk-ant-api03-loopback-secret-that-must-not-leak"

    async def persist_failure(_creds: dict) -> None:
        raise RuntimeError(f"credential store exploded with {leak_marker}")

    monkeypatch.setattr(plugin.strategy, "persist_credentials", persist_failure)
    start = client.post(
        "/v1/oauth/connections",
        json={"provider": "generic", "label": "persist-failure"},
    )
    assert start.status_code == 201
    connection_id = start.json()["connection_id"]

    auth_header = client.headers.pop("Authorization")
    try:
        with _server_errors_as_responses(client):
            cb = client.get(
                "/callback",
                params={"code": "generic-code", "state": start.json()["state"]},
                follow_redirects=False,
            )
    finally:
        client.headers["Authorization"] = auth_header

    assert cb.status_code == 503
    assert leak_marker not in cb.text
    connection = client.get(f"/v1/oauth/connections/{connection_id}").json()
    assert connection["status"] == "error"
    assert leak_marker not in json.dumps(connection)


# WHY no Profile-flow persist-failure test: since OME-1209 Stage E3b every flow is a native
# Connection flow, pinned by
# `test_connection_completion_persist_failure_is_sanitized_and_non_active`.


def test_profile_oauth_profile_index_conflict_returns_sanitized_503_html(
    client_with_index, monkeypatch
) -> None:
    client, _ = client_with_index
    plugin = _GenericOAuthPlugin()
    client.app.state.providers._plugins["generic"] = plugin
    state, _ = _open_flow(client, "generic", "index-conflict")

    async def authenticate_conflict(_profile, **_kwargs) -> None:
        raise CredentialBlobMutationConflict("forced contention")

    # WHY: on the OAuth callback path a CAS conflict surfaces from the D14 compat-document
    # mirror, the index upsert inside the completion transaction (OME-1209 Stage E3b).
    monkeypatch.setattr(client.app.state.profile_index, "upsert", authenticate_conflict)
    auth_header = client.headers.pop("Authorization")
    try:
        with _server_errors_as_responses(client):
            cb = client.get(
                "/callback",
                params={"code": "generic-code", "state": state},
                follow_redirects=False,
            )
    finally:
        client.headers["Authorization"] = auth_header

    assert cb.status_code == 503
    assert "profile_index_conflict" in cb.text
    assert "forced contention" not in cb.text


@pytest.mark.parametrize(
    ("method", "path", "json"),
    [
        ("POST", "/v1/auth/anthropic/exchange-code", {"code": "x", "state": "y"}),
    ],
)
def test_oauth_profile_routes_require_jwt(client, method, path, json) -> None:
    response = client.request(method, path, json=json)
    assert response.status_code == 401


def _mock_token_factory():
    transport = httpx.MockTransport(
        lambda req: httpx.Response(
            200,
            json={
                "access_token": "new-tok",
                "refresh_token": "new-rt",
                "expires_in": 3600,
                "token_type": "Bearer",
            },
        )
    )
    return lambda: httpx.AsyncClient(transport=transport, timeout=httpx.Timeout(5.0))


def _jwt(payload: dict) -> str:
    def encode(value: dict | bytes) -> str:
        raw = value if isinstance(value, bytes) else json.dumps(value).encode()
        return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()

    return f"{encode({'alg': 'none', 'typ': 'JWT'})}.{encode(payload)}.{encode(b'sig')}"


def _mock_codex_token_factory():
    token_payload = {
        "sub": "sub-1",
        "email": "user@example.com",
        "exp": int(time.time()) + 3600,
        "https://api.openai.com/auth": {"chatgpt_account_id": "acct-1"},
    }
    transport = httpx.MockTransport(
        lambda req: httpx.Response(
            200,
            json={
                "access_token": _jwt(token_payload),
                "refresh_token": "codex-refresh",
                "id_token": _jwt(token_payload),
                "token_type": "Bearer",
            },
        )
    )
    return lambda: httpx.AsyncClient(transport=transport, timeout=httpx.Timeout(5.0))


def _failing_token_factory():
    transport = httpx.MockTransport(
        lambda req: httpx.Response(400, json={"error": "invalid_grant"})
    )
    return lambda: httpx.AsyncClient(transport=transport, timeout=httpx.Timeout(5.0))


def _html_failing_token_factory():
    transport = httpx.MockTransport(
        lambda req: httpx.Response(400, text="<script>alert('x')</script>")
    )
    return lambda: httpx.AsyncClient(transport=transport, timeout=httpx.Timeout(5.0))


def test_callback_completes_auth(client_with_index) -> None:
    client, credential_blobs = client_with_index
    account_id = _account_id(client)
    client.app.state.anthropic_http_factory = _mock_token_factory()

    state, connection_id = _open_flow(client, "anthropic", "work")
    assert _indexed_profile(client, "anthropic", "work")["last_refreshed_at"] is None
    before = datetime.now(UTC)

    auth_header = client.headers.pop("Authorization")
    try:
        cb = client.get(
            "/v1/auth/anthropic/callback",
            params={"code": "auth-code-1", "state": state},
            follow_redirects=False,
        )
    finally:
        client.headers["Authorization"] = auth_header
    assert cb.status_code == 200

    prof = _indexed_profile(client, "anthropic", "work")
    assert prof["state"] == "authenticated"
    # INVARIANT (D14): the native callback's mirror stamps the compat document's refresh time.
    assert datetime.fromisoformat(prof["last_refreshed_at"]) >= before

    from aigateway.plugins.anthropic_provider.auth import credential_service_for

    blob = credential_blobs.read(
        credential_service_for(credential_key_for(account_id, connection_id)), "default"
    )
    assert "new-tok" in blob


# WHY no Profile-flow rollback test: since OME-1209 Stage E3b every flow is a native Connection
# flow; a failed compat-document mirror rolling the completion back is pinned in
# `core/provider_access/test_writer_floor_native.py`
# (`test_a_native_callback_publication_failure_leaves_same_named_profile_unchanged`) and
# `core/provider_access/test_writer_floor_native_compat.py`
# (`test_a_compat_document_conflict_rolls_the_native_callback_back_as_an_index_conflict`).


def test_codex_nested_callback_completes_auth_with_provider_hook(client_with_index) -> None:
    client, credential_blobs = client_with_index
    account_id = _account_id(client)
    client.app.state.codex_http_factory = _mock_codex_token_factory()

    state, connection_id = _open_flow(client, "codex", "work")

    auth_header = client.headers.pop("Authorization")
    try:
        cb = client.get(
            "/auth/callback",
            params={"code": "codex-code-1", "state": state},
            follow_redirects=False,
        )
    finally:
        client.headers["Authorization"] = auth_header
    assert cb.status_code == 200

    prof = _indexed_profile(client, "codex", "work")
    assert prof["state"] == "authenticated"
    assert prof["account_label"] == "user@example.com"

    from aigateway.plugins.codex_provider.auth import credential_service_for

    blob = credential_blobs.read(
        credential_service_for(credential_key_for(account_id, connection_id)), "default"
    )
    assert blob is not None
    assert json.loads(blob)["refresh_token"] == "codex-refresh"


def test_codex_import_profile_endpoint_is_absent(client_with_index) -> None:
    client, _ = client_with_index

    resp = client.post("/v1/auth/codex/profiles/import", json={"name": "default"})

    assert resp.status_code == 405


def test_callback_exchange_failure_consumes_state_and_marks_profile_error(
    client_with_index,
) -> None:
    client, _ = client_with_index
    client.app.state.anthropic_http_factory = _failing_token_factory()

    state, connection_id = _open_flow(client, "anthropic", "retry")

    auth_header = client.headers.pop("Authorization")
    try:
        failed = client.get(
            "/callback",
            params={"code": "bad-code", "state": state},
            follow_redirects=False,
        )
        client.app.state.anthropic_http_factory = _mock_token_factory()
        retried = client.get(
            "/callback",
            params={"code": "good-code", "state": state},
            follow_redirects=False,
        )
    finally:
        client.headers["Authorization"] = auth_header

    assert failed.status_code == 500
    assert retried.status_code == 400
    # WHY the Connection: since OME-1209 Stage E3b a failed callback marks its own Connection.
    assert client.get(f"/v1/oauth/connections/{connection_id}").json()["status"] == "error"


@pytest.mark.asyncio
async def test_complete_oauth_consumes_state_before_awaiting_exchange(client_with_index) -> None:
    client, credential_blobs = client_with_index
    account_id = _account_id(client)
    plugin = _DelayedOAuthPlugin()
    client.app.state.providers._plugins["generic"] = plugin

    state, _ = _open_flow(client, "generic", "race")
    await _move_tortoise_to_pytest_loop(client, credential_blobs)

    results = await asyncio.gather(
        _complete_oauth_for_app(client.app, "generic", "code-one", state, account_id),
        _complete_oauth_for_app(client.app, "generic", "code-two", state, account_id),
        return_exceptions=True,
    )

    assert sum(result is None for result in results) == 1
    errors = [result for result in results if isinstance(result, HTTPException)]
    assert len(errors) == 1
    assert errors[0].status_code == 400
    assert plugin.exchange_count == 1
    profile = await client.app.state.profile_index.get(account_id, "generic", "race")
    assert profile is not None
    assert profile.state == ProfileState.AUTHENTICATED
    await Tortoise.close_connections()


# WHY no Profile-session invalidation test: a native flow writes a fresh Connection address, so
# there is no prior session to invalidate; it retired with the legacy callback (OME-1209 E3b).


def test_callback_error_html_sanitizes_provider_response(client_with_index) -> None:
    client, _ = client_with_index
    client.app.state.anthropic_http_factory = _html_failing_token_factory()
    state, _ = _open_flow(client, "anthropic", "htmlfail")

    auth_header = client.headers.pop("Authorization")
    try:
        resp = client.get(
            "/callback",
            params={"code": "bad-code", "state": state},
            follow_redirects=False,
        )
    finally:
        client.headers["Authorization"] = auth_header

    assert resp.status_code == 500
    assert "<script>" not in resp.text
    assert "&lt;script&gt;alert(&#x27;x&#x27;)&lt;/script&gt;" not in resp.text
    assert "OAuth callback failed. Try again." in resp.text


def test_callback_with_unknown_state_400(client_with_index) -> None:
    client, _ = client_with_index
    auth_header = client.headers.pop("Authorization")
    try:
        resp = client.get(
            "/v1/auth/anthropic/callback",
            params={"code": "x", "state": "never-issued"},
        )
    finally:
        client.headers["Authorization"] = auth_header
    assert resp.status_code == 400


def test_exchange_code_runs_oauth(client_with_index) -> None:
    """POST /v1/auth/{provider}/exchange-code completes auth same as GET callback."""
    client, credential_blobs = client_with_index
    account_id = _account_id(client)
    client.app.state.anthropic_http_factory = _mock_token_factory()

    state, connection_id = _open_flow(client, "anthropic", "paste")

    resp = client.post(
        "/v1/auth/anthropic/exchange-code",
        json={"code": "pasted-code-1", "state": state},
    )
    assert resp.status_code == 200
    assert resp.json() == {"state": "authenticated"}

    prof = _indexed_profile(client, "anthropic", "paste")
    assert prof["state"] == "authenticated"

    from aigateway.plugins.anthropic_provider.auth import credential_service_for

    blob = credential_blobs.read(
        credential_service_for(credential_key_for(account_id, connection_id)), "default"
    )
    assert "new-tok" in blob


def test_exchange_code_with_unknown_provider_404(client_with_index) -> None:
    client, _ = client_with_index
    client.app.state.providers._plugins["generic"] = _GenericOAuthPlugin()

    state, _ = _open_flow(client, "generic", "gone")
    client.app.state.providers._plugins.pop("generic")

    resp = client.post(
        "/v1/auth/generic/exchange-code",
        json={"code": "generic-code", "state": state},
    )

    assert resp.status_code == 404
    assert resp.json()["detail"]["code"] == "unknown_provider"


def test_exchange_code_without_oauth_strategy_returns_400(client_with_index, monkeypatch) -> None:
    client, _ = client_with_index
    plugin = _GenericOAuthPlugin()
    monkeypatch.setattr(plugin, "oauth_strategy_for", lambda *_args, **_kwargs: None)
    client.app.state.providers._plugins["generic"] = plugin

    state, _ = _open_flow(client, "generic", "no-strategy")

    resp = client.post(
        "/v1/auth/generic/exchange-code",
        json={"code": "generic-code", "state": state},
    )

    assert resp.status_code == 400
    assert resp.json()["detail"]["code"] == "provider_does_not_use_oauth"


def test_exchange_code_race_after_validation_returns_unknown_state(
    client_with_index, monkeypatch
) -> None:
    client, _ = client_with_index
    client.app.state.providers._plugins["generic"] = _GenericOAuthPlugin()

    state, _ = _open_flow(client, "generic", "pop-race")
    monkeypatch.setattr(client.app.state.pending_auth, "pop", lambda _state: None)

    resp = client.post(
        "/v1/auth/generic/exchange-code",
        json={"code": "generic-code", "state": state},
    )

    assert resp.status_code == 400
    assert resp.json()["detail"]["code"] == "unknown_state"


def test_connection_exchange_not_implemented_marks_connection_error(
    client_with_index, monkeypatch
) -> None:
    client, _ = client_with_index
    plugin = _GenericOAuthPlugin()

    async def not_implemented(_request: OAuthCodeExchangeRequest) -> dict:
        raise NotImplementedError("not supported")

    monkeypatch.setattr(plugin, "exchange_oauth_code", not_implemented)
    client.app.state.providers._plugins["generic"] = plugin

    start = client.post(
        "/v1/oauth/connections",
        json={"provider": "generic", "label": "generic-not-implemented"},
    )
    connection_id = start.json()["connection_id"]

    resp = client.post(
        "/v1/auth/generic/exchange-code",
        json={"code": "generic-code", "state": start.json()["state"]},
    )

    assert resp.status_code == 400
    assert resp.json()["detail"]["code"] == "provider_does_not_use_oauth"

    detail = client.get(f"/v1/oauth/connections/{connection_id}")
    assert detail.status_code == 200
    assert detail.json()["status"] == "error"
    assert detail.json()["error_message"] == "provider_does_not_use_oauth"


def test_exchange_code_with_unknown_state_400(client_with_index) -> None:
    client, _ = client_with_index
    resp = client.post(
        "/v1/auth/anthropic/exchange-code",
        json={"code": "x", "state": "never-issued"},
    )
    assert resp.status_code == 400
    assert resp.json()["detail"]["code"] == "unknown_state"


def test_exchange_code_with_provider_mismatch_400(client_with_index) -> None:
    client, _ = client_with_index
    state, _ = _open_flow(client, "anthropic", "mismatch")

    resp = client.post(
        "/v1/auth/ghost/exchange-code",
        json={"code": "x", "state": state},
    )
    assert resp.status_code == 400
    assert resp.json()["detail"]["code"] == "provider_mismatch"


def test_exchange_code_with_other_accounts_state_404(
    client_with_index, provisioned_user_factory
) -> None:
    client, _ = client_with_index
    state, _ = _open_flow(client, "anthropic", "admin-only")
    provisioned_user_factory("bob", "bob-pass1")
    login = client.post("/v1/auth/login", json={"username": "bob", "password": "bob-pass1"})
    client.headers.update({"Authorization": f"Bearer {login.json()['token']}"})

    resp = client.post(
        "/v1/auth/anthropic/exchange-code",
        json={"code": "x", "state": state},
    )
    assert resp.status_code == 404
    assert resp.json()["detail"]["code"] == "profile_not_found"
