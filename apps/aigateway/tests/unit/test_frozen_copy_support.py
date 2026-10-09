"""Shared arrangement for the frozen-copy tests (OME-1307). Holds no test of its own."""

from __future__ import annotations

import json
import time
from collections.abc import Callable, Coroutine, Iterator
from contextlib import contextmanager
from functools import partial
from typing import Any, Literal
from uuid import UUID, uuid4

from fastapi.testclient import TestClient

from aigateway.core.frozen_copy.store import FrozenCopyStore
from aigateway.core.oauth.store import OAuthConnectionStore, credential_key_for
from aigateway.plugins.anthropic_provider.auth import credential_service_for

CHAT_PATH = "/v1/chat/completions"
COPY_HEADER = "X-AIGW-Frozen-Copy"
CAPTURE_HEADER = "X-AIGW-Capture"
PATCH_TARGET = "aigateway.plugins.anthropic_provider.plugin.AnthropicProviderPlugin.chat_completion"

Entry = tuple[Literal["chat", "tool"], Any, Any, int]


def run_async[T](client: TestClient, call: Callable[[], Coroutine[Any, Any, T]]) -> T:
    """Run a coroutine on the app's own event loop, where Tortoise is initialised."""
    portal = client.portal
    assert portal is not None
    return portal.call(call)


def chat_body(**overrides: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "model": "anthropic/claude-haiku-4-5",
        "messages": [{"role": "user", "content": "how many primes below one hundred?"}],
    }
    body.update(overrides)
    return body


def chat_response(marker: str) -> dict[str, Any]:
    return {
        "id": marker,
        "choices": [{"message": {"content": f"answer {marker}"}, "finish_reason": "stop"}],
    }


def store() -> FrozenCopyStore:
    return FrozenCopyStore(max_entry_bytes=2_000_000)


def account_id_of(client: TestClient) -> UUID:
    return UUID(client.get("/v1/auth/me").json()["id"])


def seed_copy(
    client: TestClient, owner_id: UUID, entries: list[Entry], *, seal: bool = True
) -> str:
    """A copy owned by `owner_id`, filled through the store in the given capture order."""

    async def _seed() -> str:
        frozen = store()
        copy = await frozen.open(owner_id)
        for kind, request, response, status_code in entries:
            await frozen.capture(copy, kind, request, response, status_code)
        if seal:
            await frozen.seal(copy.id, owner_id)
        return str(copy.id)

    return run_async(client, _seed)


def seal_copy(client: TestClient, copy_id: str) -> None:
    """Seal through the store as the signed-in account."""
    owner_id = account_id_of(client)

    async def _seal() -> None:
        assert await store().seal(UUID(copy_id), owner_id) is not None

    run_async(client, _seal)


def stored_entries(client: TestClient, copy_id: str) -> list[dict[str, Any]]:
    from aigateway.core.frozen_copy.models import FrozenCopyEntry

    async def _read() -> list[dict[str, Any]]:
        rows = await FrozenCopyEntry.filter(frozen_copy_id=UUID(copy_id)).order_by("seq")
        return [
            {
                "kind": row.kind,
                "seq": row.seq,
                "digest": row.request_digest,
                "request": row.request_json,
                "response": row.response_json,
                "status_code": row.status_code,
            }
            for row in rows
        ]

    return run_async(client, _read)


async def _create_active_connection(account_id: str):
    connections = OAuthConnectionStore()
    connection = await connections.create_pending(
        account_id=account_id, provider="anthropic", label="default", connection_id=uuid4()
    )
    return await connections.complete(connection, label="default", identity=None)


def arrange_provider(client: TestClient, credential_blobs) -> str:
    """An active Anthropic connection with a stored credential, for the signed-in account."""
    account_id = client.get("/v1/auth/me").json()["id"]
    connection = run_async(client, partial(_create_active_connection, account_id))
    credential = {
        "access_token": "tok",
        "refresh_token": "rt",
        "expires_at_ms": int(time.time() * 1000) + 3_600_000,
        "token_type": "Bearer",
    }
    credential_blobs.write(
        credential_service_for(credential_key_for(account_id, connection.id)),
        "default",
        json.dumps(credential),
    )
    return account_id


class DispatchCounter:
    """Stands in for the provider call; every answer carries a fresh id."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def __call__(self, body: dict[str, Any]):
        from types import SimpleNamespace

        self.calls.append(dict(body))
        return SimpleNamespace(model_dump=lambda: chat_response(f"live-{len(self.calls)}"))


class ScriptedDispatch:
    """Stands in for the provider call: each call raises or returns the next scripted outcome."""

    def __init__(self, *outcomes: Exception | dict[str, Any]) -> None:
        self._outcomes = list(outcomes)
        self.calls: list[dict[str, Any]] = []

    async def __call__(self, body: dict[str, Any]):
        from types import SimpleNamespace

        self.calls.append(dict(body))
        outcome = self._outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return SimpleNamespace(model_dump=lambda: outcome)


@contextmanager
def server_errors_as_responses(client: TestClient) -> Iterator[None]:
    """Let an unhandled exception come back as the app's 500 instead of raising in the test."""
    transport = client._transport  # type: ignore[attr-defined]
    previous = transport.raise_server_exceptions
    transport.raise_server_exceptions = False
    try:
        yield
    finally:
        transport.raise_server_exceptions = previous
