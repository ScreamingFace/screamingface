"""The httpx-backed :class:`~url4.io.layer.IOLayer` adapter (the ``run`` default).

The only module in the package that imports httpx. It owns a single, lazily
created :class:`httpx.AsyncClient` so the many fetches of one expression (a
fan-out's N sources plus its reducer) share one connection pool via keep-alive,
instead of paying a fresh TCP+TLS handshake per fetch. Its private helpers
``_guarded_transport`` / ``_source_policy`` hold the destination guard (spec F1b).
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable, Iterable
from email.utils import parsedate_to_datetime

import httpx

from url4.core.errors import ErrorCode, ResolutionError
from url4.io._guarded_transport import (
    FETCH_STATE,
    FetchState,
    GuardedTransport,
    Origin,
    Resolver,
    deadline_in,
    origin_of,
    past,
    system_resolver,
)
from url4.io._source_policy import (
    SourceGuard,
    check_url,
    redirect_limit,
    source_timeout,
    too_large,
)
from url4.io.close_once import CloseOnce
from url4.io.idempotency import idempotency_key, mark_answered
from url4.io.layer import FetchRequest, FetchResult
from url4.io.media import FetchedBytes, bare_media_type, peer_set, require_text

# Headers that describe the wire encoding of a body this adapter has already decoded.
_DECODED_AWAY = frozenset({"content-encoding", "content-length", "transfer-encoding"})


class HttpIOLayer:
    """A batteries-included :class:`~url4.io.layer.IOLayer` over httpx.

    :meth:`fetch` issues ``GET target`` (or ``GET base_url + target`` for a
    relative ``/path``) and returns the response body. A relative expression
    arrives already encoded as ``/claude?q=(ctx)!intent``, so a model backend is
    just a ``GET base_url/claude?q=…`` against the localhost node. A
    ``url4://`` target is translated to ``https://`` for transport (spec §3.5 —
    the URL4 scheme rides HTTPS on the wire). :meth:`fetch_ex` additionally
    reports the response's media type so collection parsing can be
    Content-Type-driven (spec §5.3.7), and :meth:`fetch_bytes` returns the raw
    body unmodified for binary sources (PNG, PDF). The text paths refuse a binary
    media type with ``unsupported_content_type`` rather than decode it. A
    request's ``;accept=`` annotation is sent as the ``Accept`` header.

    A single :class:`httpx.AsyncClient` is created on the first fetch and reused
    for the adapter's lifetime, so pooling / keep-alive apply across a fan-out.
    Call :meth:`aclose` (or use the adapter as an async context manager) to
    release it; :func:`~url4.run` closes the default adapter it creates. Pass
    your own ``client`` to control pooling, auth, or to inject a test transport —
    an injected client is used as-is and never closed here. Any HTTP failure
    surfaces as :class:`~url4.core.errors.ResolutionError`, permanent or transient
    by the Spec C §13.2.1 status classes, so a ``;retry=`` guard retries only what
    can succeed; a ``Retry-After`` is reported as ``ResolutionError.retry_after``.
    Inside a retrying guard every request carries the guard's ``Idempotency-Key``
    header, and every received response marks its target answered, so the next
    request to it gets a new key (:mod:`url4.io.idempotency`, "reuse until answered").

    The OWNED client is built on the destination guard (spec F1b, ``OME-1544``) configured by
    ``guard`` (:class:`SourceGuard`; strict defaults): ``https`` only, no loopback / private /
    link-local / CGNAT / metadata address after DNS and on any redirect hop, connections
    pinned to the vetted IP (SNI and ``Host`` kept), at most ``guard.max_redirects`` hops, no
    ``https``→``http`` downgrade, environment proxies ignored, and a ``url4://`` peer only
    when its host is in ``guard.peer_hosts`` (empty by default: no remote-node calls).
    ``resolver`` replaces the system DNS lookup. Only the FIRST hop of a relative fetch against
    the operator-set ``base_url`` origin is trusted; every redirect hop, and an absolute target
    that spells that origin out, is checked. The whole owned fetch, redirects included, runs
    under ``guard.total_timeout`` seconds. The owned client asks for ``Accept-Encoding:
    identity`` and decodes at most one gzip/deflate layer in bounded steps, refusing stacked or
    other codings (``x.source_too_large``), so its cap on ``guard.max_bytes`` decoded bytes holds
    with bounded memory. Each refusal is a typed ``x.source_*`` ResolutionError.
    AIDEV-NOTE: an injected ``client`` is used as-is — its owner chose its destinations,
    timeouts and decoding, so only the size cap applies to it (checked after httpx decodes).
    """

    def __init__(
        self,
        base_url: str = "",
        *,
        timeout: float = 30.0,
        client: httpx.AsyncClient | None = None,
        guard: SourceGuard | None = None,
        resolver: Resolver | None = None,
        blob_peers: Iterable[str] = (),
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._blob_peers = peer_set(blob_peers)
        self._timeout = timeout
        self._client = client
        self._guard = guard if guard is not None else SourceGuard()
        self._resolver = resolver if resolver is not None else system_resolver
        self._trusted = _trusted_origins(self._base_url)
        self._owned: httpx.AsyncClient | None = None  # lazily created when no client is injected
        self._closed = False
        self._closer = CloseOnce()

    def _get_client(self) -> httpx.AsyncClient:
        if self._closed:
            raise RuntimeError("HttpIOLayer is closed")
        if self._client is not None:
            return self._client
        if self._owned is None:
            # follow_redirects: a source that 301/302s (http->https, trailing
            # slash, auth bounce) must resolve to the real body, not the empty
            # redirect response — raise_for_status never fires on a 3xx. Every hop
            # goes through the GuardedTransport, which re-checks it (spec F1b).
            # WHY trust_env=False: an environment proxy would carry the request to an
            # address the guard never vetted.
            self._owned = httpx.AsyncClient(
                timeout=httpx.Timeout(self._timeout, connect=self._guard.connect_timeout),
                follow_redirects=True,
                max_redirects=self._guard.max_redirects,
                trust_env=False,
                transport=GuardedTransport(
                    self._guard, resolver=self._resolver, trusted=self._trusted
                ),
            )
        return self._owned

    async def fetch(self, target: str, *, relative: bool) -> str:
        _response, text = await self._get(
            self._transport_url(target, relative),
            relative=relative,
            read=lambda response: _text(target, response),
        )
        return text

    async def fetch_ex(self, request: FetchRequest) -> FetchResult:
        response, text = await self._get(
            self._transport_url(request.target, request.relative),
            relative=request.relative,
            accept=request.accept,
            read=lambda response: _text(request.target, response),
        )
        return FetchResult(text, media_type=_media_type(request.target, response))

    async def fetch_bytes(self, request: FetchRequest) -> FetchedBytes:
        """``GET`` the target and return its body exactly as received, plus its media type.

        Goes through :meth:`_get`, so the destination guard, the size cap and the deadline apply.
        A 404 / 410 is ``source_not_found`` (C5). A ``url4://`` target never follows a
        redirect: the node the ref names is the node asked (``OME-1599`` interim rule).
        """
        url4 = request.kind == "url4" or request.target.startswith("url4://")
        response, body = await self._get(
            self._transport_url(request.target, request.relative),
            relative=request.relative,
            accept=request.accept,
            read=_raw_body,
            typed=True,
            follow=not url4,
        )
        return FetchedBytes(body, media_type=_media_type(request.target, response))

    def _transport_url(self, target: str, relative: bool) -> str:
        # A url4:// target stays url4:// here: _get needs the scheme to know a peer call.
        return f"{self._base_url}{target}" if relative else target

    def blob_peer_allowed(self, authority: str) -> bool:
        """Whether a ``url4://<authority>/blob/…`` ref may be fetched (``OME-1599`` interim)."""
        return authority.lower() in self._blob_peers

    async def _get[T](
        self,
        target: str,
        *,
        relative: bool,
        read: Callable[[httpx.Response], T],
        accept: str | None = None,
        typed: bool = False,
        follow: bool = True,
    ) -> tuple[httpx.Response, T]:
        """The response and ``read(response)``, both produced within the fetch's deadline.

        AIDEV-NOTE: ``read`` is the body handling — text paths (``fetch``/``fetch_ex``) pass a
        decoder, ``fetch_bytes`` passes :func:`_raw_body`. WHY not decode here: ``response.text``
        decodes binary content; the bytes path must never touch it. Either way the final
        ``past(deadline)`` check runs AFTER ``read``.
        """
        peer = target.startswith("url4://")
        url = "https://" + target.removeprefix("url4://") if peer else target
        headers: dict[str, str] = {}
        key = idempotency_key(url)
        if key is not None:
            headers["Idempotency-Key"] = key
        if accept is not None:
            # WHY: `;accept=` (spec §4.2) is the caller's content negotiation; sent verbatim.
            headers["Accept"] = accept
        # WHY owned only: an injected client keeps the timeouts its owner chose.
        total = self._guard.total_timeout if self._client is None else None
        # INVARIANT (OME-1720): ONE absolute deadline per fetch, carried to every hop's body.
        deadline = None if total is None else deadline_in(total)
        late = f"GET {url!r} passed the {self._guard.total_timeout}s total deadline"
        try:
            async with asyncio.timeout(total):
                response = await self._send(
                    url,
                    headers or None,
                    peer=peer,
                    relative=relative,
                    deadline=deadline,
                    typed=typed,
                    follow=follow,
                )
        except TimeoutError as exc:
            raise source_timeout(late) from exc
        # WHY here: body handling (charset decoding on the text paths) is synchronous work no
        # asyncio.timeout can interrupt, so it runs BEFORE the final check (PR #1555 review: a
        # slow codec succeeded late).
        body = read(response)
        if past(deadline):
            # INVARIANT: never a success after the deadline, even one no checkpoint caught —
            # body handling included.
            raise source_timeout(late)
        return response, body

    async def _send(
        self,
        url: str,
        headers: dict[str, str] | None,
        *,
        peer: bool,
        relative: bool,
        deadline: float | None,
        typed: bool = False,
        follow: bool = True,
    ) -> httpx.Response:
        client = self._get_client()
        guarded = client is self._owned
        # WHY relative only: the operator chose base_url; an expression that spells its origin
        # out (or redirects into it) is checked like any other destination.
        trusted = relative and self._is_trusted(url)
        try:
            if guarded and not trusted:
                check_url(url, self._guard, peer=peer)
            state = FetchState(peer=peer, trusted_first_hop=trusted, deadline=deadline)
            extensions = {FETCH_STATE: state} if guarded else None
            request = client.build_request("GET", url, headers=headers, extensions=extensions)
            # WHY only ever narrowed: the client's own redirect policy holds unless refused here.
            response = await client.send(
                request, stream=True, follow_redirects=client.follow_redirects and follow
            )
            # A reply came back (any status): the next request to url is a new one.
            mark_answered(url)
            try:
                response.raise_for_status()
                body = await _read_capped(response, self._guard.max_bytes)
            finally:
                await response.aclose()
        except httpx.HTTPStatusError as exc:
            raise ResolutionError(
                f"GET {url!r} failed: {exc}",
                # WHY typed only on the bytes path: a 404's code on every other URI stays as it was.
                code=ErrorCode.SOURCE_NOT_FOUND
                if typed and exc.response.status_code in (404, 410)
                else None,
                # A refused redirect recurs on every retry: the named node is the one asked.
                permanent=_permanent_status(exc.response)
                or (not follow and exc.response.is_redirect),
                retry_after=_retry_after(exc.response),
            ) from exc
        except httpx.TooManyRedirects as exc:
            raise redirect_limit(
                f"GET {url!r} passed the {self._guard.max_redirects}-hop redirect limit"
            ) from exc
        except httpx.ConnectTimeout as exc:
            raise source_timeout(f"GET {url!r} failed: {exc}") from exc
        except (httpx.HTTPError, httpx.InvalidURL) as exc:
            # WHY: httpx.InvalidURL is not an HTTPError subclass; catch it too so a
            # malformed target (e.g. control chars in a reducer query) still
            # surfaces as ResolutionError rather than a raw httpx exception.
            raise ResolutionError(f"GET {url!r} failed: {exc}") from exc
        return _buffered(response, body)

    def _is_trusted(self, url: str) -> bool:
        try:
            return origin_of(httpx.URL(url)) in self._trusted
        except httpx.InvalidURL:
            return False

    async def aclose(self) -> None:
        """Close the internally created client, if any (an injected client is left alone).

        After ``aclose`` the adapter is closed for good; a later fetch raises.
        """
        self._closed = True
        # INVARIANT (PR #1555 review 4): the owned client is dropped only AFTER its close ends,
        # inside one shielded close a cancelled caller cannot abandon — so a retry still
        # reports a pool-close failure (httpx marks the client closed before it awaits).
        await self._closer.run(self._close_owned)

    async def _close_owned(self) -> None:
        try:
            if self._owned is not None:
                await self._owned.aclose()
        finally:
            self._owned = None

    async def __aenter__(self) -> HttpIOLayer:
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.aclose()


