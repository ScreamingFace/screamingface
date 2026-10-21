"""Bounded ``Content-Encoding`` decoding for the url4 source guard (spec F1b, ``OME-1544``).

The guarded transport asks for ``Accept-Encoding: identity``; a server may still encode. httpx's
own decoder inflates a whole raw chunk at once, so one 64 KiB chunk of a gzip bomb becomes ~64 MiB
before any byte cap sees it. This module decodes in steps of at most :data:`STEP` output bytes,
so the cap on decoded bytes aborts mid-stream with bounded memory.

INVARIANT: only one gzip or deflate layer is decoded. Stacked layers (``gzip, gzip``) and any
other coding (``br``, ``zstd``, ``compress``) are refused before a byte of the body is read.
INVARIANT: no raw byte is held past the call that fed it. A gzip body's further members are
decoded in turn under the same caller-side cap (RFC 1952 allows several); bytes after a deflate
stream, or after a gzip member that do not start another member, are a decoding error. zlib would
otherwise park them in ``unused_data`` — unbounded, and never decoded, so never counted.
INVARIANT: ``flush()`` is never called (it inflates the unconsumed input with no length bound);
:meth:`BodyDecoder.feed` drains every step instead.
"""

from __future__ import annotations

import zlib
from collections.abc import Iterator
from typing import Protocol

import httpx

from url4.core.errors import ErrorCode, ResolutionError

STEP = 64 * 1024
"""The most decoded bytes one decompress call may produce."""

_GZIP_WBITS = 16 + zlib.MAX_WBITS
_ZLIB_WBITS = zlib.MAX_WBITS
_RAW_WBITS = -zlib.MAX_WBITS


class BodyDecoder(Protocol):
    def feed(self, data: bytes) -> Iterator[bytes]:
        """Everything ``data`` decodes to, in pieces of at most :data:`STEP` bytes.

        INVARIANT: each call drains all output the input so far makes available, so a stream
        needs no final flush.
        """
        ...


class _Identity:
    def feed(self, data: bytes) -> Iterator[bytes]:
        if data:
            yield data


class _Inflate:
    """A zlib inflater whose every call yields at most :data:`STEP` bytes.

    ``deflate`` bodies come zlib-wrapped (RFC 9110) or, from some servers, raw; like httpx, the
    first chunk decides which.
    """

    def __init__(self, wbits: int, *, raw_fallback: bool = False, members: bool = False) -> None:
        self._wbits = wbits
        self._inflater = zlib.decompressobj(wbits)
        self._raw_fallback = raw_fallback
        self._members = members

    def feed(self, data: bytes) -> Iterator[bytes]:
        if self._raw_fallback and data:
            self._raw_fallback = False
            try:
                self._inflater.copy().decompress(data, 1)  # probes the header, output bounded
            except zlib.error:
                self._wbits = _RAW_WBITS
                self._inflater = zlib.decompressobj(_RAW_WBITS)
        return self._drain(data)

    def _drain(self, data: bytes) -> Iterator[bytes]:
        try:
            while True:
                if self._inflater.eof:
                    if not data:
                        return
                    self._next_member()
                out = self._inflater.decompress(data, STEP)
                if out:
                    yield out
                # WHY: at the end of a stream zlib moves the rest of ``data`` to unused_data
                # (and appends every later input there); take it back so it is never parked.
                data = self._inflater.unused_data or self._inflater.unconsumed_tail
                # WHY: a short read with no input left means zlib holds no further output.
                if not data and len(out) < STEP:
                    return
        except zlib.error as exc:
            raise httpx.DecodingError(f"cannot decode the source body: {exc}") from exc

    def _next_member(self) -> None:
        if not self._members:
            raise zlib.error("data after the end of the deflate stream")
        self._inflater = zlib.decompressobj(self._wbits)


def decoder_for(headers: httpx.Headers) -> tuple[BodyDecoder, bool]:
    """The decoder for ``headers``'s ``Content-Encoding`` and whether it changes the body.

    Raises ``x.source_too_large`` for stacked or unsupported codings: their decoded size cannot
    be bounded layer by layer, so the decoded-byte cap could not hold.
    """
    declared = headers.get_list("content-encoding", split_commas=True)
    layers = [value.strip().lower() for value in declared]
    layers = [value for value in layers if value and value != "identity"]
    if not layers:
        return _Identity(), False
    if layers == ["gzip"]:
        return _Inflate(_GZIP_WBITS, members=True), True
    if layers == ["deflate"]:
        return _Inflate(_ZLIB_WBITS, raw_fallback=True), True
    raise ResolutionError(
        f"source Content-Encoding {', '.join(declared)!r} is refused: the decoded-byte cap "
        "needs at most one gzip or deflate layer",
        code=ErrorCode.SOURCE_TOO_LARGE,
        permanent=True,
    )


__all__ = ["STEP", "BodyDecoder", "decoder_for"]
