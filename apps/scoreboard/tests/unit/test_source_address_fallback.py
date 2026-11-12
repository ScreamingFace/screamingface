"""Availability checks must handle a reachable alternate DNS address."""

from __future__ import annotations

import asyncio
import time

import httpx
import pytest

from scoreboard.source_probe import PublicSourceTransport, probe_source

ADDRESSES = ["2606:4700:4700::1111", "1.1.1.1"]


@pytest.mark.asyncio
@pytest.mark.parametrize("error_type", [httpx.ConnectError, httpx.ConnectTimeout])
async def test_connection_failure_tries_other_validated_addresses(error_type):
    dns_calls = []
    requests = []

    async def resolve(host, port):
        dns_calls.append((host, port))
        return ADDRESSES

    def handle(request):
        requests.append(request)
        if request.url.host == ADDRESSES[0]:
            raise error_type("first address is unavailable")
        return httpx.Response(200)

    async with httpx.AsyncClient(
        transport=PublicSourceTransport(resolver=resolve, transport=httpx.MockTransport(handle))
    ) as client:
        assert await probe_source("https://source.example/table?q=1", client) is True
    assert dns_calls == [("source.example", 443)]
    assert [request.url.host for request in requests] == ADDRESSES
    assert all(request.headers["host"] == "source.example" for request in requests)
    assert all(request.extensions["sni_hostname"] == "source.example" for request in requests)
    assert all(request.url.path == "/table" and request.url.query == b"q=1" for request in requests)


@pytest.mark.asyncio
async def test_all_connection_failures_remain_unchecked():
    requested = []

    async def resolve(host, port):
        return ADDRESSES

    def handle(request):
        requested.append(request.url.host)
        raise httpx.ConnectError("unreachable")

    async with httpx.AsyncClient(
        transport=PublicSourceTransport(resolver=resolve, transport=httpx.MockTransport(handle))
    ) as client:
        assert await probe_source("https://source.example/", client) is False
    assert requested == ADDRESSES


@pytest.mark.asyncio
async def test_private_answer_prevents_contacting_even_a_working_public_address():
    async def resolve(host, port):
        return [*ADDRESSES, "169.254.169.254"]

    def forbidden(request):
        pytest.fail("all DNS answers must be safe before any connection")

    async with httpx.AsyncClient(
        transport=PublicSourceTransport(resolver=resolve, transport=httpx.MockTransport(forbidden))
    ) as client:
        assert await probe_source("https://source.example/", client) is False


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome", ["404", "503", "read_timeout"])
async def test_server_responses_and_read_errors_do_not_try_other_addresses(outcome):
    requested = []

    async def resolve(host, port):
        return ADDRESSES

    def handle(request):
        requested.append(request.url.host)
        if outcome == "read_timeout":
            raise httpx.ReadTimeout("server did not respond")
        return httpx.Response(int(outcome))

    async with httpx.AsyncClient(
        transport=PublicSourceTransport(resolver=resolve, transport=httpx.MockTransport(handle))
    ) as client:
        assert await probe_source("https://source.example/", client) is False
    assert requested == [ADDRESSES[0]]


@pytest.mark.asyncio
async def test_alternate_attempt_is_cancelled_at_the_original_deadline():
    requested = []
    cancelled = asyncio.Event()

    async def resolve(host, port):
        return ADDRESSES

    async def handle(request):
        requested.append(request.url.host)
        if request.url.host == ADDRESSES[0]:
            raise httpx.ConnectError("first address unavailable")
        try:
            await asyncio.sleep(10)
        except asyncio.CancelledError:
            cancelled.set()
            raise
        return httpx.Response(200)

    started = time.monotonic()
    async with httpx.AsyncClient(
        transport=PublicSourceTransport(resolver=resolve, transport=httpx.MockTransport(handle))
    ) as client:
        assert await probe_source("https://source.example/", client, deadline=0.05) is False
    assert requested == ADDRESSES
    assert cancelled.is_set()
    assert time.monotonic() - started < 1