def _trusted_origins(base_url: str) -> frozenset[Origin]:
    if not base_url:
        return frozenset()
    try:
        return frozenset({origin_of(httpx.URL(base_url))})
    except httpx.InvalidURL:
        return frozenset()


async def _read_capped(response: httpx.Response, limit: int) -> bytes:
    """The decoded body, read chunk by chunk and abandoned as soon as it passes ``limit``.

    INVARIANT: never holds more than ``limit`` bytes — the check runs before each append.
    """
    body = bytearray()
    async for chunk in response.aiter_bytes():
        if len(body) + len(chunk) > limit:
            raise too_large(limit)
        body += chunk
    return bytes(body)


def _buffered(response: httpx.Response, body: bytes) -> httpx.Response:
    """``response`` with its already-decoded ``body`` in memory (``.text`` / ``.content`` work)."""
    headers = [(k, v) for k, v in response.headers.multi_items() if k.lower() not in _DECODED_AWAY]
    return httpx.Response(
        response.status_code, headers=headers, content=body, request=response.request
    )


def _media_type(target: str, response: httpx.Response) -> str | None:
    """The one bare, lower-cased media type of ``response``, else ``None``.

    A duplicate (comma-joined by HTTPX) or malformed ``Content-Type`` raises
    ``unsupported_content_type`` rather than leaking a joined value to the caller.
    """
    return bare_media_type(target, response.headers.get("content-type"))


