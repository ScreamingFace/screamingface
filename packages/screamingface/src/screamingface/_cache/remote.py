"""The hosted Engine as a source of community-cache pages (epic OME-1311).

One streamed `GET /v1/cache/entries` per page, through a `Client`'s own engine session, so the
caller's Cloudflare Access sign-in is the one every other SDK call uses (spec decision 14). The
body is decompressed here as it arrives, in bounded pieces, split into lines, and handed on line by
line.

INVARIANT (PR #1446 review): no response is held whole, and none is decompressed whole. gzip is
decoded from the raw bytes at most `_DECODED_PIECE` at a time, so a chunk that expands a
thousandfold never exists decoded in one allocation; a line is refused past `_MAX_LINE_BYTES`
before it is decoded as text; a retryable status is classified from its headers alone; and any
other refusal decodes at most `_PROBLEM_MAX_BYTES` of its problem detail.

WHY the replay-safe extension: a page request is a GET with no side effects, so the Access flow
may send it again after a browser sign-in (`_core/wire.py`).
"""

from __future__ import annotations

import zlib
from collections.abc import Callable, Iterable, Iterator, Sequence
from contextlib import contextmanager
from typing import TYPE_CHECKING, Final

from screamingface._cache.pages import MalformedPage
from screamingface._core.retry import _RETRYABLE_STATUS, _retry_after_seconds
from screamingface._core.wire import _REPLAY_SAFE
from screamingface.errors import AuthenticationError, PlanningError

if TYPE_CHECKING:
    import httpx

_ENTRIES_PATH: Final = "/v1/cache/entries"
# WHY 32 MiB: a hosted response is capped at 1 MB and JSON escaping at most sextuples it, so no row
# the hosted gateway wrote comes near; a longer line is not a page this client can read.
_MAX_LINE_BYTES: Final = 32 * 1024 * 1024
_PROBLEM_MAX_BYTES: Final = 64 * 1024
# WHY 1 MiB: large enough that zlib's C loop, not Python, does the work; small enough that one
# decoded piece is a bounded allocation whatever the compression ratio.
_DECODED_PIECE: Final = 1024 * 1024


class TransientPageError(Exception):
    """This page could not be read just now; asking for it again may succeed."""

    def __init__(self, message: str, *, retry_after: float | None = None) -> None:
        super().__init__(message)
        self.retry_after = retry_after


class HostedPages:
    """Pages of one pull's filter, read from one hosted Engine session."""

    def __init__(self, http: httpx.Client, models: Sequence[str]) -> None:
        self._http = http
        self._models = tuple(models)

    @property
    def origin(self) -> str:
        return str(self._http.base_url).rstrip("/")

    @contextmanager
    def open(
        self, *, after: str | None, count: bool
    ) -> Iterator[tuple[Iterator[str], Callable[[], int]]]:
        """The page's lines, and a reading of the compressed bytes received so far."""
        import httpx

        params: dict[str, str | list[str]] = {}
        if self._models:
            params["model"] = list(self._models)
        if after is not None:
            params["after"] = after
        if count:
            params["count"] = "true"
        try:
            with self._http.stream(
                "GET",
                _ENTRIES_PATH,
                params=params,
                headers={"Accept-Encoding": "gzip"},
                extensions={_REPLAY_SAFE: True},
            ) as response:
                if response.status_code != 200:
                    _raise_for(response)
                yield _lines(_body(response)), lambda: response.num_bytes_downloaded
        # WHY DecodingError: a gzip stream cut or garbled in transit reads as corrupt, not dropped.
        except (httpx.TransportError, httpx.DecodingError) as exc:
            raise TransientPageError(
                f"the Engine could not be reached ({type(exc).__name__})"
            ) from exc


