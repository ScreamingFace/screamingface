"""The httpx transport that enforces the url4 source guard on every hop (spec F1b, ``OME-1544``).

:class:`~url4.io.http.HttpIOLayer` builds its OWNED client on :class:`GuardedTransport`, so every
request it sends — the first one and each redirect hop httpx follows — passes through
:meth:`GuardedTransport.handle_async_request` before a socket is opened.

FEATURE: url4 source fetch destination guard (OME-1544, fixes OME-1704).
"""

from __future__ import annotations

import asyncio
import socket
from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
from dataclasses import dataclass

import httpx

from url4.core.errors import ResolutionError
from url4.io._body_decode import STEP, BodyDecoder, decoder_for
from url4.io._source_policy import (
    IPAddress,
    SourceGuard,
    check_destination,
    destination_blocked,
    literal_ip,
    too_large,
    vet_address,
)

Resolver = Callable[[str, int], Awaitable[Sequence[str]]]
"""``(host, port) -> addresses``: the DNS answers the guard vets before it connects."""

Origin = tuple[str, str, int | None]

FETCH_STATE = "url4.source_guard"
"""Request-extension key of the per-fetch :class:`FetchState`.

WHY an extension: httpx copies ``request.extensions`` (by reference) onto every redirect request
it builds, so one mutable state object follows the whole chain through the transport.
"""

_DEFAULT_PORTS = {"https": 443, "http": 80}

# Headers that describe the wire encoding of a body the transport has already decoded.
_ENCODING_HEADERS = ("content-encoding", "content-length")


@dataclass(slots=True)
class FetchState:
    """What the transport must know about the fetch a hop belongs to."""

    peer: bool = False
    previous_scheme: str | None = None
    trusted_first_hop: bool = False
    """Set by HttpIOLayer for a relative fetch: its first hop goes to the operator's base_url.

    INVARIANT: consumed by the first hop, so no redirect hop is ever trusted — not even one
    back into the base_url origin.
    """


async def system_resolver(host: str, port: int) -> Sequence[str]:
    """The operating system's answers for ``host``, de-duplicated, in resolver order."""
    infos = await asyncio.get_running_loop().getaddrinfo(host, port, type=socket.SOCK_STREAM)
    return list(dict.fromkeys(str(info[4][0]) for info in infos))


def _inner_transport() -> httpx.AsyncBaseTransport:
    # AIDEV-NOTE: tests replace this factory with a MockTransport to see the pinned request.
    return httpx.AsyncHTTPTransport(retries=0)


def origin_of(url: httpx.URL) -> Origin:
    return (url.scheme, url.host, url.port)


