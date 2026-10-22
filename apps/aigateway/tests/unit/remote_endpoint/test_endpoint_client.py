"""One reused HTTP client per configured endpoint, opened on first use and closed at shutdown.

# FEATURE: hosted BYOM Unit 1 — chats to one endpoint share one client and its bounded connection
# pool, instead of opening a client and a connection for every call.
# INVARIANT: the client verifies certificates, follows no redirect and reads no proxy or CA
# setting from the environment, as the per-call client did.
# INVARIANT: once shutdown closed it, a chat gets a safe 502 and opens no new client.
"""

from __future__ import annotations

import asyncio
import ssl
from typing import Any, cast

import httpx
import pytest
from fastapi import HTTPException

from aigateway.core.registry import ProviderRegistry
from aigateway.plugins.remote_endpoint import transport
from aigateway.plugins.remote_endpoint.definitions import parse_remote_endpoint_config
from aigateway.plugins.remote_endpoint.plugin import RemoteEndpointPlugin
from aigateway.provider_composition import close_remote_endpoints, install_remote_endpoints

from .conftest import PEER, Harness, chat, chat_body, echo_of, put_key, tenant_headers
from .fixtures import (
    ACCOUNT_A,
    ACCOUNT_B,
    CHAT_PATH,
    ENDPOINT_A,
    ENDPOINT_B,
    ORIGIN_A,
    two_endpoint_document,
)

KEY = {ACCOUNT_A: "sk-alice-on-a-pool-0001", ACCOUNT_B: "sk-bob-on-a-pool-0001"}
COMPLETION = {
    "object": "chat.completion",
    "choices": [
        {"index": 0, "message": {"role": "assistant", "content": "ok"}, "finish_reason": "stop"}
    ],
}


@pytest.fixture
def opened(monkeypatch: pytest.MonkeyPatch) -> list[httpx.AsyncClient]:
    """Every client the adapter opens, in order."""
    clients: list[httpx.AsyncClient] = []
    real = transport._open_client

    def recording(upstream: httpx.AsyncBaseTransport | None) -> httpx.AsyncClient:
        clients.append(real(upstream))
        return clients[-1]

    monkeypatch.setattr(transport, "_open_client", recording)
    return clients


def test_overlapping_chats_share_one_client_that_shutdown_closes(
    byom: Harness, opened: list[httpx.AsyncClient]
) -> None:
    with byom.start(two_endpoint_document()) as client:
        for account in (ACCOUNT_A, ACCOUNT_B):
            assert put_key(client, account, ENDPOINT_A, KEY[account]).status_code == 200
        byom.upstream.calls.clear()
        # Both chats must be in flight at once, or the fake upstream's barrier times out.
        byom.upstream.expect_overlap(2)

        async def overlap() -> list[httpx.Response]:
            asgi = httpx.ASGITransport(app=client.app, client=PEER)
            async with httpx.AsyncClient(transport=asgi, base_url="http://testserver") as http:
                return await asyncio.gather(
                    *(
                        http.post(
                            "/v1/chat/completions",
                            json=chat_body(ENDPOINT_A),
                            headers=tenant_headers(account),
                        )
                        for account in (ACCOUNT_A, ACCOUNT_B)
                    )
                )

        assert client.portal is not None
        overlapping = client.portal.call(overlap)
        byom.upstream.expect_overlap(0)
        later = chat(client, ACCOUNT_A, ENDPOINT_A)
        assert len(opened) == 1 and not opened[0].is_closed

    # INVARIANT: sharing the client shares no key: each chat still carries its own account's key.
    assert [echo_of(r) for r in (*overlapping, later)] == [
        f"{ORIGIN_A}{CHAT_PATH}|Bearer {KEY[account]}"
        for account in (ACCOUNT_A, ACCOUNT_B, ACCOUNT_A)
    ]
    assert opened[0].is_closed


def test_each_endpoint_opens_its_own_client(byom: Harness, opened: list[httpx.AsyncClient]) -> None:
    with byom.start(two_endpoint_document()) as client:
        for provider in (ENDPOINT_A, ENDPOINT_B):
            assert put_key(client, ACCOUNT_A, provider, KEY[ACCOUNT_A]).status_code == 200
            assert chat(client, ACCOUNT_A, provider).status_code == 200

    assert len(opened) == 2 and opened[0] is not opened[1]
    assert all(c.is_closed for c in opened)


def _installed() -> tuple[ProviderRegistry, RemoteEndpointPlugin, list[httpx.Request]]:
    registry = ProviderRegistry()
    install_remote_endpoints(registry, parse_remote_endpoint_config(two_endpoint_document()))
    plugin = registry.get(ENDPOINT_A)
    assert isinstance(plugin, RemoteEndpointPlugin)
    sent: list[httpx.Request] = []

    def answer(request: httpx.Request) -> httpx.Response:
        sent.append(request)
        return httpx.Response(200, json=COMPLETION)

    # cast: the harness injects its fake upstream the same way.
    cast(Any, plugin)._transport = httpx.MockTransport(answer)
    return registry, plugin, sent


@pytest.mark.parametrize("used_before", [False, True])
def test_a_chat_after_shutdown_is_a_safe_502_that_opens_no_client(
    opened: list[httpx.AsyncClient], used_before: bool
) -> None:
    registry, plugin, sent = _installed()
    body = {**chat_body(ENDPOINT_A), "api_key": KEY[ACCOUNT_A]}

    async def scenario() -> HTTPException:
        if used_before:
            assert await plugin.chat_completion(body) == COMPLETION
        await close_remote_endpoints(registry)
        # WHY twice: shutdown may close an app whose endpoints were already closed.
        await close_remote_endpoints(registry)
        with pytest.raises(HTTPException) as caught:
            await plugin.chat_completion(body)
        return caught.value

    refused = asyncio.run(scenario())

    assert refused.status_code == 502
    assert cast(dict[str, str], refused.detail)["code"] == "provider_unavailable"
    assert KEY[ACCOUNT_A] not in str(refused.detail)
    assert len(sent) == len(opened) == int(used_before)
    assert all(c.is_closed for c in opened)


def test_the_client_verifies_certificates_and_ignores_the_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HTTPS_PROXY", "http://proxy.invalid:3128")
    monkeypatch.setenv("SSL_CERT_FILE", "/nonexistent/ca.pem")
    client = transport.EndpointClient().open(None)
    try:
        # cast: the pool's settings are only reachable through httpx internals.
        pool = cast(Any, client)._transport._pool
        context: ssl.SSLContext = pool._ssl_context
        assert (context.verify_mode, context.check_hostname) == (ssl.CERT_REQUIRED, True)
        assert cast(Any, client)._mounts == {}
        assert client.follow_redirects is False
        # INVARIANT: the pool is bounded; core admission still caps concurrent calls first.
        assert pool._max_connections is not None
        assert pool._retries == 0
    finally:
        asyncio.run(client.aclose())
