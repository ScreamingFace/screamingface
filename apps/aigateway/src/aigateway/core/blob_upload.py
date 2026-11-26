"""Read one uploaded Case file off the wire: capped, hashed and type-checked as it arrives.

FEATURE: Case files by blob reference (OME-1970, PR 4). A **Case** is one Benchmark question;
its pictures and PDFs used to ride every model call inline as base64. Now the Engine uploads each
file once per run (`routes/blobs.py`), and each call carries a **blob reference**, the text
`blob:sha256/<64 hex>`, the SHA-256 of the file's bytes. This module is the read half of that
upload: it turns a request body stream into verified bytes, or a typed refusal.

INVARIANT: the reader holds at most `max_bytes` of the body. The chunk that would cross the cap is
refused and dropped, and nothing after it is pulled off the connection.
INVARIANT: no refusal raised here carries file bytes; a message names sizes, limits and types only.
"""

from __future__ import annotations

import hashlib
from collections.abc import AsyncIterator
from dataclasses import dataclass

from .errors import AigwError

# WHY 15,000,000 (OME-1970 decision 4): the PDF floor. Probed on 24 and 26 Nov 2026 through
# OpenRouter pinned to Bedrock, a one-PDF request passed at 14.8 MB on disk (19.73 MB of base64)
# and was refused at 15.3 MB (20.40 MB of base64, "malformed JSON"), so Bedrock's per-PDF limit is
# ~20,000,000 bytes of base64, ~15,000,000 on disk. A larger file could not be sent to every host
# OpenRouter may pick, so the gateway does not hold one. Pictures have a lower floor (5 MiB of
# base64), which the importer checks at seal time; this cap is per file of any allowed type.
MAX_BLOB_UPLOAD_BYTES: int = 15_000_000

# The longest signature below needs 12 bytes (WebP's form type sits at bytes 8-12).
SIGNATURE_PREFIX_BYTES: int = 12

# FEATURE: only the five types a model call can carry natively are stored, recognised by the
# file's leading bytes, never by a label the caller sends. Each entry: (offset, magic) pairs that
# must all match. The same five and the same signatures as the Engine's run blob store
# (`artifacts/blob_schema.py::MEDIA_TYPE_SIGNATURES`) and its picture import (`picture_input.py`);
# copied, not imported, because apps never import each other.
# WHY `%PDF-` at offset 0 only: a conforming writer always starts there; a looser check widens
# what passes as PDF.
# WHY WebP needs two parts: `RIFF` alone is also AVI and WAV; bytes 8-12 name the form type.
_SIGNATURES: tuple[tuple[str, tuple[tuple[int, bytes], ...]], ...] = (
    ("image/png", ((0, b"\x89PNG\r\n\x1a\n"),)),
    ("image/jpeg", ((0, b"\xff\xd8\xff"),)),
    ("image/gif", ((0, b"GIF87a"),)),
    ("image/gif", ((0, b"GIF89a"),)),
    ("image/webp", ((0, b"RIFF"), (8, b"WEBP"))),
    ("application/pdf", ((0, b"%PDF-"),)),
)


class BlobUploadRefused(AigwError):
    """An upload the gateway will not store; the route maps each kind to its typed answer."""


class BlobTooLarge(BlobUploadRefused):
    """The body is longer than the per-file cap."""

    def __init__(self, limit: int) -> None:
        self.limit = limit
        super().__init__(f"the file is over the upload limit of {limit:,} bytes")


class BlobDigestMismatch(BlobUploadRefused):
    """The bytes received do not hash to the SHA-256 the upload was labelled with."""

    def __init__(self) -> None:
        super().__init__("the uploaded bytes do not hash to the SHA-256 in the path")


class BlobUnsupportedMediaType(BlobUploadRefused):
    """The file's leading bytes are none of png, jpeg, gif, webp or pdf."""

    def __init__(self) -> None:
        super().__init__("the file is not a png, jpeg, gif, webp or pdf by its leading bytes")


