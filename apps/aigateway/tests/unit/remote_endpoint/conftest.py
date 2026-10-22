"""App harness for configured endpoints: real `create_app`, isolated store, fake upstream HTTP.

# FEATURE: hosted BYOM Unit 0 — every app-level test runs the real routes, provider access, admin
# publication, strategy cache, validation service and encrypted store; only the network is fake.
# WHY accounts are created before the app starts: grants name account UUIDs, and the config is read
# once at startup, so the UUIDs must exist first — as they do when an operator grants a tenant.
# WHY `start` can be entered again on the same store: a grant or enable change is a restart.
"""

from __future__ import annotations

import asyncio
import base64
import json
import sqlite3
from collections.abc import Iterator
from contextlib import closing, contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from tortoise import Tortoise

from aigateway.core.auth.models import Account
from aigateway.db import close_db, init_db
from aigateway.plugins.remote_endpoint.validation import RemoteEndpointReadiness
from tests.conftest import TEST_SECRET_KEY, CredentialBlobProbe

from .fixtures import ACCOUNT_A, ACCOUNT_B, ALIAS, ENDPOINT_A, ENDPOINT_B, to_toml

ADMIN = "admin@byom.test"
EMAIL = {ACCOUNT_A: "alice@byom.test", ACCOUNT_B: "bob@byom.test"}
# A key containing this marker is refused by the fake upstream, as a revoked key would be.
REJECTED = "rejected"
# A key containing this marker gets HTTP 200 with a body that is not a chat completion.
MALFORMED = "malformed"
# A key containing this marker gets a well-formed completion served as `text/html`.
WRONG_TYPE = "wrong-type"
PEER = ("10.1.2.3", 50000)


@dataclass(frozen=True)
class Call:
    url: str
    bearer: str
    model: str | None
    probe: bool


@dataclass
class Upstream:
    """One fake HTTP server behind every configured endpoint; it records and echoes each request."""

    calls: list[Call] = field(default_factory=list)
    # The JSON body of each request, in the order of `calls`.
    bodies: list[dict[str, Any]] = field(default_factory=list)
    _parties: int = 0
    _barrier: asyncio.Barrier | None = None

    def expect_overlap(self, parties: int) -> None:
        """Hold every request until `parties` are in flight at once (0 turns it off)."""
        self._parties, self._barrier = parties, None

    def transport(self, *, probe: bool = False) -> httpx.MockTransport:
        """A transport whose calls are recorded as readiness probes when ``probe`` is set."""

        async def handle(request: httpx.Request) -> httpx.Response:
            return await self._handle(request, probe=probe)

        return httpx.MockTransport(handle)

    async def _handle(self, request: httpx.Request, *, probe: bool) -> httpx.Response:
        payload = json.loads(request.content)
        bearer = request.headers.get("authorization", "")
        self.calls.append(Call(str(request.url), bearer, payload.get("model"), probe))
        self.bodies.append(payload)
        if self._parties:
            if self._barrier is None:
                self._barrier = asyncio.Barrier(self._parties)
            # INVARIANT: a timeout here means the gateway serialized requests it must overlap.
            await asyncio.wait_for(self._barrier.wait(), timeout=10)
        if REJECTED in bearer:
            return httpx.Response(401, json={"error": "upstream says the key is invalid"})
        if MALFORMED in bearer:
            return httpx.Response(200, json={"object": "chat.completion", "choices": [{}]})
        echo = f"{request.url}|{bearer}"
        # WHY a finish_reason: a finished answer declares it, and only a finished answer may be
        # stored by the shared cache.
        choice = {"index": 0, "message": {"role": "assistant", "content": echo}}
        choice["finish_reason"] = "stop"
        completion = {"object": "chat.completion", "choices": [choice]}
        if WRONG_TYPE in bearer:
            content = json.dumps(completion).encode()
            return httpx.Response(200, content=content, headers={"content-type": "text/html"})
        return httpx.Response(200, json=completion)


