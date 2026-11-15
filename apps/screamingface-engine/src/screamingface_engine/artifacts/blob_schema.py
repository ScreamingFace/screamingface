"""The run blob store's value types: codes, errors, scope, policy, signatures, the sidecar.

FEATURE: image and PDF inputs (epic OME-1529; run blob store OME-1540). Split out of
`artifacts.blobs` (#1603 review round 3, module size); `artifacts.blobs` re-exports every public
name here, so importers keep saying `from screamingface_engine.artifacts.blobs import ...`.

INVARIANT (#1603 review round 2, item 3): the sidecar is a CLOSED schema — `parse_sidecar` is the
one place that decides what a stored record may say, for the read path and the ingest path alike.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from typing import Literal

BLOB_REF_PREFIX = "blob:sha256/"
SOURCE_NOT_FOUND = "source_not_found"
BLOB_DIGEST_MISMATCH = "x.blob_digest_mismatch"
# AIDEV-NOTE: the two codes below are new `x.*` url4 wire codes (owner decision 2026-10-28,
# Q4a) and, like the spec's other proposed codes, await Kevin's url4 wire sign-off.
BLOB_TOO_LARGE = "x.blob_too_large"
BLOB_UNSUPPORTED_MEDIA_TYPE = "x.blob_unsupported_media_type"

# WHY these five: they are exactly the spec F1b attachment types — the only files a v1 model call
# can carry natively. Anything else would be stored and then refused at the connector.
ATTACHMENT_MEDIA_TYPES = frozenset(
    {"image/png", "image/jpeg", "image/gif", "image/webp", "application/pdf"}
)
# WHY 8,000,000: the spec's per-run aggregate attachment cap (§4 `x.attachments_too_large`); no
# single blob can usefully exceed what a whole run may carry (owner decision 2026-10-28, Q4a).
DEFAULT_BLOB_MAX_BYTES = 8_000_000
# WHY 1024: a valid sidecar is `{"media_type": ..., "size_bytes": ...}` — under 100 bytes for every
# accepted type. A cap of its own keeps a hostile sidecar from costing the blob's 8 MB budget
# (#1603 review round 2, owner decision 2026-11-04, item 2).
SIDECAR_MAX_BYTES = 1024
# INVARIANT: the closed sidecar schema (item 3) — exactly these keys, nothing else.
_SIDECAR_KEYS = frozenset({"media_type", "size_bytes"})

# FEATURE: #1603 review (Khoa, 2026-11-02; owner decision 2026-11-03) — the store checks the
# file's first bytes against its declared type at ingest, so a stored blob is what its label says.
# Each entry: (offset, magic) pairs that must ALL match.
#
# INVARIANT: keys == ATTACHMENT_MEDIA_TYPES (pinned by a test). A type added to the attachment set
# needs an explicit decision here; a type WITHOUT a reliable signature (e.g. a plain-text format)
# must not be added to this table with a weak one — it would need its own WHY and a different
# check, because a label that cannot be verified is exactly what this table exists to refuse.
# WHY `%PDF-` at offset 0 only: Acrobat tolerates junk in the first 1024 bytes, but a strict
# check refuses nothing a conforming writer emits, and a looser one widens what passes as PDF.
# WHY WebP needs two parts: `RIFF` alone is also AVI and WAV; bytes 8-12 name the form type.
MEDIA_TYPE_SIGNATURES: dict[str, tuple[tuple[tuple[int, bytes], ...], ...]] = {
    "application/pdf": (((0, b"%PDF-"),),),
    "image/png": (((0, b"\x89PNG\r\n\x1a\n"),),),
    "image/jpeg": (((0, b"\xff\xd8\xff"),),),
    "image/gif": (((0, b"GIF87a"),), ((0, b"GIF89a"),)),
    "image/webp": (((0, b"RIFF"), (8, b"WEBP")),),
}

_RUN = re.compile(r"^[A-Za-z0-9]{1,128}$")
_ANONYMOUS = "anonymous"
# INVARIANT: every blob key lives below this prefix — the filesystem sweep walks only this tree.
BLOB_KEY_ROOT = "blobs"


class BlobError(Exception):
    """A blob the store refuses to keep or to serve. `code` is the spec §4 code."""

    code: str = ""
    permanent: bool = True


class BlobDigestMismatch(BlobError):
    """The bytes do not hash to the digest: at ingest a bad upload, at read store corruption."""

    code = BLOB_DIGEST_MISMATCH

    def __init__(self, sha256: str, *, at: Literal["ingest", "read"]) -> None:
        super().__init__(f"blob bytes do not hash to sha256:{sha256} ({at})")
        self.at = at


class BlobCorrupted(BlobDigestMismatch):
    """A stored blob the store will not serve: its metadata or its bytes break the contract.

    FEATURE: #1603 review round 2 (owner decision 2026-11-04, items 2 and 3) — an object past
    the read cap, a sidecar outside the closed schema, a recorded size or type that does not
    match the bytes, or (with `verify_signature`) bytes that are not their recorded type.

    WHY a subclass of the read-side `BlobDigestMismatch` and its code, not a new one: to the
    client it is the same fact — "the store's copy is not the file you uploaded" — permanent,
    and the two new `x.*` codes already await url4 wire sign-off; `detail` says which.
    """

    def __init__(self, sha256: str, reason: str) -> None:
        BlobError.__init__(self, f"stored blob sha256:{sha256} is corrupt: {reason}")
        self.at = "read"
        self.reason = reason


class BlobTooLarge(BlobError):
    code = BLOB_TOO_LARGE


class BlobUnsupportedMediaType(BlobError):
    code = BLOB_UNSUPPORTED_MEDIA_TYPE


class BlobContentMismatch(BlobUnsupportedMediaType):
    """The bytes do not open with the signature of the media type they are declared as.

    WHY the same code as an unaccepted type (no new wire code): to the client both mean "these
    bytes are not a file of a type this store keeps"; the `detail` says which, and the new
    `x.*` codes already await url4 wire sign-off (see BLOB_TOO_LARGE above).
    """


@dataclass(frozen=True)
class BlobScope:
    """One tenant + one run: the only key a blob can be read back under.

    `tenant` is `anonymous` or `u-<sha256 of the verified email>`, so the email never lands in a
    path or an object key and no email can spell the anonymous partition.
    """

    tenant: str
    run: str

    @classmethod
    def for_caller(cls, email: str | None, run: str) -> BlobScope:
        if _RUN.fullmatch(run) is None:
            # INVARIANT: the run id becomes a key segment; anything but plain alphanumerics could
            # climb out of its prefix. A capability topic is 64 alphanumerics, so this never
            # refuses a real one.
            raise ValueError("blob scope run id must be 1-128 ASCII letters or digits")
        stripped = (email or "").strip()
        if not stripped:
            return cls(tenant=_ANONYMOUS, run=run)
        return cls(tenant="u-" + hashlib.sha256(stripped.encode("utf-8")).hexdigest(), run=run)

    @property
    def key_prefix(self) -> str:
        return f"{BLOB_KEY_ROOT}/{self.tenant}/{self.run}"


@dataclass(frozen=True)
class StoredBlob:
    """The claim ticket of one blob: `ResultArtifact`'s shape plus the media type it carries."""

    sha256: str
    size_bytes: int
    media_type: str

    @property
    def ref(self) -> str:
        return f"{BLOB_REF_PREFIX}{self.sha256}"