def _raw_body(response: httpx.Response) -> bytes:
    """The buffered body exactly as received (content-coding undone) — never decoded to text."""
    # INVARIANT: response.content, never .text — the bytes are the origin's bytes.
    return response.content


def _text(target: str, response: httpx.Response) -> str:
    """``response.text`` for a text body; a binary body is refused, never decoded."""
    require_text(target, response.headers.get("content-type"))
    return response.text


# Spec C §13.2.1: 4xx is permanent except these; 5xx is transient except the others.
_TRANSIENT_4XX = frozenset({408, 409, 421, 423, 425, 429})
_PERMANENT_5XX = frozenset({501, 505, 508})


def _permanent_status(response: httpx.Response) -> bool:
    """Whether retrying this failed response can never succeed (Spec C §13.2.1).

    ``Retry-After`` on any response makes it transient. Anything else that is not a
    4xx or 5xx (an unfollowed redirect) is transient, like a connection failure.
    """
    if "retry-after" in response.headers:
        return False
    status = response.status_code
    if 400 <= status < 500:
        return status not in _TRANSIENT_4XX
    return status in _PERMANENT_5XX


def _retry_after(response: httpx.Response) -> float | None:
    """The ``Retry-After`` wait in seconds (delta-seconds or HTTP-date), else ``None``.

    An unparseable value still made the failure transient; it just sets no minimum.
    """
    raw = response.headers.get("retry-after")
    seconds = None if raw is None else _delta_seconds(raw)
    return None if seconds is None else max(0.0, seconds)


def _delta_seconds(raw: str) -> float | None:
    try:
        return float(raw)
    except ValueError:
        pass
    try:
        return parsedate_to_datetime(raw).timestamp() - time.time()
    except (TypeError, ValueError):
        return None


__all__ = ["HttpIOLayer", "SourceGuard"]
