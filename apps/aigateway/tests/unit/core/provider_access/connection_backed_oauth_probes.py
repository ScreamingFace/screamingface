"""Probes shared by the Connection-backed OAuth-flow suites (OME-1208, S2'b2).

# AIDEV-NOTE: helpers only — the `legacy`/`migrated` harness fixtures stay explicit in each suite.
# The token factories are the ownership suite's idiom (`test_profile_oauth_flow_ownership.py`)
# re-expressed here so these suites depend on no other test module.
"""

from __future__ import annotations

import asyncio
import json
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import httpx
from provider_access_harness import PROVIDER

from aigateway.core.oauth.store import OAuthConnectionStore
from aigateway.core.provider_access import PairAuthorityStore

SENTINEL = "SENSITIVE-PROVIDER-BODY"


def token_factory(
    token: str,
    *,
    stall: threading.Event | None = None,
    started: threading.Event | None = None,
) -> Any:
    """A provider token endpoint that answers `token` (optionally after `stall` is released)."""

    async def token_handler(_request: httpx.Request) -> httpx.Response:
        if started is not None:
            started.set()
        if stall is not None and not await asyncio.to_thread(stall.wait, 5):
            raise TimeoutError("OAuth exchange was not released")
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


def failing_token_factory(*, sentinel: str = SENTINEL) -> Any:
    """A provider-side failure whose body carries a sentinel that must never leak."""

    async def token_handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"error": "invalid_grant", "detail": sentinel})

    return lambda: httpx.AsyncClient(
        transport=httpx.MockTransport(token_handler), timeout=httpx.Timeout(5.0)
    )


def use_tokens(harness: Any, token: str) -> None:
    harness.client.app.state.anthropic_http_factory = token_factory(token)


def use_failing_exchange(harness: Any, *, sentinel: str = SENTINEL) -> None:
    harness.client.app.state.anthropic_http_factory = failing_token_factory(sentinel=sentinel)


def start(harness: Any, name: str = "default", **body: Any) -> httpx.Response:
    return harness.client.post(f"/v1/auth/{PROVIDER}/profiles", json={"name": name, **body})


def callback(harness: Any, state: str, code: str = "code-1") -> httpx.Response:
    return harness.client.get(
        f"/v1/auth/{PROVIDER}/callback",
        params={"code": code, "state": state},
        follow_redirects=False,
    )


def status(harness: Any, name: str = "default") -> httpx.Response:
    return harness.client.get(f"/v1/auth/{PROVIDER}/profiles/{name}/status")


def pending_entry(harness: Any, state: str) -> Any:
    return harness.client.app.state.pending_auth.peek(state)


def access_token_of(blob: str | None) -> str | None:
    return None if blob is None else json.loads(blob).get("access_token")


def detach_effective(harness: Any, connection_id: str) -> None:
    """The post-delete shape of a migrated pair: the row revoked, the marker naming NO effective."""
    store = OAuthConnectionStore()
    row = harness.call(store.get, harness.account_id, connection_id)
    harness.call(store.mark_revoked, row)
    markers = PairAuthorityStore()
    current = harness.call(markers.read, harness.account_id, PROVIDER)
    harness.call(
        markers.advance,
        harness.account_id,
        PROVIDER,
        expected_generation=current.generation,
        migration_state="migrated",
    )


@contextmanager
def server_errors_as_responses(client: Any) -> Iterator[None]:
    """Let a 500 reach the assertions instead of re-raising inside the TestClient."""
    transport = getattr(client, "_transport")
    previous = transport.raise_server_exceptions
    transport.raise_server_exceptions = False
    try:
        yield
    finally:
        transport.raise_server_exceptions = previous


__all__ = [
    "SENTINEL",
    "access_token_of",
    "callback",
    "detach_effective",
    "failing_token_factory",
    "pending_entry",
    "server_errors_as_responses",
    "start",
    "status",
    "token_factory",
    "use_failing_exchange",
    "use_tokens",
]
