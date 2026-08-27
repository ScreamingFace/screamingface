"""OME-479 §5.2 — bounded, sanitized public-discovery HTTPS transport.

FEATURE: safe dynamic observation transport. Providers (OpenRouter/HF/Gemini)
fetch FIXED public catalogs to enrich the detailed contract with raw support
evidence. This module owns the safety envelope; provider parsers own the shape.

INVARIANT (§5.2): the caller (a provider integration) supplies a FIXED https URL
and its own allowlisted origins — never a caller-supplied or response-derived
URL, never a followed redirect. Credentials: never an ACCOUNT credential, and
never on the default path. OME-1026 (D1) narrowed this by exception — a provider
MAY attach an operator-configured DEPLOYMENT discovery credential as static
headers to its OWN allowlisted origin, validated before the dial opens. Every failure is raised as a
``DiscoveryError`` carrying ONLY a stable reason code — never a raw body or a
raw exception string (that would leak upstream content into API output).

INVARIANT: nothing here runs on the chat dispatch critical path — discovery
feeds the detailed contract only. Dispatch is authorized by rules alone.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol, cast
from urllib.parse import urlsplit

import httpx


class DiscoveryError(Exception):
    """A sanitized discovery failure.

    # INVARIANT: only ``reason`` (a fixed code) is ever exposed; no raw upstream
    # body or raw exception text is attached, so it is safe to surface.
    """

    def __init__(self, reason: str, *, status: int | None = None) -> None:
        super().__init__(reason)
        self.reason = reason
        # OME-972: the upstream HTTP status for ``bad_status`` failures ONLY — an
        # integer class marker (401 auth onset vs 429 vs 5xx outage) that log
        # lines may render. Never a body, never text; None for every other reason.
        self.status = status


@dataclass(frozen=True)
class DiscoveryLimits:
    """Response bounds enforced on every fetch (§5.2)."""

    timeout_s: float = 3.0
    max_bytes: int = 1_000_000
    max_json_depth: int = 16
    max_json_nodes: int = 50_000


@dataclass(frozen=True)
class DiscoverySourceRef:
    """The cache identity of a provider's discovery source, known BEFORE any fetch.

    # WHY it must precede the fetch: the observation cache decides whether a
    # stored value is still trustworthy by comparing the ``revision`` it was
    # stored under. A revision read OFF the fetched payload could only ever be
    # compared after paying for the fetch, which defeats the cache — and would
    # let the source itself decide when its old evidence stays valid.
    # INVARIANT: ``revision`` identifies the SOURCE (which catalog, parsed by
    # which gateway-side reading), not the freshness of one response. Freshness
    # is the cache's TTL; the revision is what a TTL is scoped to.
    """

    source: str
    revision: str


@dataclass(frozen=True)
class RawResponse:
    """The minimal, transport-agnostic response the discovery layer inspects."""

    status: int
    content_type: str
    body: str


class DiscoveryHttpClient(Protocol):
    """Injected transport seam — a real httpx adapter in prod, a fake in tests.

    The adapter MUST NOT follow redirects and MUST translate any network/timeout
    fault into a ``DiscoveryError`` (so this module never leaks a raw exception).
    """

    async def get(self, url: str, *, timeout_s: float, max_bytes: int) -> RawResponse: ...


class HeaderCapableDiscoveryClient(Protocol):
    """OME-1026 (D1) — the OPTIONAL capability: a dial that can carry static headers.

    # WHY a second protocol instead of widening ``DiscoveryHttpClient``: protocol
    # matching is structural, so adding this keyword there would make every existing
    # discovery double — which declares only the legacy signature — stop satisfying the
    # port, turning a capability ONE provider needs into a pyright failure across every
    # prior unit's tests.
    # AIDEV-NOTE: deliberately NOT ``runtime_checkable``, and never isinstance-tested.
    # A runtime protocol check compares member NAMES, not signatures, so every legacy
    # client would pass it — pyright says the same thing statically ("overlaps unsafely
    # and could produce a match at runtime"). There is therefore no honest static test
    # for this capability: ``fetch_discovery_json`` casts to it for narrowing and relies
    # on the argument-binding boundary as the ONLY runtime guarantee.
    """

    async def get(
        self,
        url: str,
        *,
        timeout_s: float,
        max_bytes: int,
        headers: Mapping[str, str] | None = None,
    ) -> RawResponse: ...


def _origin_of(url: str) -> tuple[str, str]:
    parts = urlsplit(url)
    return parts.scheme, f"{parts.scheme}://{parts.netloc}"


def _assert_bounded(data: Any, *, max_depth: int, max_nodes: int) -> None:
    # WHY: a fixed public catalog is normally shallow and small; a pathologically
    # deep or huge document is treated as hostile input, not parsed into memory
    # pressure. Depth is checked BEFORE recursing so the stack is bounded too.
    nodes = 0

    def walk(node: Any, depth: int) -> None:
        nonlocal nodes
        if depth > max_depth:
            raise DiscoveryError("too_deep")
        nodes += 1
        if nodes > max_nodes:
            raise DiscoveryError("too_many_nodes")
        if isinstance(node, dict):
            for value in node.values():
                walk(value, depth + 1)
        elif isinstance(node, list):
            for value in node:
                walk(value, depth + 1)

    walk(data, 0)


async def fetch_discovery_json(
    url: str,
    *,
    allowed_origins: frozenset[str],
    client: DiscoveryHttpClient,
    limits: DiscoveryLimits = DiscoveryLimits(),
    headers: Mapping[str, str] | None = None,
) -> Any:
    """Fetch + validate a fixed JSON catalog, or raise ``DiscoveryError``.

    Order matters: origin/scheme are validated BEFORE the client is dialed, so a
    non-allowlisted or insecure URL never opens a connection — which is also what
    makes ``headers`` safe to carry a deployment credential (OME-1026 D1): it
    cannot leave for a host the caller did not allowlist.

    ``headers`` is OPTIONAL and defaults to the legacy behavior. With no headers the
    client is dialed EXACTLY as before, the keyword absent from the call, so a
    transport double that predates this capability is unaffected.
    """
    scheme, origin = _origin_of(url)
    if scheme != "https":
        raise DiscoveryError("insecure_scheme")
    if origin not in allowed_origins:
        raise DiscoveryError("origin_not_allowed")

    if headers is None:
        # The byte-identical legacy call: the keyword is not passed at all.
        response = await client.get(url, timeout_s=limits.timeout_s, max_bytes=limits.max_bytes)
    else:
        # A cast, not a check: whether this transport can bind ``headers`` is genuinely
        # unknowable statically (see HeaderCapableDiscoveryClient), so pretending to
        # verify it would be theatre. The binding guard below is the real gate.
        capable = cast(HeaderCapableDiscoveryClient, client)
        try:
            pending = capable.get(
                url,
                timeout_s=limits.timeout_s,
                max_bytes=limits.max_bytes,
                headers=headers,
            )
        except TypeError:
            # INVARIANT: a transport that cannot BIND ``headers`` fails at coroutine
            # CREATION, before its body runs — so a credentialed dial can never silently
            # degrade into a credential-less one whose (unauthorized) response might be
            # cached as a fresh catalog. Sanitized: no header name or value is attached.
            raise DiscoveryError("internal_error") from None
        # INVARIANT: awaited OUTSIDE the guard deliberately. A capable client's INTERNAL
        # TypeError must stay a TypeError for the outer boundary rather than be relabelled
        # a signature mismatch — "cannot carry headers" and "is broken" are different bugs.
        response = await pending

    # A redirect (3xx) is never followed: any non-200 is a failure, not a hop.
    if response.status != 200:
        raise DiscoveryError("bad_status", status=response.status)
    if response.content_type.split(";")[0].strip().lower() != "application/json":
        raise DiscoveryError("bad_content_type")
    if len(response.body.encode("utf-8")) > limits.max_bytes:
        raise DiscoveryError("oversized")

    try:
        parsed = json.loads(response.body)
    except (json.JSONDecodeError, RecursionError):
        # sanitized: the raw body is discarded, only a fixed reason survives.
        raise DiscoveryError("malformed_json") from None

    _assert_bounded(parsed, max_depth=limits.max_json_depth, max_nodes=limits.max_json_nodes)
    return parsed


# WHY: ``max_bytes`` must denote ONE quantity. Asking for an unencoded body makes
# bytes-on-the-wire, bytes-buffered and bytes-parsed the same number, so the limit
# stops depending on a ``Content-Encoding`` the source chooses. The extra transfer is
# ~1 MB once per cache TTL, on a path that is off the dispatch critical path (§5.2).
_IDENTITY_ENCODING = {"accept-encoding": "identity"}


class HttpxDiscoveryClient:
    """The production ``DiscoveryHttpClient`` over httpx (§5.2).

    # INVARIANT: ``follow_redirects`` is OFF, so a 3xx is returned as-is for
    # ``fetch_discovery_json`` to fail as a bad status — a Location is never
    # chased into an unvetted origin.
    # INVARIANT: this adapter ENFORCES both advertised bounds rather than reporting
    # near them — an over-cap body raises instead of returning truncated, and
    # ``timeout_s`` is a total wall-clock deadline, not a per-interval budget.
    # INVARIANT: every httpx fault is translated to ``DiscoveryError`` with a
    # fixed reason and no ``__cause__`` chained out — a raw transport message can
    # carry a host/path, and must never reach API output.
    # AIDEV-NOTE: ``transport`` is injectable ONLY so tests drive it with
    # ``httpx.MockTransport``; production constructs it with no arguments.
    """

    def __init__(self, *, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._transport = transport

    async def get(
        self,
        url: str,
        *,
        timeout_s: float,
        max_bytes: int,
        headers: Mapping[str, str] | None = None,
    ) -> RawResponse:
        # WHY: ``httpx.Timeout`` bounds each connect/read/write/pool INTERVAL, and
        # every interval resets on activity — a source that keeps dribbling small
        # chunks stays "busy" and never trips it. Only an outer deadline bounds the
        # operation. It sits OUTSIDE the httpx handler below so an expiry is reported
        # as ``timeout`` rather than reclassified by httpx's own error translation.
        try:
            async with asyncio.timeout(timeout_s):
                return await self._read_bounded(
                    url, timeout_s=timeout_s, max_bytes=max_bytes, headers=headers
                )
        except TimeoutError:
            raise DiscoveryError("timeout") from None

    async def _read_bounded(
        self,
        url: str,
        *,
        timeout_s: float,
        max_bytes: int,
        headers: Mapping[str, str] | None = None,
    ) -> RawResponse:
        # INVARIANT (OME-1026 CC-14): caller headers are merged UNDER the identity
        # encoding, so identity WINS on conflict. The bounded read counts wire bytes and
        # equals the parsed quantity only while nothing is compressed — a caller must not
        # be able to reopen the expansion path the byte cap closes.
        request_headers = {**(headers or {}), **_IDENTITY_ENCODING}
        try:
            async with httpx.AsyncClient(
                follow_redirects=False,
                timeout=httpx.Timeout(timeout_s),
                transport=self._transport,
            ) as client:
                async with client.stream("GET", url, headers=request_headers) as response:
                    return RawResponse(
                        status=response.status_code,
                        content_type=response.headers.get("content-type", ""),
                        body=await self._bounded_body(response, max_bytes=max_bytes),
                    )
        except httpx.HTTPError:
            # sanitized: a stable reason only; the raw exception is dropped.
            raise DiscoveryError("unreachable") from None

    @staticmethod
    async def _bounded_body(response: httpx.Response, *, max_bytes: int) -> str:
        encoding = response.headers.get("content-encoding", "").strip().lower()
        if encoding and encoding != "identity":
            # Refused rather than decoded: decoding would move the cap back onto
            # post-expansion bytes and reopen the expansion path the policy closes.
            raise DiscoveryError("unsupported_encoding")

        # WHY: with a non-identity encoding already refused above, httpx's decoder for
        # what remains is the identity decoder, so ``aiter_bytes`` yields exactly the
        # bytes on the wire — the counted quantity and the wire quantity are the same.
        # The expansion path is closed by the header refusal, not by the iterator
        # choice, which is why this does not need ``aiter_raw`` (that additionally
        # rejects any already-materialised response, e.g. a non-streaming test double).
        # AIDEV-NOTE: deliberately NO ``chunk_size``. httpx's ByteChunker writes each
        # incoming read into its own buffer in full before splitting, so a chunk size
        # would add a copy without bounding memory; unset, it passes reads straight
        # through at the transport's own sizing.
        chunks: list[bytes] = []
        total = 0
        async for chunk in response.aiter_bytes():
            # INVARIANT: counted BEFORE retained, so the buffer never exceeds the cap.
            total += len(chunk)
            if total > max_bytes:
                raise DiscoveryError("oversized")
            chunks.append(chunk)
        try:
            return b"".join(chunks).decode("utf-8")
        except UnicodeDecodeError:
            # INVARIANT: replacement decoding can erase restrictive model evidence
            # while leaving syntactically valid JSON that would be cached as fresh.
            raise DiscoveryError("malformed_json") from None
