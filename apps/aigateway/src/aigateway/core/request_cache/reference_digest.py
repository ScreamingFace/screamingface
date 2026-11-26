"""Today's cache key for a request that carries a Case file by blob reference (OME-1970).

FEATURE: Case files sent by blob reference. The Engine uploads each Case file (a picture or a
PDF) to the gateway once per run, then sends a **blob reference** where the file's base64 used to
be: the text ``blob:sha256/<64 hex>``, the SHA-256 of the file's bytes. Both stores that key a
request — the response cache and the pinned cache a published run is replayed from — hash the
request's canonical JSON with the file's base64 inside. Owner decision 2 (26 Nov): that key stays
exactly today's, so no cached answer or pinned copy is lost and no ``KEY_REVISION`` moves.

STORY: as a researcher I re-run a published Benchmark after the Engine switched to references,
and every answer it cached and every pinned copy it recorded inline still matches.

INVARIANT: there is no second writer of the canonical form here. The request is written by
`canonical_material`, the one writer, with each file replaced by a short placeholder; only the
placeholders are then swapped for the files' bytes on their way into the hash. So whatever
``canonical`` decides about separators, key order or escaping, this module inherits.

AIDEV-NOTE: like ``canonical``, this is a dependency-free leaf (stdlib plus ``canonical``), so
a lane or an out-of-repo tool can import it alone.
"""

from __future__ import annotations

import hashlib
import json
import re
import secrets
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, Final

from .canonical import CanonicalizationError, canonical_material

__all__ = [
    "BlobReference",
    "ReferencedFile",
    "ReferencedFileLookup",
    "UnknownBlobReference",
    "canonical_digest_with_references",
]

# A blob reference names a file by the lowercase hex SHA-256 of its bytes, nothing else.
_SHA256_HEX: Final = re.compile(r"[0-9a-f]{64}")
# WHY 1 MiB: a referenced file is escaped and hashed one slice at a time, so a call holds about
# three slices of extra memory (escaped text, its UTF-8 bytes) instead of a second copy of an
# 18 MB file. Larger slices save nothing measurable; smaller ones add per-slice overhead.
_FILE_SLICE_CHARS: Final = 1 << 20
# The placeholder walk stops descending a little past the canonical guard's own depth cap, so a
# cyclic or absurdly deep value costs the guard's `CanonicalizationError`, never a RecursionError.
_MAX_WALK_DEPTH: Final = 80
# 128 random bits per call: a caller cannot predict the placeholder, so no prompt text can
# contain one (and `canonical_digest_with_references` counts them anyway).
_NONCE_BYTES: Final = 16


@dataclass(frozen=True, slots=True)
class BlobReference:
    """Stands in key material exactly where a file's ``data:`` URI string would stand.

    It is the in-memory form of a blob reference. Only `canonical_digest_with_references`
    resolves it; every other cache entry point refuses it as an unsupported type, so a
    reference can never be keyed as anything but its file.
    """

    sha256: str

    def __post_init__(self) -> None:
        """Refuse anything that is not one lowercase hex SHA-256."""
        if not _SHA256_HEX.fullmatch(self.sha256):
            raise ValueError("a blob reference names a lowercase hex SHA-256")

    @property
    def text(self) -> str:
        """The reference as it travels on the wire: ``blob:sha256/<64 hex>``."""
        return f"blob:sha256/{self.sha256}"


@dataclass(frozen=True, slots=True)
class ReferencedFile:
    """One stored file as today's inline request carries it: its media type and its base64."""

    media_type: str
    base64_text: str


# What the digest asks for each reference: the file stored under that SHA-256, or None.
# AIDEV-NOTE: the async callers run the digest in a worker thread, so the lookup runs there
# too and must be a plain read of in-memory state (no await, no I/O).
type ReferencedFileLookup = Callable[[str], ReferencedFile | None]


class UnknownBlobReference(LookupError):
    """A reference names a file the gateway does not hold, so the request has no key.

    WHY a ``LookupError`` and NOT a `CanonicalizationError`: the cache lanes turn a
    `CanonicalizationError` into a silent bypass, but a request whose file is gone cannot be
    dispatched either. The caller must hear "unknown file" and upload it again.
    """

    def __init__(self, sha256: str) -> None:
        """Name the missing file by a 12-character digest prefix, never by its content."""
        super().__init__(f"no stored file for blob reference sha256/{sha256[:12]}")
        self.sha256 = sha256