@dataclass
class Harness:
    monkeypatch: pytest.MonkeyPatch
    blobs: CredentialBlobProbe
    config_path: Path
    upstream: Upstream

    @contextmanager
    def start(self, doc: dict[str, Any] | None) -> Iterator[TestClient]:
        if doc is None:
            self.monkeypatch.delenv("AIGW_REMOTE_ENDPOINTS_CONFIG", raising=False)
        else:
            self.config_path.write_text(to_toml(doc), encoding="utf-8")
            self.monkeypatch.setenv("AIGW_REMOTE_ENDPOINTS_CONFIG", str(self.config_path))
        from aigateway.main import create_app

        app = create_app()
        with TestClient(app, client=PEER) as client:
            for provider in (ENDPOINT_A, ENDPOINT_B):
                plugin = app.state.providers.get(provider)
                if plugin is not None:
                    plugin._transport = self.upstream.transport()
                    # WHY a validator of its own: the probe sends the very request an ordinary
                    # chat sends, so only the transport it uses can mark a call as a probe.
                    readiness = RemoteEndpointReadiness(
                        plugin._definition, transport=self.upstream.transport(probe=True)
                    )
                    self.monkeypatch.setattr(plugin, "api_key_validator", lambda r=readiness: r)
            yield client
        asyncio.run(Tortoise.close_connections())

    def stored_key(self, account: str, provider: str) -> str | None:
        # WHY the live row's locator (E5a, history cleanup): a minted row keeps its key at its own
        # `<account>:<row id>` address, never a Profile name, so the harness reads the address the
        # row names.
        with closing(sqlite3.connect(self.blobs.db_path)) as db:
            rows = db.execute(
                "SELECT credential_locator FROM oauth_connections"
                " WHERE account_id = ? AND provider = ? AND status != 'revoked'",
                (account, provider),
            ).fetchall()
        if not rows:
            return None
        ((locator,),) = rows
        address = json.loads(locator)
        raw = self.blobs.read(address["service"], address["account"])
        return None if raw is None else json.loads(raw)["api_key"]


@pytest.fixture
def byom(monkeypatch: pytest.MonkeyPatch, credential_blobs: CredentialBlobProbe, tmp_path: Path):
    database_url = f"sqlite://{credential_blobs.db_path}"
    monkeypatch.setenv("AIGATEWAY_ADMIN_PASSWORD", "test-admin-password")
    monkeypatch.setenv("AIGATEWAY_JWT_SECRET", "x" * 32)
    monkeypatch.setenv("AIGATEWAY_PROVISIONING_TOKEN", "p" * 32)
    monkeypatch.setenv("AIGATEWAY_SECRET_KEY", base64.b64encode(TEST_SECRET_KEY).decode())
    monkeypatch.setenv("AIGW_AUTH_MODE", "cloudflare_headers")
    monkeypatch.setenv("AIGW_ALLOWED_NETWORKS", "10.0.0.0/8")
    monkeypatch.setenv("AIGATEWAY_ADMIN_EMAILS", ADMIN)

    async def seed_accounts() -> None:
        await init_db(database_url)
        try:
            for account_id, email in EMAIL.items():
                await Account.create(id=account_id, username=email, password_hash="")
        finally:
            await close_db()

    asyncio.run(seed_accounts())
    return Harness(monkeypatch, credential_blobs, tmp_path / "remote-endpoints.toml", Upstream())


# --- request helpers ----------------------------------------------------------------------------


def admin_headers() -> dict[str, str]:
    return {"X-User-Email": ADMIN}


def tenant_headers(account: str) -> dict[str, str]:
    return {"X-User-Email": EMAIL[account]}


def put_key(client: TestClient, account: str, provider: str, key: str) -> httpx.Response:
    return client.put(
        f"/v1/admin/accounts/{account}/connections/{provider}/api-key",
        json={"api_key": key},
        headers=admin_headers(),
    )


def delete_pair(client: TestClient, account: str, provider: str) -> httpx.Response:
    return client.delete(
        f"/v1/admin/accounts/{account}/connections/{provider}", headers=admin_headers()
    )


def chat_body(provider: str, alias: str = ALIAS) -> dict[str, Any]:
    return {"model": f"{provider}/{alias}", "messages": [{"role": "user", "content": "ping"}]}


def chat(client: TestClient, account: str, provider: str, alias: str = ALIAS) -> httpx.Response:
    return client.post(
        "/v1/chat/completions", json=chat_body(provider, alias), headers=tenant_headers(account)
    )


def echo_of(response: httpx.Response) -> str:
    assert response.status_code == 200, response.text
    return response.json()["choices"][0]["message"]["content"]
