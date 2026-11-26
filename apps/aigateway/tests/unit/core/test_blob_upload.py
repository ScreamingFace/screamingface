"""Reading one uploaded file off the wire: capped, hashed and type-checked as it arrives (OME-1970).

FEATURE: Case files by blob reference (OME-1970, PR 4; decision 4).
INVARIANT: the reader never holds more than the per-file cap. The chunk that would cross the cap
is refused and dropped, and no chunk after it is pulled off the connection.
"""

from __future__ import annotations

import hashlib
from collections.abc import AsyncIterator

import pytest

from aigateway.core.blob_upload import (
    MAX_BLOB_UPLOAD_BYTES,
    BlobDigestMismatch,
    BlobTooLarge,
    BlobUnsupportedMediaType,
    receive_upload,
)

PNG = b"\x89PNG\r\n\x1a\n" + b"p" * 64
JPEG = b"\xff\xd8\xff\xe0" + b"j" * 64
GIF87 = b"GIF87a" + b"g" * 64
GIF89 = b"GIF89a" + b"g" * 64
WEBP = b"RIFF\x00\x00\x00\x00WEBP" + b"w" * 64
PDF = b"%PDF-1.7\n" + b"d" * 64


class _Wire:
    """An upload body arriving in fixed chunks; counts how many chunks the reader pulled."""

    def __init__(self, chunks: list[bytes] | None = None, *, endless: bytes | None = None) -> None:
        self._chunks: list[bytes] = list(chunks or [])
        self._endless: bytes | None = endless
        self.pulled: int = 0

    async def stream(self) -> AsyncIterator[bytes]:
        """Yield the chunks, or the same chunk forever for an endless body."""
        if self._endless is not None:
            while True:
                self.pulled += 1
                yield self._endless
        for chunk in self._chunks:
            self.pulled += 1
            yield chunk


def _split(payload: bytes, size: int) -> list[bytes]:
    return [payload[i : i + size] for i in range(0, len(payload), size)]


def test_the_cap_is_fifteen_million_bytes_the_pdf_floor() -> None:
    # WHY pinned: decision 4 — Bedrock refuses a PDF over ~20,000,000 bytes of base64, which is
    # ~15,000,000 bytes on disk; a larger upload could never be sent on every host anyway.
    assert MAX_BLOB_UPLOAD_BYTES == 15_000_000


@pytest.mark.parametrize(
    ("payload", "media_type"),
    [
        (PNG, "image/png"),
        (JPEG, "image/jpeg"),
        (GIF87, "image/gif"),
        (GIF89, "image/gif"),
        (WEBP, "image/webp"),
        (PDF, "application/pdf"),
    ],
)
@pytest.mark.asyncio
async def test_each_allowed_type_is_read_with_its_digest_and_type(
    payload: bytes, media_type: str
) -> None:
    wire = _Wire(_split(payload, 7))

    received = await receive_upload(wire.stream(), digest=hashlib.sha256(payload).hexdigest())

    assert received.data == payload
    assert received.media_type == media_type
    assert received.digest == hashlib.sha256(payload).hexdigest()


@pytest.mark.parametrize(
    "payload",
    [
        b"<svg xmlns='http://www.w3.org/2000/svg'/>",
        b"RIFF\x00\x00\x00\x00WAVEfmt ",  # RIFF but not WEBP: a WAV file
        b"PK\x03\x04 a zip file",
        b"%PD",  # too short to be a PDF
        b"",
    ],
)
@pytest.mark.asyncio
async def test_a_file_that_is_none_of_the_five_types_is_refused(payload: bytes) -> None:
    with pytest.raises(BlobUnsupportedMediaType):
        await receive_upload(
            _Wire(_split(payload, 4) or [b""]).stream(),
            digest=hashlib.sha256(payload).hexdigest(),
        )


@pytest.mark.asyncio
async def test_a_wrong_type_is_refused_from_its_leading_bytes_without_reading_the_rest() -> None:
    wire = _Wire(endless=b"MZ" + b"\x00" * 1022)  # a Windows executable, 1 KiB chunks forever

    with pytest.raises(BlobUnsupportedMediaType):
        await receive_upload(wire.stream(), digest="0" * 64)

    assert wire.pulled == 1


@pytest.mark.asyncio
async def test_bytes_that_do_not_hash_to_the_named_digest_are_refused() -> None:
    other_digest: str = hashlib.sha256(b"a different file").hexdigest()

    with pytest.raises(BlobDigestMismatch):
        await receive_upload(_Wire(_split(PDF, 16)).stream(), digest=other_digest)


@pytest.mark.asyncio
async def test_a_file_exactly_at_the_cap_is_read() -> None:
    payload: bytes = PDF + b"x" * (1000 - len(PDF))

    received = await receive_upload(
        _Wire(_split(payload, 100)).stream(),
        digest=hashlib.sha256(payload).hexdigest(),
        max_bytes=1000,
    )

    assert len(received.data) == 1000


@pytest.mark.asyncio
async def test_one_byte_over_the_cap_is_refused() -> None:
    payload: bytes = PDF + b"x" * (1001 - len(PDF))

    with pytest.raises(BlobTooLarge):
        await receive_upload(
            _Wire(_split(payload, 100)).stream(),
            digest=hashlib.sha256(payload).hexdigest(),
            max_bytes=1000,
        )


@pytest.mark.asyncio
async def test_an_oversize_body_is_refused_on_the_crossing_chunk_and_never_read_further() -> None:
    # A PDF arriving in 1,000,000-byte chunks forever, against the real 15,000,000-byte cap:
    # chunks 1-15 fit exactly, chunk 16 crosses. If the reader buffered past the cap it would
    # keep pulling (this body never ends), so `pulled == 16` proves it stopped at the cap.
    chunk: bytes = PDF + b"x" * (1_000_000 - len(PDF))
    wire = _Wire(endless=chunk)

    with pytest.raises(BlobTooLarge):
        await receive_upload(wire.stream(), digest="0" * 64)

    assert wire.pulled == 16