class GuardedTransport(httpx.AsyncBaseTransport):
    """Vet each hop, then connect to the vetted address with the original SNI and ``Host``.

    INVARIANT: no connection is opened to an address the policy has not vetted. A DNS name is
    resolved exactly once per hop, every answer is vetted, and the request is sent to the first
    answer as an IP literal — so a second DNS answer (rebinding) can never move it.
    INVARIANT: one connection pool per host name, so a TLS connection made with one name's SNI
    is never reused for another name that shares its address.
    """

    def __init__(
        self,
        guard: SourceGuard,
        *,
        resolver: Resolver = system_resolver,
        trusted: frozenset[Origin] = frozenset(),
    ) -> None:
        self._guard = guard
        self._resolver = resolver
        self._trusted = trusted
        self._pools: dict[str, httpx.AsyncBaseTransport] = {}

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        url = request.url
        state = request.extensions.get(FETCH_STATE)
        if not isinstance(state, FetchState):
            state = FetchState()
        # WHY identity: an encoded body would be inflated by httpx a whole chunk at a time; a
        # server that encodes anyway is decoded here in bounded steps (url4.io._body_decode).
        request.headers["Accept-Encoding"] = "identity"
        previous, state.previous_scheme = state.previous_scheme, url.scheme
        trusted, state.trusted_first_hop = state.trusted_first_hop, False
        if trusted and origin_of(url) in self._trusted:
            # WHY: the operator's own base_url origin (spec F1b leaves it out of the guard).
            outbound = request
        else:
            outbound = await self._pinned(request, state, previous)
        response = await self._pool(url.host).handle_async_request(outbound)
        stream = response.stream
        if not isinstance(stream, httpx.AsyncByteStream):
            # INVARIANT: fail closed — a body the cap cannot wrap is never handed on.
            raise TypeError("the connection returned a body stream that is not async")
        try:
            decoder, decodes = decoder_for(response.headers)
        except ResolutionError:
            await stream.aclose()
            raise
        headers = response.headers.copy()
        if decodes:
            # WHY: the body leaves here decoded, so httpx must not decode it a second time.
            for name in _ENCODING_HEADERS:
                headers.pop(name, None)
        return httpx.Response(
            response.status_code,
            headers=headers,
            stream=_CappedStream(stream, self._guard.max_bytes, decoder),
            extensions=response.extensions,
        )

    async def _pinned(
        self, request: httpx.Request, state: FetchState, previous: str | None
    ) -> httpx.Request:
        """``request`` re-addressed to its vetted IP, keeping SNI and ``Host``."""
        url = request.url
        address = check_destination(
            url.scheme, url.host, self._guard, peer=state.peer, previous_scheme=previous
        )
        extensions = dict(request.extensions)
        if address is None:
            address = await self._resolve(url.host, url.port or _DEFAULT_PORTS[url.scheme])
            extensions["sni_hostname"] = url.host
        return httpx.Request(
            request.method,
            url.copy_with(host=str(address)),
            headers=request.headers,
            stream=request.stream,
            extensions=extensions,
        )

    async def _resolve(self, host: str, port: int) -> IPAddress:
        try:
            answers = list(await self._resolver(host, port))
        except OSError as exc:
            raise httpx.ConnectError(f"cannot resolve {host!r}: {exc}") from exc
        if not answers:
            raise httpx.ConnectError(f"{host!r} resolved to no address")
        vetted: list[IPAddress] = []
        for answer in answers:
            address = literal_ip(answer)
            if address is None:
                raise destination_blocked(f"{host!r} resolved to a non-address {answer!r}")
            vet_address(address, self._guard)
            vetted.append(address)
        return vetted[0]

    def _pool(self, host: str) -> httpx.AsyncBaseTransport:
        pool = self._pools.get(host)
        if pool is None:
            pool = self._pools[host] = _inner_transport()
        return pool

    async def aclose(self) -> None:
        pools, self._pools = list(self._pools.values()), {}
        for pool in pools:
            await pool.aclose()


class _CappedStream(httpx.AsyncByteStream):
    """A response stream, decoded in bounded steps, that aborts past ``limit`` bytes.

    WHY in the transport: httpx reads a redirect response's body itself before following it,
    so only the transport sees — and can bound — every body on the chain.
    INVARIANT: two counts, one ``limit``: RAW bytes off the wire (counted before decoding, so a
    body that decodes to nothing — empty deflate blocks, empty gzip members — still ends) and
    DECODED bytes handed on. Neither depends on ``Content-Length``/``Content-Encoding``, which
    the transport strips for httpx's sake only.
    INVARIANT: the decoder is fed at most :data:`STEP` raw bytes at a time, so zlib's
    ``unconsumed_tail`` never copies more than one step of a large network chunk.
    """

    def __init__(self, inner: httpx.AsyncByteStream, limit: int, decoder: BodyDecoder) -> None:
        self._inner = inner
        self._limit = limit
        self._decoder = decoder
        self._raw = 0
        self._seen = 0

    async def __aiter__(self) -> AsyncIterator[bytes]:
        async for chunk in self._inner:
            self._raw += len(chunk)
            if self._raw > self._limit:
                raise too_large(self._limit)
            for start in range(0, len(chunk), STEP):
                for piece in self._decoder.feed(chunk[start : start + STEP]):
                    yield self._count(piece)

    def _count(self, piece: bytes) -> bytes:
        self._seen += len(piece)
        if self._seen > self._limit:
            raise too_large(self._limit)
        return piece

    async def aclose(self) -> None:
        await self._inner.aclose()


__all__ = ["FETCH_STATE", "FetchState", "GuardedTransport", "Resolver", "system_resolver"]
