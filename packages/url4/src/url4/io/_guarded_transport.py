"""The httpx transport that enforces the url4 source guard on every hop (spec F1b, ``OME-1544``).

:class:`~url4.io.http.HttpIOLayer` builds its OWNED client on :class:`GuardedTransport`, so every
request it sends — the first one and each redirect hop httpx follows — passes through
:meth:`GuardedTransport.handle_async_request` before a socket is opened.

FEATURE: url4 source fetch destination guard (OME-1544, fixes OME-1704).
"""

from __future__ import annotations

import asyncio
import socket
import time
from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
from dataclasses import dataclass

import httpx

from url4.core.errors import ResolutionError
from url4.io._body_decode import STEP, BodyDecoder, decoder_for
from url4.io._host_pools import HostPools, Lease
from url4.io._source_policy import (
    IPAddress,
    SourceGuard,
    check_destination,
    credentials_refused,
    destination_blocked,
    has_userinfo,
    literal_ip,
    source_timeout,
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

# AIDEV-NOTE: the guard's monotonic clock; tests replace it to make deadlines deterministic.
_now = time.monotonic


def deadline_in(seconds: float) -> float:
    """The absolute deadline ``seconds`` from now, on the guard's clock (OME-1720)."""
    return _now() + seconds


def past(deadline: float | None) -> bool:
    """Whether ``deadline`` (``None``: no deadline) has been reached."""
    return deadline is not None and _now() >= deadline


MAX_HOST_POOLS = 32
"""The most per-host connection pools one transport retains (OME-1719); LRU past it."""

MAX_ADDRESS_ATTEMPTS = 3
"""The most vetted DNS answers one hop tries before its connection failure surfaces (OME-1718).

WHY bounded: each attempt may wait the full connect timeout; the total deadline caps the sum,
but a short list keeps a dead name from eating that whole budget one address at a time.
"""

# The failures httpx raises only while OPENING a connection — before a byte of the request is
# written — so trying the next vetted address can never resend a request.
_CONNECT_PHASE = (httpx.ConnectError, httpx.ConnectTimeout)

# Headers that describe the wire encoding of a body the transport has already decoded.
_ENCODING_HEADERS = ("content-encoding", "content-length")


@dataclass(slots=True)
class FetchState:
    """What the transport must know about the fetch a hop belongs to."""

    peer: bool = False
    previous_scheme: str | None = None
    deadline: float | None = None
    """The fetch's ONE absolute deadline (:func:`deadline_in`), shared by every redirect hop.

    INVARIANT (OME-1720): body processing, decoding included, checkpoints against it.
    """
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
    resolved exactly once per hop, EVERY answer is vetted before the first attempt, and the
    request is sent to a vetted answer as an IP literal — so a second DNS answer (rebinding)
    can never move it.
    INVARIANT (OME-1718): a connection-phase failure (``ConnectError``/``ConnectTimeout``, i.e.
    nothing was sent) falls back to the next vetted answer, at most
    :data:`MAX_ADDRESS_ATTEMPTS` in all; any later failure is never retried.
    INVARIANT: one connection pool per host name, so a TLS connection made with one name's SNI
    is never reused for another name that shares its address — and at most ``max_hosts`` of
    them retained (:mod:`url4.io._host_pools`), none closed under a request in flight.
    """

    def __init__(
        self,
        guard: SourceGuard,
        *,
        resolver: Resolver = system_resolver,
        trusted: frozenset[Origin] = frozenset(),
        max_hosts: int = MAX_HOST_POOLS,
    ) -> None:
        self._guard = guard
        self._resolver = resolver
        self._trusted = trusted
        # WHY a lambda: tests replace the module-level factory after this transport is built.
        self._pools = HostPools(lambda: _inner_transport(), max_hosts)

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
            attempts = [request]
        else:
            attempts = await self._pinned(request, state, previous)
        lease = await self._acquire(url.host, state.deadline)
        try:
            response = await _first_connected(lease.transport, attempts)
            stream = _async_or_close(response.stream)
            await _refuse_credentialed_location(response, stream)
            decoder, decodes = await _decoder_or_close(response.headers, stream)
        except BaseException:
            # WHY BaseException: a cancelled attempt must give its pool back too.
            await lease.release()
            raise
        headers = response.headers.copy()
        if decodes:
            # WHY: the body leaves here decoded, so httpx must not decode it a second time.
            for name in _ENCODING_HEADERS:
                headers.pop(name, None)
        return httpx.Response(
            response.status_code,
            headers=headers,
            stream=_CappedStream(
                stream, self._guard.max_bytes, decoder, lease, deadline=state.deadline
            ),
            extensions=response.extensions,
        )

    async def _acquire(self, host: str, deadline: float | None) -> Lease:
        # INVARIANT (review 3): waiting for a pool-close slot is bounded by the fetch deadline.
        try:
            return await self._pools.acquire(
                host, timeout=None if deadline is None else deadline - _now()
            )
        except TimeoutError as exc:
            raise source_timeout(
                "waiting for a per-host pool to close passed the total deadline"
            ) from exc

    async def _pinned(
        self, request: httpx.Request, state: FetchState, previous: str | None
    ) -> list[httpx.Request]:
        """``request`` re-addressed to each vetted IP to try, in order, keeping SNI and ``Host``."""
        url = request.url
        address = check_destination(
            url.scheme,
            url.host,
            self._guard,
            peer=state.peer,
            previous_scheme=previous,
            credentials=bool(url.userinfo),
        )
        extensions = dict(request.extensions)
        if address is None:
            addresses = await self._resolve(url.host, url.port or _DEFAULT_PORTS[url.scheme])
            extensions["sni_hostname"] = url.host
        else:
            addresses = [address]
        return [
            httpx.Request(
                request.method,
                url.copy_with(host=str(vetted)),
                headers=request.headers,
                stream=request.stream,
                extensions=extensions,
            )
            for vetted in addresses[:MAX_ADDRESS_ATTEMPTS]
        ]

    async def _resolve(self, host: str, port: int) -> list[IPAddress]:
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
        return vetted

    async def aclose(self) -> None:
        await self._pools.aclose()


def _async_or_close(stream: httpx.SyncByteStream | httpx.AsyncByteStream) -> httpx.AsyncByteStream:
    if isinstance(stream, httpx.AsyncByteStream):
        return stream
    # INVARIANT: fail closed — a body the cap cannot wrap is never handed on, and it is closed
    # first so its connection goes back to the pool (PR #1555 review).
    close = getattr(stream, "close", None)
    if callable(close):
        close()
    raise TypeError("the connection returned a body stream that is not async")


async def _refuse_credentialed_location(
    response: httpx.Response, stream: httpx.AsyncByteStream
) -> None:
    """Refuse a redirect whose RAW ``Location`` carries userinfo, before httpx follows it.

    WHY here: httpx normalizes ``Location: https://@host`` (and ``//@host``) to an empty
    userinfo before the next hop reaches :meth:`GuardedTransport._pinned`, so only the raw
    header still shows the ``@`` (PR #1605 review 2).
    """
    if response.has_redirect_location and has_userinfo(response.headers["Location"]):
        await stream.aclose()
        raise credentials_refused()


async def _decoder_or_close(
    headers: httpx.Headers, stream: httpx.AsyncByteStream
) -> tuple[BodyDecoder, bool]:
    try:
        return decoder_for(headers)
    except ResolutionError:
        await stream.aclose()
        raise


async def _first_connected(
    pool: httpx.AsyncBaseTransport, attempts: Sequence[httpx.Request]
) -> httpx.Response:
    """The response from the first attempt whose connection opens (``attempts`` is non-empty).

    INVARIANT: only a connection-phase failure moves on to the next attempt; the last attempt's
    failure, and every failure after the request was sent, surfaces unchanged.
    """
    *fallbacks, last = attempts
    failed: list[str] = []
    for attempt in fallbacks:
        try:
            return await pool.handle_async_request(attempt)
        except _CONNECT_PHASE as exc:
            # WHY kept, not swallowed: the next vetted address is tried, and this failure is
            # recorded on the final error if none of them connects.
            failed.append(f"{attempt.url.host}: {type(exc).__name__}")
    try:
        return await pool.handle_async_request(last)
    except Exception as exc:
        # INVARIANT: the final error's type (so its x.* mapping) is unchanged; the earlier
        # attempts ride along as a note — vetted public addresses and exception class names
        # only, never a header, body or message.
        if failed:
            exc.add_note("earlier vetted addresses failed to connect: " + ", ".join(failed))
        raise


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
    INVARIANT (OME-1720): every raw chunk and every decompress call — even one that yields
    nothing, like an empty gzip member — is a checkpoint against the fetch deadline, and each
    raw step yields to the event loop so a cancellation or ``asyncio.timeout`` is delivered.
    """

    def __init__(
        self,
        inner: httpx.AsyncByteStream,
        limit: int,
        decoder: BodyDecoder,
        lease: Lease,
        *,
        deadline: float | None = None,
    ) -> None:
        self._inner = inner
        self._lease = lease
        self._deadline = deadline
        self._limit = limit
        self._decoder = decoder
        self._raw = 0
        self._seen = 0

    async def __aiter__(self) -> AsyncIterator[bytes]:
        async for chunk in self._inner:
            self._checkpoint()
            self._raw += len(chunk)
            if self._raw > self._limit:
                raise too_large(self._limit)
            for start in range(0, len(chunk), STEP):
                for piece in self._decoder.feed(chunk[start : start + STEP]):
                    self._checkpoint()
                    if piece:
                        yield self._count(piece)
                # WHY: decoding is synchronous; give a pending cancel/timeout its turn.
                await asyncio.sleep(0)

    def _checkpoint(self) -> None:
        if past(self._deadline):
            raise source_timeout("the source body passed the total deadline while being read")

    def _count(self, piece: bytes) -> bytes:
        self._seen += len(piece)
        if self._seen > self._limit:
            raise too_large(self._limit)
        return piece

    async def aclose(self) -> None:
        # INVARIANT: the lease is released even if closing the body fails, so the pool can close.
        try:
            await self._inner.aclose()
        finally:
            await self._lease.release()


__all__ = [
    "FETCH_STATE",
    "MAX_ADDRESS_ATTEMPTS",
    "MAX_HOST_POOLS",
    "FetchState",
    "GuardedTransport",
    "Resolver",
    "system_resolver",
]
