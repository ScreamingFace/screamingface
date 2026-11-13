"""Reading an S3-compatible store's responses: raw chunks, bounded error text, and the errors.

FEATURE: over-cap results survive the Runner Job (OME-929); the run blob store (OME-1540) and the
run-results store (E5 P2 spec D9a) read through the same helpers. Moved out of `artifacts/s3.py`
unchanged, so that module stays one store.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator

import httpx

# WHY 512: enough for the store's error XML to name its cause (`<Code>SlowDown</Code>`), and a
# fixed cost however large a hostile store or proxy makes the body (#1603 review round 3).
ERROR_PREFIX_BYTES = 512
_ERROR_DETAIL_CHARS = 200
_IDENTITY_ENCODINGS = frozenset({"", "identity"})


class S3ObjectTooLarge(Exception):
    """An object holds more bytes than the caller's cap: the store's CONTENT is wrong.

    INVARIANT: not an `S3StorageError` — a sick store is retryable (503), an object past its
    cap is permanent corruption, and the blob store renders the two differently.
    """


class S3StorageError(RuntimeError):
    """The object store could not serve a request.

    INVARIANT: distinct from "the artifact is absent", which is `None`. Collapsing the two
    would present a misconfiguration (bad credentials, unreachable endpoint) as an expired
    parcel — the misdiagnosis that sent the OME-929 investigation down a dead end.
    """


def raw_chunks(response: httpx.Response, size: int) -> Iterator[bytes]:
    """The body's raw (undecoded) bytes in `size` chunks.

    WHY the `is_stream_consumed` branch: a response built in memory (`httpx.Response(content=)`,
    as a mock transport or a buffering transport returns) is already read, and `iter_raw` would
    raise `StreamConsumed`. Its bytes are already materialised, so slicing them costs nothing
    the response has not already spent. On the wire, `client.stream` never pre-reads.
    """
    if response.is_stream_consumed:
        body = response.content
        for at in range(0, len(body), size):
            yield body[at : at + size]
        return
    yield from response.iter_raw(size)


async def araw_chunks(response: httpx.Response, size: int) -> AsyncIterator[bytes]:
    """The async twin of `raw_chunks`."""
    if response.is_stream_consumed:
        for chunk in raw_chunks(response, size):
            yield chunk
        return
    async for chunk in response.aiter_raw(size):
        yield chunk


def _content_encoding(response: httpx.Response) -> str | None:
    """The response's Content-Encoding when it is anything but identity, else None."""
    raw = response.headers.get("content-encoding", "")
    tokens = {token.strip().lower() for token in raw.split(",")}
    return None if tokens <= _IDENTITY_ENCODINGS else raw.strip()


def encoded_body_note(response: httpx.Response) -> str | None:
    """A diagnostic standing in for an encoded error body that is deliberately left unread."""
    encoding = _content_encoding(response)
    return None if encoding is None else f"<{encoding}-encoded body not read>"


def refuse_encoded(response: httpx.Response, what: str) -> None:
    """Refuse an object body the store (or a proxy) sent with a non-identity Content-Encoding.

    FEATURE: #1603 review round 4 — HTTPX would inflate it before any cap applies.

    WHY refuse rather than decode: an object store returns the stored bytes and this client
    never asks for compression, so an encoded body is a misbehaving store or proxy. Decoding it
    under a cap would mean a decompressor with its own output bound; refusing needs none.
    """
    encoding = _content_encoding(response)
    if encoding is not None:
        raise S3StorageError(
            f"object storage answered {what} with Content-Encoding {encoding!r}; "
            "object bytes must arrive unencoded"
        )


def read_error_detail(response: httpx.Response) -> str:
    """The error text from at most `ERROR_PREFIX_BYTES` of a STREAMED body, then close it.

    INVARIANT (#1603 review round 4): RAW bytes only, and an encoded body is not read at all —
    `iter_bytes` would inflate a compressed body before the prefix limit applied.
    """
    detail = encoded_body_note(response)
    if detail is None:
        prefix = b""
        for prefix in raw_chunks(response, ERROR_PREFIX_BYTES):
            break
        detail = error_detail(prefix)
    response.close()
    return detail


def error_detail(prefix: bytes) -> str:
    """The store's error text from a bounded body prefix; bad UTF-8 never raises."""
    text = prefix[:ERROR_PREFIX_BYTES].decode("utf-8", errors="replace")
    return text[:_ERROR_DETAIL_CHARS]


__all__ = [
    "ERROR_PREFIX_BYTES",
    "S3ObjectTooLarge",
    "S3StorageError",
    "araw_chunks",
    "encoded_body_note",
    "error_detail",
    "raw_chunks",
    "read_error_detail",
    "refuse_encoded",
]
