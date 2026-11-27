"""A picture's width and height, read from its header bytes without decoding a pixel (OME-1970).

FEATURE: the hosts' floor. The importer refuses a picture with a side over 8000 px or more than
30,000 patches of 32 px (``picture_input.py``), so it needs each picture's size. Think of it as
reading the label on a box instead of opening it: every format the Case envelope accepts states
its size in the first few dozen bytes, at a fixed place or (JPEG) in the first frame header.

Where each format keeps it:

    PNG   — the IHDR chunk, always first: width, height as 4-byte big-endian at bytes 16–24.
    GIF   — the logical screen: width, height as 2-byte little-endian at bytes 6–10.
    JPEG  — the first start-of-frame (SOF) segment, found by walking the segments after the
            start marker: height, width as 2-byte big-endian after one precision byte.
    WebP  — the first chunk after ``RIFF....WEBP``: ``VP8X`` (extended) holds the canvas as
            3-byte little-endian size-minus-one; ``VP8L`` (lossless) packs 14-bit
            size-minus-one fields after a signature byte; ``VP8 `` (lossy) holds 14-bit
            width, height after a 3-byte frame tag and the start code ``9d 01 2a``.

Example: a PNG whose IHDR says 14950 × 2780 → ``(14950, 2780)``; 16 bytes of a PNG signature
and padding (the importer tests' stand-in) → ``None``.

INVARIANT: this module never raises on any input; a header it cannot read is ``None``, and the
caller decides what that means. WHY no Pillow: ``picture_input`` runs in every import, and
these few fixed offsets need no decoder or extra dependency.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Final, Literal

#: Byte order, as ``int.from_bytes`` names it.
ByteOrder = Literal["little", "big"]

_PNG: Final[bytes] = b"\x89PNG\r\n\x1a\n"
_GIF_SIGNATURES: Final[tuple[bytes, ...]] = (b"GIF87a", b"GIF89a")
_JPEG_START: Final[bytes] = b"\xff\xd8"
#: The start-of-frame markers that carry a frame size: C0–CF except C4 (Huffman tables),
#: C8 (reserved) and CC (arithmetic conditioning).
_JPEG_SOF: Final[frozenset[int]] = frozenset(range(0xC0, 0xD0)) - {0xC4, 0xC8, 0xCC}
#: Markers that stand alone, with no length after them: RST0–RST7, SOI, EOI and TEM.
_JPEG_STANDALONE: Final[frozenset[int]] = frozenset(range(0xD0, 0xDA)) | {0x01}
#: A 14-bit field, as VP8 and VP8L store a side.
_FOURTEEN_BITS: Final[int] = 0x3FFF
_VP8_START_CODE: Final[bytes] = b"\x9d\x01\x2a"


def picture_size(data: bytes) -> tuple[int, int] | None:
    """The picture's ``(width, height)`` in px from its header, or ``None`` when unreadable."""

    for matches, read in _READERS:
        if matches(data):
            return read(data)
    return None


def _pair(data: bytes, offset: int, width: int, order: ByteOrder) -> tuple[int, int] | None:
    """Two unsigned integers of ``width`` bytes at ``offset``, or ``None`` past the end."""

    end: int = offset + 2 * width
    if len(data) < end:
        return None
    first: int = int.from_bytes(data[offset : offset + width], order)
    second: int = int.from_bytes(data[offset + width : end], order)
    return first, second


def _png_size(data: bytes) -> tuple[int, int] | None:
    """PNG: IHDR is the first chunk, so its width and height sit at bytes 16–24."""

    if data[12:16] != b"IHDR":
        return None
    return _pair(data, 16, 4, "big")


def _jpeg_size(data: bytes) -> tuple[int, int] | None:
    """JPEG: walk the segments from byte 2 until the first start-of-frame, then read it.

    Each segment is ``FF <marker> <2-byte length, itself included> <body>``; fill bytes
    (extra ``FF``) may sit between segments. SOF's body is precision, height, width.
    """

    position: int = len(_JPEG_START)
    while position + 4 <= len(data):
        if data[position] != 0xFF:
            return None
        marker: int = data[position + 1]
        if marker == 0xFF:
            position += 1
            continue
        if marker in _JPEG_STANDALONE:
            position += 2
            continue
        length: int = int.from_bytes(data[position + 2 : position + 4], "big")
        if marker in _JPEG_SOF:
            size: tuple[int, int] | None = _pair(data, position + 5, 2, "big")
            return None if size is None else (size[1], size[0])
        position += 2 + length
    return None


def _webp_size(data: bytes) -> tuple[int, int] | None:
    """WebP: the first chunk after the 12-byte RIFF header names the bitstream; read its size."""

    read: Callable[[bytes], tuple[int, int] | None] | None = _WEBP_CHUNKS.get(data[12:16])
    return None if read is None else read(data)


def _vp8x_size(data: bytes) -> tuple[int, int] | None:
    """Extended WebP: the canvas as 3-byte little-endian size-minus-one after 4 flag bytes."""

    size: tuple[int, int] | None = _pair(data, _WEBP_BODY + 4, 3, "little")
    return None if size is None else (size[0] + 1, size[1] + 1)


def _vp8l_size(data: bytes) -> tuple[int, int] | None:
    """Lossless WebP: signature 0x2F, then 14-bit width-minus-one and height-minus-one."""

    if len(data) < _WEBP_BODY + 5 or data[_WEBP_BODY] != _VP8L_SIGNATURE:
        return None
    bits: int = int.from_bytes(data[_WEBP_BODY + 1 : _WEBP_BODY + 5], "little")
    return (bits & _FOURTEEN_BITS) + 1, ((bits >> 14) & _FOURTEEN_BITS) + 1


def _vp8_size(data: bytes) -> tuple[int, int] | None:
    """Lossy WebP: a 3-byte frame tag, the start code, then 14-bit width and height."""

    if data[_WEBP_BODY + 3 : _WEBP_BODY + 6] != _VP8_START_CODE:
        return None
    size: tuple[int, int] | None = _pair(data, _WEBP_BODY + 6, 2, "little")
    return None if size is None else (size[0] & _FOURTEEN_BITS, size[1] & _FOURTEEN_BITS)


def _gif_size(data: bytes) -> tuple[int, int] | None:
    """GIF: the logical screen's width and height, 2-byte little-endian at bytes 6–10."""

    return _pair(data, 6, 2, "little")


def _is_webp(data: bytes) -> bool:
    """A RIFF file whose form type is WEBP."""

    return data.startswith(b"RIFF") and data[8:12] == b"WEBP"


#: Where a WebP's first chunk body starts: the 12-byte RIFF header, then the chunk's name and
#: its 4-byte length.
_WEBP_BODY: Final[int] = 20
_VP8L_SIGNATURE: Final[int] = 0x2F
_WEBP_CHUNKS: Final[dict[bytes, Callable[[bytes], tuple[int, int] | None]]] = {
    b"VP8X": _vp8x_size,
    b"VP8L": _vp8l_size,
    b"VP8 ": _vp8_size,
}
#: Each format the envelope accepts: how to recognise it, then how to read its size.
_READERS: Final[
    tuple[tuple[Callable[[bytes], bool], Callable[[bytes], tuple[int, int] | None]], ...]
] = (
    (lambda data: data.startswith(_PNG), _png_size),
    (lambda data: data.startswith(_GIF_SIGNATURES), _gif_size),
    (lambda data: data.startswith(_JPEG_START), _jpeg_size),
    (_is_webp, _webp_size),
)


__all__ = ["picture_size"]