def _body(response: httpx.Response, piece: int = _DECODED_PIECE) -> Iterator[bytes]:
    """The response's decoded body, at most `piece` at a time."""
    # WHY: a body httpx already read (a buffered response) is decoded already.
    if response.is_stream_consumed:
        return iter([response.content])
    gzip = response.headers.get("content-encoding", "").strip().casefold() == "gzip"
    return _decompressed(response.iter_raw(), gzip=gzip, piece=piece)


def _decompressed(
    chunks: Iterable[bytes], *, gzip: bool, piece: int = _DECODED_PIECE
) -> Iterator[bytes]:
    """The body's decoded bytes, at most `piece` at a time."""
    import httpx

    if not gzip:
        yield from chunks
        return
    decoder = zlib.decompressobj(16 + zlib.MAX_WBITS)
    try:
        for chunk in chunks:
            data = chunk
            while True:
                out = decoder.decompress(data, piece)
                if out:
                    yield out
                data = decoder.unconsumed_tail
                # WHY a full piece goes round again: zlib may hold more output for this input.
                if not data and len(out) < piece:
                    break
    # WHY as httpx's own error: a gzip stream garbled in transit stays a transient failure.
    except zlib.error as exc:
        raise httpx.DecodingError(f"the page's gzip stream is corrupt: {exc}") from exc


def _lines(chunks: Iterable[bytes]) -> Iterator[str]:
    buffer = bytearray()
    for chunk in chunks:
        # WHY from the new chunk only: rescanning a long line's earlier chunks would be quadratic.
        searched = len(buffer)
        buffer += chunk
        start = 0
        while (end := buffer.find(b"\n", searched)) != -1:
            yield _decoded(buffer[start:end])
            start = searched = end + 1
        del buffer[:start]
        if len(buffer) > _MAX_LINE_BYTES:
            raise MalformedPage(f"a page line is longer than {_MAX_LINE_BYTES} bytes")
    if buffer:
        yield _decoded(buffer)


def _decoded(line: bytearray) -> str:
    if len(line) > _MAX_LINE_BYTES:
        raise MalformedPage(f"a page line is longer than {_MAX_LINE_BYTES} bytes")
    try:
        return line.decode()
    except UnicodeDecodeError as exc:
        raise MalformedPage("a page line is not UTF-8") from exc


def _raise_for(response: httpx.Response) -> None:
    from screamingface._engine.transport import _problem_parts

    status = response.status_code
    # WHY the SDK's shared set: a page crosses the same Cloudflare edge as every other call, and
    # the Engine's own cache route answers 429 + Retry-After when reads are rate limited. Every
    # other status is a fact about the request, not about the moment.
    if status in _RETRYABLE_STATUS:
        raise TransientPageError(
            f"the Engine answered {status}", retry_after=_retry_after_seconds(response)
        )
    detail, code, details = _problem_parts(_prefix(response))
    if status in {401, 403}:
        raise AuthenticationError(
            f"The Engine refused the community-cache request: {detail}",
            code="authentication_required",
            status=status,
            permanent=True,
            details=details,
        )
    if status == 404:
        raise PlanningError(
            "This Engine does not serve the community cache",
            code="community_cache_unsupported",
            status=status,
            permanent=True,
            details=details,
        )
    raise PlanningError(
        f"The Engine refused the community-cache request: {detail}",
        code=code or "community_cache_request_refused",
        status=status,
        permanent=True,
        details=details,
    )


def _prefix(response: httpx.Response) -> httpx.Response:
    """The refusal with at most `_PROBLEM_MAX_BYTES` of its (decompressed) body."""
    import httpx

    body = bytearray()
    for chunk in _body(response, _PROBLEM_MAX_BYTES):
        body += chunk
        if len(body) >= _PROBLEM_MAX_BYTES:
            break
    return httpx.Response(
        response.status_code,
        headers={"content-type": response.headers.get("content-type", "")},
        content=bytes(body[:_PROBLEM_MAX_BYTES]),
        request=response.request,
    )


__all__ = ["HostedPages", "TransientPageError"]
