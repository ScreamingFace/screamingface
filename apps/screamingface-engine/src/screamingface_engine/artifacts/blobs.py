"""The run blob store: content-addressed files scoped to one tenant + run (OME-1540).

FEATURE: image and PDF inputs (epic OME-1529; spec
`docs/spec/2026-10-16-OME-1535-file-input-execution.md` F1, F3, §4).
STORY: as a url4 client I upload a picture under my run's capability token, get back
`blob:sha256/<hex>`, and every model call in that run can read it — and no other run can.

Layout: one data object and one metadata object per blob, both below
`blobs/<tenant>/<run>/<hex>` in the same filesystem directory or S3 bucket the result artifacts
use. Result parcels sit FLAT at that root under 64-hex names, so the two never collide, and the
artifact sweep (which only matches flat 64-hex names) never touches a blob.

INVARIANT (F3 authorization): a digest is NOT a bearer capability. Every key carries the
(tenant, run) scope, so a read from any other scope finds nothing — the same `None` a digest
nobody uploaded gives. The scope comes from the caller's verified token and identity (the App) or
the run's own environment (the Runner), never from the ref.
INVARIANT (F3 integrity): sha256 is verified at ingest (nothing is stored under a digest its
bytes do not match) and on EVERY read. A read mismatch is store corruption: logged as such and
raised as the permanent `x.blob_digest_mismatch`, never served.
INVARIANT: logs carry the digest and the size, never the bytes, the email or the run id (the
run id is the capability topic, a bearer secret).

AIDEV-NOTE: a SHARED LEAF of the layering gate (it lives under `artifacts`): the App serves the
routes, the Runner binds `ScopedBlobReader` for its model calls. Nothing HTTP-framework-shaped
belongs here — `rest.blobs` renders these errors as problems.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import re
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, Protocol

from screamingface_engine.artifacts.s3 import S3ArtifactStore

_logger = logging.getLogger(__name__)

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

_HEX = re.compile(r"^[0-9a-f]{64}$")
_RUN = re.compile(r"^[A-Za-z0-9]{1,128}$")
_ANONYMOUS = "anonymous"
_ROOT_PREFIX = "blobs"
_SHA256_DIGEST_PREFIX = "sha256:"


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


class BlobTooLarge(BlobError):
    code = BLOB_TOO_LARGE


class BlobUnsupportedMediaType(BlobError):
    code = BLOB_UNSUPPORTED_MEDIA_TYPE


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
        return f"{_ROOT_PREFIX}/{self.tenant}/{self.run}"


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


class BlobObjects(Protocol):
    """The byte-object backend under the store: keyed put/get plus TTL reclamation."""

    def put(self, key: str, data: bytes) -> None: ...

    def get(self, key: str) -> bytes | None: ...

    def sweep(self, ttl_seconds: float, *, now: float | None = None) -> int: ...


class FilesystemBlobObjects:
    """Blob objects as files below `<root>/blobs/` — `root` is the artifacts directory."""

    def __init__(self, root: Path) -> None:
        self._root = root

    def put(self, key: str, data: bytes) -> None:
        # WHY tmp + os.replace: a crash mid-write never leaves a half-blob under a valid key.
        # A rewrite also re-stamps mtime, so a repeat upload restarts the blob's TTL clock.
        final = self._root / key
        final.parent.mkdir(parents=True, exist_ok=True)
        tmp = final.parent / f".{final.name}.{uuid.uuid4().hex}.tmp"
        tmp.write_bytes(data)
        os.replace(tmp, final)

    def get(self, key: str) -> bytes | None:
        try:
            return (self._root / key).read_bytes()
        except FileNotFoundError:
            return None

    def sweep(self, ttl_seconds: float, *, now: float | None = None) -> int:
        """Delete blob files (and `.tmp` leftovers) older than `ttl_seconds`, by mtime.

        INVARIANT: only below `blobs/`; result parcels at the root are the artifact sweep's.
        INVARIANT: tolerant of concurrent life — a file gone between listing and stat is done.
        """
        tree = self._root / _ROOT_PREFIX
        if not tree.is_dir():
            return 0
        cutoff = (time.time() if now is None else now) - ttl_seconds
        removed = 0
        for path in tree.rglob("*"):
            try:
                expired = path.is_file() and path.stat().st_mtime < cutoff
            except FileNotFoundError:
                continue
            if expired:
                path.unlink(missing_ok=True)
                removed += 1
        return removed


class S3BlobObjects:
    """Blob objects in the artifact bucket, below the `blobs/` key prefix."""

    def __init__(self, store: S3ArtifactStore) -> None:
        self._store = store

    def put(self, key: str, data: bytes) -> None:
        self._store.put_object(key, data)

    def get(self, key: str) -> bytes | None:
        return self._store.get_object(key)

    def sweep(self, ttl_seconds: float, *, now: float | None = None) -> int:
        """Always 0 — expiry is the bucket's lifecycle rule, exactly as for result artifacts.

        AIDEV-NOTE: the operator's lifecycle rule must cover the `blobs/` prefix too.
        """
        return 0


class BlobStore:
    """Ingest and read blobs within one (tenant, run) scope, verifying sha256 both ways."""

    def __init__(self, objects: BlobObjects, policy: BlobPolicy | None = None) -> None:
        self._objects = objects
        self._policy = policy or BlobPolicy()

    @property
    def objects(self) -> BlobObjects:
        """The backend this store keeps its bytes in (which one the wiring selected)."""
        return self._objects

    def ingest(
        self, scope: BlobScope, sha256: str, media_type: str, body: bytes
    ) -> tuple[StoredBlob, bool]:
        """Keep `body` under `sha256` in `scope`; `(blob, created)`. Idempotent per scope.

        Raises:
            BlobDigestMismatch: `body` does not hash to `sha256` (or `sha256` is malformed).
            BlobTooLarge: `body` exceeds the policy cap.
            BlobUnsupportedMediaType: the bare media type is not on the allowlist.
        """
        bare = _bare_media_type(media_type)
        if bare not in self._policy.media_types:
            raise BlobUnsupportedMediaType(f"media type {bare!r} is not accepted for blobs")
        if len(body) > self._policy.max_bytes:
            raise BlobTooLarge(
                f"blob of {len(body)} bytes exceeds the {self._policy.max_bytes}-byte cap"
            )
        if _HEX.fullmatch(sha256) is None or hashlib.sha256(body).hexdigest() != sha256:
            named = sha256 if _HEX.fullmatch(sha256) else "<malformed>"
            raise BlobDigestMismatch(named, at="ingest")
        key = f"{scope.key_prefix}/{sha256}"
        existing = self._meta(key)
        # WHY first-write-wins on the media type: a ref already handed out must not change type
        # under its holder. The data is rewritten anyway: it heals a corrupt copy and restarts
        # the TTL clock.
        blob = existing or StoredBlob(sha256=sha256, size_bytes=len(body), media_type=bare)
        # INVARIANT: data before metadata — a blob is readable only once both exist, so a crash
        # between the two leaves an unreadable orphan for the sweep, never a half-blob.
        self._objects.put(key, body)
        self._objects.put(
            f"{key}.json",
            json.dumps({"media_type": blob.media_type, "size_bytes": blob.size_bytes}).encode(),
        )
        _logger.info("blob ingested digest=sha256:%s size=%d", sha256, len(body))
        return blob, existing is None

    def read(self, scope: BlobScope, sha256: str) -> tuple[StoredBlob, bytes] | None:
        """The verified blob and its bytes, or None when absent, out of scope or malformed.

        Raises:
            BlobDigestMismatch: the stored bytes no longer hash to `sha256` (store corruption).
        """
        if _HEX.fullmatch(sha256) is None:
            return None
        key = f"{scope.key_prefix}/{sha256}"
        blob = self._meta(key)
        body = None if blob is None else self._objects.get(key)
        if blob is None or body is None:
            return None
        if hashlib.sha256(body).hexdigest() != sha256:
            _logger.error(
                "blob store corruption: stored bytes do not hash to digest=sha256:%s size=%d",
                sha256,
                len(body),
            )
            raise BlobDigestMismatch(sha256, at="read")
        return blob, body

    def sweep(self, ttl_seconds: float, *, now: float | None = None) -> int:
        """Reclaim blobs older than `ttl_seconds` (the artifact TTL — owner decision Q4a)."""
        return self._objects.sweep(ttl_seconds, now=now)

    def _meta(self, key: str) -> StoredBlob | None:
        raw = self._objects.get(f"{key}.json")
        if raw is None:
            return None
        meta = json.loads(raw)
        return StoredBlob(
            sha256=key.rsplit("/", 1)[-1],
            size_bytes=int(meta["size_bytes"]),
            media_type=str(meta["media_type"]),
        )


class ScopedBlobReader:
    """The engine's `BlobReader` port (OME-1545) over this store, bound to ONE tenant + run.

    `read("sha256:<hex>")` returns the verified bytes, or None for anything not readable in this
    scope (absent, other run, other tenant, another digest spelling) — F3's `source_not_found`.
    Store corruption raises `BlobDigestMismatch` rather than returning bytes known to be wrong.
    """

    def __init__(self, store: BlobStore, scope: BlobScope) -> None:
        self._store = store
        self._scope = scope

    async def read(self, digest: str) -> bytes | None:
        if not digest.startswith(_SHA256_DIGEST_PREFIX):
            return None
        # WHY to_thread: the backends are sync and S3 makes a blocking round trip.
        found = await asyncio.to_thread(
            self._store.read, self._scope, digest[len(_SHA256_DIGEST_PREFIX) :]
        )
        return None if found is None else found[1]


def _bare_media_type(media_type: str) -> str:
    """Spec F3 canonical spelling: lowercased, parameters dropped."""
    return media_type.split(";", 1)[0].strip().lower()


__all__ = [
    "ATTACHMENT_MEDIA_TYPES",
    "BLOB_DIGEST_MISMATCH",
    "BLOB_REF_PREFIX",
    "BLOB_TOO_LARGE",
    "BLOB_UNSUPPORTED_MEDIA_TYPE",
    "DEFAULT_BLOB_MAX_BYTES",
    "SOURCE_NOT_FOUND",
    "BlobDigestMismatch",
    "BlobError",
    "BlobObjects",
    "BlobPolicy",
    "BlobScope",
    "BlobStore",
    "BlobTooLarge",
    "BlobUnsupportedMediaType",
    "FilesystemBlobObjects",
    "S3BlobObjects",
    "ScopedBlobReader",
    "StoredBlob",
]
