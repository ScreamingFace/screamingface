"""One reused HTTP client per configured endpoint, opened on first use and closed at shutdown.

# FEATURE: hosted BYOM Unit 1 — chats to one endpoint share one client and its bounded connection
# pool, instead of opening a client and a connection for every call.
# INVARIANT: the client verifies certificates, follows no redirect and reads no proxy or CA
# setting from the environment, as the per-call client did.
# INVARIANT: once shutdown closed it, a chat gets a safe 502 and opens no new client.
# INVARIANT: the shared client keeps no cookie, so one account's upstream session never rides on
# another account's request.
# INVARIANT: shutdown closes every endpoint's client, even when another endpoint's close fails,
# the close itself is cancelled or the whole shutdown is cancelled.
# INVARIANT: a close error never reaches the log as text; it may carry the endpoint's origin.
"""

from __future__ import annotations

import asyncio
import gc
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


def test_an_answer_cookie_never_reaches_another_account(
    opened: list[httpx.AsyncClient],
) -> None:
    registry, plugin, _ = _installed()
    sent: list[httpx.Request] = []

    def answer(request: httpx.Request) -> httpx.Response:
        sent.append(request)
        cookie = f"session=from-call-{len(sent)}; Path=/"
        return httpx.Response(200, json=COMPLETION, headers={"Set-Cookie": cookie})

    cast(Any, plugin)._transport = httpx.MockTransport(answer)

    async def one_chat_each() -> None:
        for account in (ACCOUNT_A, ACCOUNT_B):
            body = {**chat_body(ENDPOINT_A), "api_key": KEY[account]}
            assert await plugin.chat_completion(body) == COMPLETION
        await close_remote_endpoints(registry)

    asyncio.run(one_chat_each())

    assert len(opened) == 1
    assert [request.headers.get("cookie") for request in sent] == [None, None]
    # WHY the jar too: a kept cookie would also grow for the whole life of the process.
    assert len(opened[0].cookies) == 0


class _Closing(httpx.AsyncBaseTransport):
    """An upstream transport whose close is recorded, and can fail or wait until released."""

    def __init__(self, *, fail: bool = False, hold: bool = False) -> None:
        self.fail, self.hold = fail, hold
        self.entered, self.released = asyncio.Event(), asyncio.Event()
        self.finished = 0

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=COMPLETION)

    async def aclose(self) -> None:
        self.entered.set()
        if self.fail:
            raise RuntimeError("the connection pool failed to close")
        if self.hold:
            await self.released.wait()
        self.finished += 1


def test_one_failed_close_leaves_no_other_endpoint_open(caplog: pytest.LogCaptureFixture) -> None:
    registry = ProviderRegistry()
    install_remote_endpoints(registry, parse_remote_endpoint_config(two_endpoint_document()))
    plugins = [p for p in registry.all() if isinstance(p, RemoteEndpointPlugin)]
    # WHY the first in sweep order fails: only then can a stopped sweep skip the other one.
    upstreams = [_Closing(fail=True), _Closing()]
    for plugin, upstream in zip(plugins, upstreams, strict=True):
        cast(Any, plugin)._transport = upstream

    async def chat_then_shut_down() -> None:
        for plugin in plugins:
            body = {**chat_body(plugin.custom_llm_provider), "api_key": KEY[ACCOUNT_A]}
            assert await plugin.chat_completion(body) == COMPLETION
        await close_remote_endpoints(registry)

    asyncio.run(chat_then_shut_down())

    assert upstreams[0].entered.is_set() and upstreams[1].finished == 1
    assert plugins[0].custom_llm_provider in caplog.text


def test_a_cancelled_close_still_finishes_and_a_repeat_waits_for_it() -> None:
    upstream = _Closing(hold=True)
    owner = transport.EndpointClient()
    owner.open(upstream)

    async def cancel_then_repeat() -> None:
        first = asyncio.ensure_future(owner.aclose())
        await asyncio.wait_for(upstream.entered.wait(), timeout=5)
        first.cancel()
        with pytest.raises(asyncio.CancelledError):
            await first
        repeat = asyncio.ensure_future(owner.aclose())
        await asyncio.sleep(0.01)
        # INVARIANT: the repeat waits for the close already running rather than returning early.
        assert not repeat.done()
        upstream.released.set()
        await asyncio.wait_for(repeat, timeout=5)

    asyncio.run(cancel_then_repeat())

    assert upstream.finished == 1


def test_a_cancelled_shutdown_still_closes_every_endpoint() -> None:
    registry = ProviderRegistry()
    install_remote_endpoints(registry, parse_remote_endpoint_config(two_endpoint_document()))
    plugins = [p for p in registry.all() if isinstance(p, RemoteEndpointPlugin)]
    upstreams = [_Closing(hold=True), _Closing(hold=True)]
    for plugin, upstream in zip(plugins, upstreams, strict=True):
        cast(Any, plugin)._transport = upstream

    async def chat_then_cancel_the_shutdown() -> None:
        for plugin in plugins:
            body = {**chat_body(plugin.custom_llm_provider), "api_key": KEY[ACCOUNT_A]}
            assert await plugin.chat_completion(body) == COMPLETION
        sweep = asyncio.ensure_future(close_remote_endpoints(registry))
        await asyncio.wait_for(upstreams[0].entered.wait(), timeout=5)
        sweep.cancel()
        with pytest.raises(asyncio.CancelledError):
            await sweep
        for upstream in upstreams:
            upstream.released.set()
        # WHY poll: nothing waits for the closes any more; each must finish on its own.
        for _ in range(100):
            if all(upstream.finished for upstream in upstreams):
                break
            await asyncio.sleep(0.01)

    asyncio.run(chat_then_cancel_the_shutdown())

    assert [upstream.finished for upstream in upstreams] == [1, 1]


class _FailingLater(_Closing):
    """An upstream transport whose close waits until released, then fails naming the origin."""

    async def aclose(self) -> None:
        self.entered.set()
        await self.released.wait()
        raise RuntimeError(f"the pool for {ORIGIN_A} failed to close")


def test_a_close_error_nobody_waits_for_is_never_printed() -> None:
    upstream = _FailingLater()
    reported: list[dict[str, Any]] = []

    async def cancel_the_wait_then_fail() -> None:
        loop = asyncio.get_running_loop()
        loop.set_exception_handler(lambda _, context: reported.append(context))
        owner = transport.EndpointClient()
        owner.open(upstream)
        waiting = asyncio.ensure_future(owner.aclose())
        await asyncio.wait_for(upstream.entered.wait(), timeout=5)
        waiting.cancel()
        with pytest.raises(asyncio.CancelledError):
            await waiting
        upstream.released.set()
        for _ in range(100):
            if cast(Any, owner)._closing.done():
                break
            await asyncio.sleep(0.01)
        assert cast(Any, owner)._closing.done()
        # WHY collect: asyncio reports an unread task error when the task is destroyed.
        del owner, waiting
        gc.collect()

    asyncio.run(cancel_the_wait_then_fail())

    # INVARIANT: asyncio never prints the close's error; its text may carry the origin.
    assert reported == []
