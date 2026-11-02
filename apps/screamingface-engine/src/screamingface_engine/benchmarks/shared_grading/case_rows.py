"""Stream the rows of a prepared ``cases.json`` one at a time instead of parsing the whole file.

FEATURE: capacity for concurrent users (OME-1314, OME-1789). A picture board's ``cases.json`` is
hundreds of MB of base64 (FigQA: 181 Cases, ~330 MB). The aggregate needs only the Cases a run
selected, yet ``read_text`` + ``json.loads`` held the whole text AND every decoded row at once —
close to a GiB of peak memory for a 2-Case run. This reader holds one row at a time.

How: read the text in chunks and decode each top-level array element with the stdlib decoder's
``raw_decode``. When an element straddles the end of the buffer, read more and retry; the read
grows with the buffer, so even a row far larger than a chunk costs amortised linear time.

INVARIANT: what this accepts and rejects is what ``json.loads`` accepts and rejects — the same
decoder decodes every element, and the array punctuation and surrounding whitespace follow the
JSON grammar exactly. A malformed file raises ``ValueError`` (the wording may differ from
``json.loads``'s; the caller's message prefix does not), a well-formed non-array raises
``NotAnArrayError``.

AIDEV-NOTE: this is NOT per-Case storage (OME-1790) and does not change what the Cases route
reads (OME-1675). Every row is still decoded once per aggregate; only the memory is bounded.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from typing import TextIO

#: Characters read per refill. Monkeypatched small by the tests to force every edge case.
CHUNK_CHARS = 1 << 20

#: JSON's insignificant whitespace — exactly the four characters ``json.loads`` skips.
_WHITESPACE = " \t\n\r"

#: Every character that can continue a JSON number (digits, fraction, exponent and its sign).
_NUMBER_CHARS = "0123456789.eE+-"


class NotAnArrayError(ValueError):
    """The file is valid JSON, but its top level is not an array."""


class _Buffer:
    """A sliding window over the stream: ``text[pos:]`` is what has not been consumed yet."""

    def __init__(self, stream: TextIO, chunk_chars: int) -> None:
        self._stream = stream
        self._chunk = max(1, chunk_chars)
        self.text = ""
        self.pos = 0
        self.eof = False

    def refill(self) -> bool:
        """Read more text; False once the stream is exhausted.

        WHY the read grows with the pending text: a retry re-decodes the pending element from
        its start, so doubling keeps a huge row at O(size) total work instead of O(size²/chunk).
        """

        if self.eof:
            return False
        pending: str = self.text[self.pos :]
        piece: str = self._stream.read(max(self._chunk, len(pending)))
        if not piece:
            self.eof = True
            return False
        self.text = pending + piece
        self.pos = 0
        return True

    def peek(self) -> str:
        """The next non-whitespace character, consuming the whitespace; "" at end of stream."""

        while True:
            while self.pos < len(self.text) and self.text[self.pos] in _WHITESPACE:
                self.pos += 1
            if self.pos < len(self.text):
                return self.text[self.pos]
            if not self.refill():
                return ""


def iter_array_rows(stream: TextIO, *, chunk_chars: int | None = None) -> Iterator[object]:
    """Yield each element of the JSON array in ``stream``, in order, holding one at a time.

    Raises:
        ValueError: the text is not valid JSON (including a truncated or trailing-garbage file).
        NotAnArrayError: the text is valid JSON whose top level is not an array.
    """

    buffer = _Buffer(stream, CHUNK_CHARS if chunk_chars is None else chunk_chars)
    decoder = json.JSONDecoder()
    if buffer.peek() != "[":
        # WHY: not an array, but the old reader distinguished "not JSON" from "not an array".
        # Off the hot path (a broken bundle), so decoding the rest whole keeps that exact.
        rest: str = buffer.text[buffer.pos :] + stream.read()
        json.loads(rest)
        raise NotAnArrayError("top-level JSON value is not an array")
    buffer.pos += 1
    if buffer.peek() == "]":
        buffer.pos += 1
    else:
        while True:
            yield _decode_element(buffer, decoder)
            separator: str = buffer.peek()
            buffer.pos += 1
            if separator == "]":
                break
            if separator != ",":
                raise ValueError(f"expected ',' or ']' in the cases array, got {separator!r}")
    if buffer.peek():
        raise ValueError("extra data after the cases array")


def _decode_element(buffer: _Buffer, decoder: json.JSONDecoder) -> object:
    """Decode the element starting at the next non-whitespace character, refilling as needed."""

    if not buffer.peek():
        raise ValueError("the cases array is truncated")
    while True:
        try:
            value, end = decoder.raw_decode(buffer.text, buffer.pos)
        except json.JSONDecodeError:
            if buffer.refill():
                continue
            raise
        # WHY: a number cut by the buffer edge decodes as a shorter number ("12" | "3",
        # "-15" | "00.5", "1.5e" | "3"), so it is final only once a character that cannot
        # continue it is in view. Strings, objects, arrays and literals end on their own.
        if (
            isinstance(value, int | float)
            and not buffer.text[end:].lstrip(_NUMBER_CHARS)
            and buffer.refill()
        ):
            continue
        buffer.pos = end
        return value


__all__ = ["CHUNK_CHARS", "NotAnArrayError", "iter_array_rows"]
