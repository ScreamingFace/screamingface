"""Bounded availability checks for public citations, never score verification."""

from __future__ import annotations

import asyncio
import ipaddress
from collections.abc import Awaitable, Callable, Sequence

import httpx

from .source_dns import resolve_public_host

Resolver = Callable[[str, int], Awaitable[Sequence[str]]]
_REDIRECTS = {301, 302, 303, 307, 308}


class UnsafeSource(ValueError):
    """A citation is not a public HTTP(S) destination."""


def _public_address(value: str) -> bool:
    address = ipaddress.ip_address(value)
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped:
        address = address.ipv4_mapped
    # WHY: Azure's platform VIP is classified as global, but serves the VM host.
    return (
        address.is_global
        and not address.is_multicast
        and not address.is_reserved
        and str(address) != "168.63.129.16"
    )


def _validate_url(url: httpx.URL) -> None:
    if (
        url.scheme not in ("http", "https")
        or not url.host
        or url.userinfo
        or url.port not in (None, 80, 443)
    ):
        raise UnsafeSource("unsupported source URL")
    try:
        ipaddress.ip_address(url.host)
    except ValueError:
        return
    if not _public_address(url.host):
        raise UnsafeSource("non-public address")


class PublicSourceTransport(httpx.AsyncBaseTransport):
    def __init__(
        self,
        *,
        resolver: Resolver = resolve_public_host,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._resolver = resolver
        # WHY: no proxy credentials/environment and no cross-host TLS connection reuse
        # after replacing hostnames with IPs (different hosts can share an address).
        self._transport = transport or httpx.AsyncHTTPTransport(
            trust_env=False, limits=httpx.Limits(max_keepalive_connections=0)
        )

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        url = request.url
        _validate_url(url)
        addresses = await self._resolver(
            url.host, url.port or (443 if url.scheme == "https" else 80)
        )
        if not addresses or not all(_public_address(address) for address in addresses):
            raise UnsafeSource("non-public DNS answer")
        return await self._connect(request, addresses)

    async def _connect(self, request: httpx.Request, addresses: Sequence[str]) -> httpx.Response:
        # INVARIANT: connect to the validated IP, never re-resolve after validation.
        # Preserve HTTP Host and TLS certificate/SNI validation for the original host.
        error: httpx.HTTPError = httpx.ConnectError("source connection failed")
        for address in addresses:
            pinned = httpx.Request(
                request.method,
                request.url.copy_with(host=address),
                headers=request.headers,
                extensions={**request.extensions, "sni_hostname": request.url.host},
            )
            try:
                return await self._transport.handle_async_request(pinned)
            except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
                # WHY: one unreachable address (e.g. IPv6 on an IPv4-only host)
                # must not hide a reachable alternate. The probe deadline covers
                # every attempt; HTTP responses and read failures are not retried.
                error = exc
        raise error

    async def aclose(self) -> None:
        await self._transport.aclose()


async def _follow_source(url: str, client: httpx.AsyncClient) -> bool:
    target = httpx.URL(url)
    for _ in range(6):
        _validate_url(target)
        # WHY: GET avoids servers which reject HEAD. Streaming and manual redirects
        # close every body unread, even enormous redirect/error pages.
        async with client.stream("GET", target, follow_redirects=False, timeout=5) as response:
            if response.status_code not in _REDIRECTS:
                return response.is_success
            location = response.headers.get("location")
            if not location:
                return False
            target = target.join(location)
    return False


async def probe_source(url: str, client: httpx.AsyncClient, *, deadline: float = 15) -> bool:
    try:
        # INVARIANT: DNS and the entire redirect chain share one finite deadline.
        async with asyncio.timeout(deadline):
            return await _follow_source(url, client)
    except (httpx.HTTPError, httpx.InvalidURL, ValueError, OSError, TimeoutError):
        # A failed check is not proof of deletion. Never store/log URL-bearing errors.
        return False