@dataclass(frozen=True)
class BlobPolicy:
    """What the store accepts. Both limits are `Settings`-configurable on the App."""

    max_bytes: int = DEFAULT_BLOB_MAX_BYTES
    media_types: frozenset[str] = field(default=ATTACHMENT_MEDIA_TYPES)
    # WHY off by default and ON in the App (`app._build_blob_store`): the App is the only
    # ingest path (uploads, and OME-1543's write-through); the Runner only reads. A store built
    # bare keeps the original label-trusting behaviour its first tests pinned.
    verify_signature: bool = False


def encode_sidecar(blob: StoredBlob) -> bytes:
    """The closed-schema record stored next to a blob's bytes."""
    return json.dumps({"media_type": blob.media_type, "size_bytes": blob.size_bytes}).encode()


def parse_sidecar(
    sha256: str, raw: bytes, policy: BlobPolicy, size_bytes: int | None = None
) -> StoredBlob:
    """The record in `raw`, validated against the CLOSED schema and `policy`.

    `size_bytes`, when given, must equal the recorded size (the ingest path knows it before
    reading the data back; the read path checks it against the bytes instead).

    Raises:
        BlobCorrupted: not JSON, not exactly the two keys, a size that is not a non-negative int
            within the cap, or a type outside the policy.
    """
    try:
        meta = json.loads(raw)
    except ValueError:  # JSONDecodeError and UnicodeDecodeError are both ValueErrors
        raise BlobCorrupted(sha256, "metadata is not valid JSON") from None
    if not isinstance(meta, dict) or set(meta) != _SIDECAR_KEYS:
        raise BlobCorrupted(sha256, "metadata is not the closed sidecar schema")
    size, media = meta["size_bytes"], meta["media_type"]
    # WHY `type(...) is int`: `bool` is an `int` subclass, and `true` is not a size.
    if type(size) is not int or not 0 <= size <= policy.max_bytes:
        raise BlobCorrupted(sha256, "recorded size is not a size within the cap")
    if size_bytes is not None and size != size_bytes:
        raise BlobCorrupted(sha256, f"recorded size {size} is not {size_bytes}")
    if not isinstance(media, str) or media not in policy.media_types:
        raise BlobCorrupted(sha256, "recorded media type is not an accepted type")
    return StoredBlob(sha256=sha256, size_bytes=size, media_type=media)


def has_signature(media_type: str, body: bytes) -> bool:
    """Whether `body` opens with one of `media_type`'s signatures (absent type → False)."""
    return any(
        all(body[at : at + len(magic)] == magic for at, magic in alternative)
        for alternative in MEDIA_TYPE_SIGNATURES.get(media_type, ())
    )


def bare_media_type(media_type: str) -> str:
    """Spec F3 canonical spelling: lowercased, parameters dropped."""
    return media_type.split(";", 1)[0].strip().lower()