@dataclass(frozen=True, slots=True)
class ReceivedFile:
    """One upload, read whole and verified: its bytes, their SHA-256 and the type they name."""

    data: bytes
    digest: str
    media_type: str

    def __repr__(self) -> str:
        # INVARIANT: a repr (a traceback, a debug line) never carries the file's bytes.
        size_bytes: int = len(self.data)
        return (
            f"ReceivedFile(digest={self.digest[:12]}…, media_type={self.media_type}, "
            f"size_bytes={size_bytes})"
        )


def base64_length(size_bytes: int) -> int:
    """How many base64 characters a file of ``size_bytes`` encodes to (4 per started 3 bytes)."""
    return 4 * ((size_bytes + 2) // 3)


def media_type_of(leading: bytes) -> str | None:
    """The allowed type these leading bytes start, or ``None`` when they start none of the five."""
    for media_type, parts in _SIGNATURES:
        if all(leading[offset : offset + len(magic)] == magic for offset, magic in parts):
            return media_type
    return None


async def receive_upload(
    chunks: AsyncIterator[bytes],
    *,
    digest: str,
    max_bytes: int = MAX_BLOB_UPLOAD_BYTES,
) -> ReceivedFile:
    """Read an upload body chunk by chunk and hand back the file only if every check passes.

    In one line: each chunk is counted, hashed and (once 12 bytes are in) type-checked as it
    arrives, and the first broken rule stops the read before the chunk that broke it is kept.

    Stages, in the order they run on each chunk:

    1. Count: the chunk's length is added to the bytes already held. If the total would pass
       ``max_bytes``, raise ``BlobTooLarge`` *before* keeping the chunk, and pull nothing more —
       e.g. 1,000,000-byte chunks against the 15,000,000 cap: chunks 1-15 are kept, chunk 16 is
       refused, chunk 17 is never read.
    2. Fingerprint: the chunk is fed to a running SHA-256, so the digest is ready at the end
       without a second pass over up to 15 MB.
    3. Type: as soon as 12 bytes are held (the longest signature), the leading bytes must start
       one of the five allowed types, else ``BlobUnsupportedMediaType``. A junk body is refused
       on its first chunk rather than after 15 MB.

    At the end of the stream: a body shorter than 12 bytes gets its type check now, then the
    finished SHA-256 must equal ``digest``, else ``BlobDigestMismatch``.

    Args:
        chunks: the request body as it arrives (Starlette's ``request.stream()``). Each chunk is
            consumed once; the iterator is abandoned, not drained, on a refusal.
        digest: the SHA-256 the uploader labelled the file with, 64 lowercase hex characters
            (the route has already checked the spelling).
        max_bytes: the most file bytes accepted; the route passes the per-file cap.

    Returns:
        The file's bytes, the SHA-256 they were verified to have, and the type their leading
        bytes name. Nothing is stored here; the caller decides where the bytes go.

    Raises:
        BlobTooLarge, BlobUnsupportedMediaType, BlobDigestMismatch: as staged above.
    """
    held: bytearray = bytearray()
    hasher = hashlib.sha256()
    media_type: str | None = None
    async for chunk in chunks:
        # Stage 1 — count. INVARIANT: the crossing chunk is refused before it is kept.
        if len(held) + len(chunk) > max_bytes:
            raise BlobTooLarge(max_bytes)
        held += chunk
        # Stage 2 — fingerprint.
        hasher.update(chunk)
        # Stage 3 — type, once the longest signature fits.
        if media_type is None and len(held) >= SIGNATURE_PREFIX_BYTES:
            media_type = _required_media_type(bytes(held[:SIGNATURE_PREFIX_BYTES]))
    if media_type is None:
        media_type = _required_media_type(bytes(held))
    if hasher.hexdigest() != digest:
        raise BlobDigestMismatch()
    return ReceivedFile(data=bytes(held), digest=digest, media_type=media_type)


def _required_media_type(leading: bytes) -> str:
    """The allowed type of these leading bytes, or a refusal when there is none."""
    media_type: str | None = media_type_of(leading)
    if media_type is None:
        raise BlobUnsupportedMediaType()
    return media_type


__all__ = [
    "MAX_BLOB_UPLOAD_BYTES",
    "BlobDigestMismatch",
    "BlobTooLarge",
    "BlobUnsupportedMediaType",
    "BlobUploadRefused",
    "ReceivedFile",
    "base64_length",
    "media_type_of",
    "receive_upload",
]
