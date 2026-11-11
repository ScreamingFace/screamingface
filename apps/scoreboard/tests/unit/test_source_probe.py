import asyncio

import httpx
import pytest

from scoreboard.source_probe import PublicSourceTransport, probe_source

PUBLIC = "93.184.216.34"


async def public_dns(host, port):
    return [PUBLIC]


def client_for(handler, resolver=public_dns):
    return httpx.AsyncClient(
        transport=PublicSourceTransport(resolver=resolver, transport=httpx.MockTransport(handler)),
        trust_env=False,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status,expected",
    [
        (200, True),
        (204, True),
        (404, False),
        (410, False),
        (403, False),
        (429, False),
        (503, False),
    ],
)
async def test_http_outcomes(status, expected):
    async with client_for(lambda req: httpx.Response(status)) as client:
        assert await probe_source("https://source.example/results", client) is expected


@pytest.mark.asyncio
async def test_pinned_address_keeps_host_and_tls_name():
    seen = []

    def handler(req):
        seen.append(req)
        return httpx.Response(200)

    async with client_for(handler) as client:
        assert await probe_source("https://source.example/results#table", client)
    assert len(seen) == 1
    assert seen[0].url.host == PUBLIC
    assert seen[0].headers["host"] == "source.example"
    assert seen[0].extensions["sni_hostname"] == "source.example"
    assert seen[0].method == "GET"
    assert "authorization" not in seen[0].headers


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "address",
    ["127.0.0.1", "10.0.0.1", "169.254.169.254", "::1", "::ffff:127.0.0.1", "224.0.0.1", "0.0.0.0"],
)
async def test_private_dns_answers_are_never_contacted(address):
    async def resolve(host, port):
        return [PUBLIC, address]

    def forbidden(req):
        pytest.fail("unsafe connection")

    async with client_for(forbidden, resolve) as client:
        assert await probe_source("https://source.example/results", client) is False


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "http://user:password@example.org/",
        "http://127.0.0.1",
        "//example.org/x",
        "https://example.org:8443/",
        "http://[::1]/",
    ],
)
async def test_unsupported_targets_are_not_requested(url):
    def forbidden(req):
        pytest.fail("unsafe connection")

    async with client_for(forbidden) as client:
        assert await probe_source(url, client) is False


@pytest.mark.asyncio
async def test_redirect_to_private_host_is_rejected():
    seen = []

    async def resolve(host, port):
        return ["127.0.0.1"] if host == "private.example" else [PUBLIC]

    def handler(req):
        seen.append(req)
        return httpx.Response(302, headers={"location": "http://private.example/admin"})

    async with client_for(handler, resolve) as client:
        assert await probe_source("https://source.example/results", client) is False
    assert len(seen) == 1


@pytest.mark.asyncio
async def test_relative_redirect_and_loop_limit():
    seen = []

    def handler(req):
        seen.append(req)
        return (
            httpx.Response(302, headers={"location": "/new"})
            if req.url.path == "/old"
            else httpx.Response(200)
        )

    async with client_for(handler) as client:
        assert await probe_source("https://source.example/old", client) is True
    assert [req.url.path for req in seen] == ["/old", "/new"]
    seen.clear()

    def looping(req):
        seen.append(req)
        return httpx.Response(302, headers={"location": "/loop"})

    async with client_for(looping) as client:
        assert await probe_source("https://source.example/loop", client) is False
    assert len(seen) <= 6


@pytest.mark.asyncio
async def test_network_error_and_overall_deadline():
    def failing(req):
        raise httpx.ConnectError("cannot connect")

    async with client_for(failing) as client:
        assert await probe_source("https://source.example/", client) is False

    async def slow_dns(host, port):
        await asyncio.sleep(1)
        return [PUBLIC]

    async with client_for(lambda req: httpx.Response(200), slow_dns) as client:
        assert await probe_source("https://source.example/", client, deadline=0.01) is False


@pytest.mark.asyncio
async def test_redirect_and_final_bodies_are_not_consumed():
    class UnreadableBody(httpx.AsyncByteStream):
        async def __aiter__(self):
            pytest.fail("page body was downloaded")
            yield b""

    def handler(req):
        return (
            httpx.Response(302, headers={"location": "/new"}, stream=UnreadableBody())
            if req.url.path == "/old"
            else httpx.Response(200, stream=UnreadableBody())
        )

    async with client_for(handler) as client:
        assert await probe_source("https://source.example/old", client)


@pytest.mark.asyncio
@pytest.mark.parametrize("address", ["168.63.129.16", "::ffff:168.63.129.16"])
async def test_azure_platform_address_is_not_a_public_source(address):
    async def resolve(host, port):
        return [address]

    def forbidden(req):
        pytest.fail("Azure platform service must not be contacted")

    async with client_for(forbidden, resolve) as client:
        assert await probe_source("https://source.example/results", client) is False
