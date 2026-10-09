"""The httpx-backed :class:`~url4.io.layer.IOLayer` adapter (the ``run`` default).

The only module in the package that imports httpx. It owns a single, lazily
created :class:`httpx.AsyncClient` so the many fetches of one expression (a
fan-out's N sources plus its reducer) share one connection pool via keep-alive,
instead of paying a fresh TCP+TLS handshake per fetch.
"""

from __future__ import annotations

import httpx

from url4.core.errors import ErrorCode, ResolutionError
from url4.io.layer import FetchRequest, FetchResult

_URL4_SCHEME = "url4://"
_KNOWN_ERROR_CODES = frozenset(member.value for member in ErrorCode)


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
    surfaces as :class:`~url4.core.errors.ResolutionError`.
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
        url4 = self._absolute_url(target, relative).startswith(_URL4_SCHEME)
        response = await self._get(self._transport_url(target, relative), url4=url4)
        return response.text

    async def fetch_ex(self, request: FetchRequest) -> FetchResult:
        url4 = self._absolute_url(request.target, request.relative).startswith(_URL4_SCHEME)
        response = await self._get(self._transport_url(request.target, request.relative), url4=url4)
        content_type = response.headers.get("content-type", "")
        media_type = content_type.split(";", 1)[0].strip().lower() or None
        return FetchResult(response.text, media_type=media_type)

    def _absolute_url(self, target: str, relative: bool) -> str:
        return f"{self._base_url}{target}" if relative else target

    def _transport_url(self, target: str, relative: bool) -> str:
        url = self._absolute_url(target, relative)
        if url.startswith(_URL4_SCHEME):
            return "https://" + url.removeprefix(_URL4_SCHEME)
        return url

    async def _get(self, url: str, *, url4: bool = False) -> httpx.Response:
        try:
            response = await self._get_client().get(url)
            response.raise_for_status()
        except (httpx.HTTPError, httpx.InvalidURL) as exc:
            # WHY: httpx.InvalidURL is not an HTTPError subclass; catch it too so a
            # malformed target (e.g. control chars in a reducer query) still
            # surfaces as ResolutionError rather than a raw httpx exception.
            remote = _remote_error(exc) if url4 and isinstance(exc, httpx.HTTPStatusError) else None
            if remote is not None:
                # WHY: a remote intent_error is permanent; a transient error here would be
                # retried by ;retry= (PRD E10), so the remote node's code and permanence win.
                code, message, permanent = remote
                raise ResolutionError(
                    f"GET {url!r} failed: {message}", code=code, permanent=permanent
                ) from exc
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


def _remote_error(exc: httpx.HTTPStatusError) -> tuple[str, str, bool] | None:
    """The remote node's ``(code, message, permanent)`` from an RDS error response, else None.

    Only a body of ``{"error": {"code": <known spec code>}}`` qualifies. Any other body keeps
    the transient error that the caller raises.
    """
    try:
        body = exc.response.json()
    except ValueError:  # JSONDecodeError and UnicodeDecodeError both subclass ValueError
        return None
    error = body.get("error") if isinstance(body, dict) else None
    error = error if isinstance(error, dict) else {}
    code = error.get("code")
    if not isinstance(code, str) or code not in _KNOWN_ERROR_CODES:
        return None
    message = error.get("message")
    status = exc.response.status_code
    return code, (message if isinstance(message, str) else str(exc)), 400 <= status < 500


__all__ = ["HttpIOLayer"]
