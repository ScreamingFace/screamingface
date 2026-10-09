"""The httpx-backed :class:`~url4.io.layer.IOLayer` adapter (the ``run`` default).

The only module in the package that imports httpx. It owns a single, lazily
created :class:`httpx.AsyncClient` so the many fetches of one expression (a
fan-out's N sources plus its reducer) share one connection pool via keep-alive,
instead of paying a fresh TCP+TLS handshake per fetch.
"""

from __future__ import annotations

import time
from email.utils import parsedate_to_datetime

import httpx

from url4.core.errors import ResolutionError
from url4.io.idempotency import idempotency_key, mark_answered
from url4.io.layer import FetchRequest, FetchResult


class HttpIOLayer:
    """A batteries-included :class:`~url4.io.layer.IOLayer` over httpx.

    :meth:`fetch` issues ``GET target`` (or ``GET base_url + target`` for a
    relative ``/path``) and returns the response body. A relative expression
    arrives already encoded as ``/claude?q=(ctx)!intent``, so a model backend is
    just a ``GET base_url/claude?q=…`` against the localhost node. A
    ``url4://`` target is translated to ``https://`` for transport (spec §3.5 —
    the URL4 scheme rides HTTPS on the wire). :meth:`fetch_ex` additionally
    reports the response's media type so collection parsing can be
    Content-Type-driven (spec §5.3.7).

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
    """

    def __init__(
        self,
        base_url: str = "",
        *,
        timeout: float = 30.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._client = client
        self._owned: httpx.AsyncClient | None = None  # lazily created when no client is injected

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is not None:
            return self._client
        if self._owned is None:
            # follow_redirects: a source that 301/302s (http->https, trailing
            # slash, auth bounce) must resolve to the real body, not the empty
            # redirect response — raise_for_status never fires on a 3xx.
            self._owned = httpx.AsyncClient(timeout=self._timeout, follow_redirects=True)
        return self._owned

    async def fetch(self, target: str, *, relative: bool) -> str:
        response = await self._get(self._transport_url(target, relative))
        return response.text

    async def fetch_ex(self, request: FetchRequest) -> FetchResult:
        response = await self._get(self._transport_url(request.target, request.relative))
        content_type = response.headers.get("content-type", "")
        media_type = content_type.split(";", 1)[0].strip().lower() or None
        return FetchResult(response.text, media_type=media_type)

    def _transport_url(self, target: str, relative: bool) -> str:
        url = f"{self._base_url}{target}" if relative else target
        if url.startswith("url4://"):
            return "https://" + url.removeprefix("url4://")
        return url

    async def _get(self, url: str) -> httpx.Response:
        key = idempotency_key(url)
        headers = {"Idempotency-Key": key} if key is not None else None
        try:
            response = await self._get_client().get(url, headers=headers)
            # A reply came back (any status): the next request to url is a new one.
            mark_answered(url)
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise ResolutionError(
                f"GET {url!r} failed: {exc}",
                permanent=_permanent_status(exc.response),
                retry_after=_retry_after(exc.response),
            ) from exc
        except (httpx.HTTPError, httpx.InvalidURL) as exc:
            # WHY: httpx.InvalidURL is not an HTTPError subclass; catch it too so a
            # malformed target (e.g. control chars in a reducer query) still
            # surfaces as ResolutionError rather than a raw httpx exception.
            raise ResolutionError(f"GET {url!r} failed: {exc}") from exc
        return response

    async def aclose(self) -> None:
        """Close the internally created client, if any (an injected client is left alone)."""
        if self._owned is not None:
            await self._owned.aclose()
            self._owned = None

    async def __aenter__(self) -> HttpIOLayer:
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.aclose()


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


__all__ = ["HttpIOLayer"]
