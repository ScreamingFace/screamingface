"""A chat request body streamed to the gateway in bounded chunks, byte-identical to ``json=``.

FEATURE: image and PDF inputs (epic ``OME-1529``, unit ``OME-1545``; PR #1588 review blocker 1).
STORY: as a node operator, eight concurrent model calls carrying one 8 MB picture hold the picture's
one shared ``data:`` URI, not eight JSON copies of it (the review probe: 85 MB retained).

INVARIANT (wire parity): the streamed bytes equal ``httpx``'s own ``json=`` encoding (``json.dumps``
with ``ensure_ascii=False``, ``separators=(",", ":")``, ``allow_nan=False``, UTF-8), and the
``Content-Length`` is that encoding's exact length — so the gateway, its cache key and its request
cap see the same request as before; only the Engine's memory changes.
INVARIANT (bounded memory): a string longer than :data:`_LARGE` is never encoded whole; it is
escaped and encoded :data:`_SLICE` characters at a time into a :data:`_CHUNK`-byte buffer, so one
in-flight call holds O(``_CHUNK``) beyond the objects it shares.

AIDEV-NOTE: a body with no large string returns ``None`` and keeps the plain ``json=`` path, so a
text-only call is untouched — same bytes AND the same ``httpx`` request shape tests read.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Iterator
from typing import Any

_CHUNK = 64 * 1024
"""The most bytes one yielded chunk carries (httpx's own streaming chunk size)."""
_SLICE = 16 * 1024
"""Characters escaped per step of a large string: at most 6 bytes each (a ``\\u001f`` escape), so
one step's piece is at most 96 KiB before :func:`_buffered` cuts it into chunks."""
_LARGE = 256 * 1024
"""A string at least this long is streamed in slices; anything shorter is encoded whole."""

_ENCODER = json.JSONEncoder(ensure_ascii=False, separators=(",", ":"), allow_nan=False)


class StreamedJson:
    """A re-iterable async byte stream of one body: each ``async for`` starts over (a retry)."""

    __slots__ = ("_body",)

    def __init__(self, body: Any) -> None:
        self._body = body

    def __aiter__(self) -> AsyncIterator[bytes]:
        return self._chunks()

    async def _chunks(self) -> AsyncIterator[bytes]:
        for chunk in _buffered(_pieces(self._body)):
            yield chunk

    def __len__(self) -> int:
        return sum(len(piece) for piece in _pieces(self._body))


def streamed_json_body(body: Any) -> tuple[dict[str, str], StreamedJson] | None:
    """Headers and a stream for ``body`` when it holds a large string; ``None`` otherwise."""
    if not _has_large_string(body):
        return None
    content = StreamedJson(body)
    return {"Content-Length": str(len(content)), "Content-Type": "application/json"}, content


def _has_large_string(value: Any) -> bool:
    if isinstance(value, str):
        return len(value) >= _LARGE
    items = value.values() if isinstance(value, dict) else value
    return isinstance(value, dict | list | tuple) and any(_has_large_string(i) for i in items)


def _pieces(value: Any) -> Iterator[bytes]:
    """``value``'s JSON as UTF-8 pieces, in order; a large string comes in bounded slices."""
    if isinstance(value, str) and len(value) >= _LARGE:
        yield from _string_pieces(value)
    elif isinstance(value, dict) and value and all(isinstance(key, str) for key in value):
        # WHY str keys only: ``json.dumps`` coerces other key types; such a dict is small and
        # encoded whole below, which keeps that coercion exactly.
        yield from _object_pieces(value)
    elif isinstance(value, list | tuple) and value:
        yield from _array_pieces(value)
    else:
        yield _ENCODER.encode(value).encode("utf-8")


def _string_pieces(value: str) -> Iterator[bytes]:
    yield b'"'
    for start in range(0, len(value), _SLICE):
        # WHY slicing is safe: a Python ``str`` index is a code point, so no slice splits one,
        # and JSON escaping is per code point (``ensure_ascii=False`` never emits surrogates).
        yield _ENCODER.encode(value[start : start + _SLICE])[1:-1].encode("utf-8")
    yield b'"'


def _object_pieces(value: dict[str, Any]) -> Iterator[bytes]:
    yield b"{"
    for index, (key, item) in enumerate(value.items()):
        yield (b"," if index else b"") + _ENCODER.encode(key).encode("utf-8") + b":"
        yield from _pieces(item)
    yield b"}"


def _array_pieces(value: list[Any] | tuple[Any, ...]) -> Iterator[bytes]:
    yield b"["
    for index, item in enumerate(value):
        if index:
            yield b","
        yield from _pieces(item)
    yield b"]"


def _buffered(pieces: Iterator[bytes]) -> Iterator[bytes]:
    """Coalesce ``pieces`` into chunks of at most :data:`_CHUNK` bytes."""
    buffer = bytearray()
    for piece in pieces:
        view = memoryview(piece)
        while view:
            room = _CHUNK - len(buffer)
            buffer += view[:room]
            view = view[room:]
            if len(buffer) == _CHUNK:
                yield bytes(buffer)
                buffer.clear()
    if buffer:
        yield bytes(buffer)


__all__ = ["StreamedJson", "streamed_json_body"]