def _with_placeholders(value: Any, nonce: str, depth: int) -> tuple[Any, int]:
    """``value`` with each `BlobReference` swapped for its placeholder text, and their count.

    Only dicts, lists and tuples are walked, exactly the containers ``json.dumps`` writes, so a
    reference anywhere else stays a `BlobReference` and the canonical guard refuses it.
    """
    if isinstance(value, BlobReference):
        return f"{nonce}.{value.sha256}", 1
    if depth > _MAX_WALK_DEPTH:
        return value, 0
    if isinstance(value, dict):
        swapped: dict[Any, Any] = {}
        total: int = 0
        for key, nested in value.items():
            swapped[key], count = _with_placeholders(nested, nonce, depth + 1)
            total += count
        return swapped, total
    if isinstance(value, (list, tuple)):
        items: list[Any] = []
        total = 0
        for item in value:
            swapped_item, count = _with_placeholders(item, nonce, depth + 1)
            items.append(swapped_item)
            total += count
        return items, total
    return value, 0


def _update_escaped(digest: Any, text: str) -> None:
    """Hash the inside of ``text``'s JSON string literal, without its two quotes.

    WHY through ``json.dumps`` even for base64, which never needs escaping: if a stored text
    ever held a quote or a control character, the bytes would still be exactly the ones
    ``json.dumps`` writes for the whole string. JSON escapes one character at a time, so
    escaping slices and joining them equals escaping the whole.
    """
    quoted: bytes = json.dumps(text, ensure_ascii=False).encode("utf-8")
    digest.update(memoryview(quoted)[1:-1])


def canonical_digest_with_references(
    mapping: Mapping[str, Any], files: ReferencedFileLookup
) -> str:
    """`canonical_digest` of a request whose files travel by reference: today's key, unchanged.

    Think of it as the inline request rebuilt inside the hash's input only. The hash is fed the
    exact bytes today's inline request hashes: the JSON before the file, then the stored file as
    its ``data:`` URI, then the JSON after. The whole string is never built, so an 18 MB file is
    not copied into a second 18 MB string.

    Stages, in execution order:

    1. Placeholders. Copy the request's containers (not its strings), swapping each reference
       for ``<nonce>.<sha256>``, where the nonce is fresh random hex for this call.
    2. Canonical form. Write that small request with `canonical_material`, the one writer: the
       same guard, separators, key order and escaping as every cache key. Each placeholder is
       hex, so it appears in the text as ``"<nonce>.<sha256>"``, quotes included.
    3. Count. The placeholders found must equal the references swapped. They always do, since
       nobody else knows the nonce; a mismatch is refused rather than keyed.
    4. Hash. Feed the text between placeholders as UTF-8, and in each placeholder's place feed
       ``"data:<media type>;base64,`` plus the stored base64 in 1 MiB slices plus ``"``. A file
       referenced twice is hashed twice, as it appears twice in today's JSON.

    Worked example: ``{"q": "hi", "file": BlobReference("ab…")}`` with the stored file
    ``ReferencedFile("image/png", "iVBO")`` and nonce ``n1``. Stage 2 writes
    ``{"file":"n1.ab…","q":"hi"}``. Stage 4 feeds ``{"file":`` · ``"data:image/png;base64,`` ·
    ``iVBO`` · ``"`` · ``,"q":"hi"}``, which joined is
    ``{"file":"data:image/png;base64,iVBO","q":"hi"}``: exactly what `canonical_material`
    writes for the inline request, so the two digests are equal.

    Args:
        mapping: the key material with each file's ``data:`` URI string replaced by a
            `BlobReference`. Not modified.
        files: the gateway's lookup from SHA-256 to the stored file. Called once per reference
            occurrence, from whatever thread runs this function.

    Returns:
        The hex SHA-256 only, as `canonical_digest`; the material never leaves this function.

    Raises:
        CanonicalizationError: as `canonical_digest`.
        TypeError: as `canonical_digest`, for a value ``json.dumps`` cannot write.
        UnknownBlobReference: ``files`` holds no file for a reference.
    """
    # Stage 1 — placeholders.
    nonce: str = secrets.token_hex(_NONCE_BYTES)
    swapped, references = _with_placeholders(mapping, nonce, depth=0)
    # Stage 2 — the one canonical writer, on a request now only a few KB long.
    material: str = canonical_material(swapped)
    # Stage 3 — count.
    placeholder = re.compile(f'"{nonce}\\.([0-9a-f]{{64}})"')
    found: list[re.Match[str]] = list(placeholder.finditer(material))
    if len(found) != references:
        raise CanonicalizationError("key material holds an ambiguous blob reference")
    # Stage 4 — hash, swapping each placeholder for its stored file.
    digest = hashlib.sha256()
    position: int = 0
    for match in found:
        file: ReferencedFile | None = files(match[1])
        if file is None:
            raise UnknownBlobReference(match[1])
        digest.update(material[position : match.start()].encode("utf-8"))
        digest.update(b'"')
        _update_escaped(digest, f"data:{file.media_type};base64,")
        text: str = file.base64_text
        for start in range(0, len(text), _FILE_SLICE_CHARS):
            _update_escaped(digest, text[start : start + _FILE_SLICE_CHARS])
        digest.update(b'"')
        position = match.end()
    digest.update(material[position:].encode("utf-8"))
    return digest.hexdigest()
