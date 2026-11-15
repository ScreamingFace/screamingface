"""The run blob store: content-addressed files scoped to one tenant + run (OME-1540).

FEATURE: image and PDF inputs (epic OME-1529; spec
`docs/spec/2026-10-16-OME-1535-file-input-execution.md` F1, F3, §4).
STORY: as a url4 client I upload a picture under my run's capability token, get back
`blob:sha256/<hex>`, and every model call in that run can read it — and no other run can.

Layout: one data object and one metadata object per blob, both below
`blobs/<tenant>/<run>/<hex>` in the blob store's OWN directory or bucket (#1603 review, owner
decision 2026-11-03; `artifacts.wiring.blob_objects_from_values`), so a full blob store fails
uploads and never result delivery. With `URL4_CLOUD_BLOB_STORE` unset there is NO blob store
(fail closed, #1603 review round 2). Even a store sharing a root with result parcels could not
collide: parcels sit FLAT under 64-hex names, and the artifact sweep only matches those.

INVARIANT (F3 authorization): a digest is NOT a bearer capability. Every key carries the
(tenant, run) scope, so a read from any other scope finds nothing — the same `None` a digest
nobody uploaded gives. The scope comes from the caller's verified token and identity (the App) or
the run's own environment (the Runner), never from the ref.
INVARIANT (F3 integrity): sha256 is verified at ingest (nothing is stored under a digest its
bytes do not match) and on EVERY read. A read mismatch is store corruption: logged as such and
raised as the permanent `x.blob_digest_mismatch`, never served.
INVARIANT: logs carry the digest and the size, never the bytes, the email or the run id (the
run id is the capability topic, a bearer secret).

Modules: `blob_schema` (codes, errors, scope, policy, signatures, the closed sidecar),
`blob_objects` (the filesystem and S3 backends), and this one (the store and the Runner's reader).
Every public name of the three is importable from here (#1603 review round 3, module size).

AIDEV-NOTE: a SHARED LEAF of the layering gate (it lives under `artifacts`): the App serves the
routes, the Runner binds `ScopedBlobReader` for its model calls. Nothing HTTP-framework-shaped
belongs here — `rest.blobs` renders these errors as problems.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import re

from screamingface_engine.artifacts.blob_objects import (
    BlobObjects,
    BoundedBlobObjects,
    FilesystemBlobObjects,
    S3BlobObjects,
    UnboundedObjects,
)
from screamingface_engine.artifacts.blob_schema import (
    ATTACHMENT_MEDIA_TYPES,
    BLOB_DIGEST_MISMATCH,
    BLOB_REF_PREFIX,
    BLOB_TOO_LARGE,
    BLOB_UNSUPPORTED_MEDIA_TYPE,
    DEFAULT_BLOB_MAX_BYTES,
    MEDIA_TYPE_SIGNATURES,
    SIDECAR_MAX_BYTES,
    SOURCE_NOT_FOUND,
    BlobContentMismatch,
    BlobCorrupted,
    BlobDigestMismatch,
    BlobError,
    BlobPolicy,
    BlobScope,
    BlobTooLarge,
    BlobUnsupportedMediaType,
    StoredBlob,
    bare_media_type,
    encode_sidecar,
    has_signature,
    parse_sidecar,
)

_logger = logging.getLogger(__name__)

_HEX = re.compile(r"^[0-9a-f]{64}$")
_SHA256_DIGEST_PREFIX = "sha256:"


class BlobStore:
    """Ingest and read blobs within one (tenant, run) scope, verifying sha256 both ways."""

    def __init__(self, objects: BlobObjects, policy: BlobPolicy | None = None) -> None:
        self._objects = objects
        self._backend: BoundedBlobObjects = (
            objects if isinstance(objects, BoundedBlobObjects) else UnboundedObjects(objects)
        )
        self._policy = policy or BlobPolicy()

    @property
    def objects(self) -> BlobObjects:
        """The backend this store keeps its bytes in (which one the wiring selected)."""
        return self._objects

    def ingest(
        self, scope: BlobScope, sha256: str, media_type: str, body: bytes
    ) -> tuple[StoredBlob, bool]:
        """Keep `body` under `sha256` in `scope`; `(blob, created)`. Idempotent per scope.

        INVARIANT (#1603 review round 2, item 5): of any number of racing first uploads, exactly
        one returns `created=True` — the metadata's first write is create-exclusive (on Garage,
        which ignores S3 conditional writes, see `S3ArtifactStore.put_object_if_absent`).

        Raises:
            BlobDigestMismatch: `body` does not hash to `sha256` (or `sha256` is malformed).
            BlobTooLarge: `body` exceeds the policy cap.
            BlobUnsupportedMediaType: the bare media type is not on the allowlist.
            BlobContentMismatch: with `verify_signature`, the bytes are not that type.
        """
        bare = self._admit(sha256, media_type, body)
        key = f"{scope.key_prefix}/{sha256}"
        existing, corrupt = self._existing(key, body)
        # WHY first-write-wins on the media type: a ref already handed out must not change type
        # under its holder. The data is rewritten anyway: it heals a corrupt copy and restarts
        # the TTL clock.
        # INVARIANT: data before metadata — a blob is readable only once both exist, so a crash
        # between the two leaves an unreadable orphan for the sweep, never a half-blob.
        self._backend.put(key, body)
        blob = StoredBlob(sha256=sha256, size_bytes=len(body), media_type=bare)
        if existing is not None or corrupt:
            # A repeat upload rewrites the record too, so its TTL clock restarts with the data's.
            # A corrupt record is replaced by the verified upload's — corruption recovery, which
            # repairs a blob the scope already held, so created=False (#1603 round 3, item 2).
            kept = existing if existing is not None else blob
            self._backend.put(f"{key}.json", encode_sidecar(kept))
            return kept, False
        if not self._backend.create(f"{key}.json", encode_sidecar(blob)):
            # Another upload of these bytes created the record between our check and our write.
            return self._meta(key, len(body)) or blob, False
        _logger.info("blob ingested digest=sha256:%s size=%d", sha256, len(body))
        return blob, True

    def _admit(self, sha256: str, media_type: str, body: bytes) -> str:
        """The bare media type of an upload the policy accepts, or the refusal `ingest` names."""
        bare = bare_media_type(media_type)
        if bare not in self._policy.media_types:
            raise BlobUnsupportedMediaType(f"media type {bare!r} is not accepted for blobs")
        if self._policy.verify_signature and not has_signature(bare, body):
            raise BlobContentMismatch(f"the bytes are not a {bare!r} file")
        if len(body) > self._policy.max_bytes:
            raise BlobTooLarge(
                f"blob of {len(body)} bytes exceeds the {self._policy.max_bytes}-byte cap"
            )
        if _HEX.fullmatch(sha256) is None or hashlib.sha256(body).hexdigest() != sha256:
            named = sha256 if _HEX.fullmatch(sha256) else "<malformed>"
            raise BlobDigestMismatch(named, at="ingest")
        return bare

    def _existing(self, key: str, body: bytes) -> tuple[StoredBlob | None, bool]:
        """`(record, corrupt)` of what the scope already holds under `key`.

        INVARIANT (#1603 review round 3, item 2): a record is kept only when it agrees with the
        upload just verified — its size, and with `verify_signature` the signature of its
        recorded type. Anything else is corrupt, exactly as `read` would find it.
        WHY the recorded type's SIGNATURE rather than equality with the new label: with
        `verify_signature` the two are the same test (the upload passed its own type's
        signature, and the five signatures are disjoint); without it, the store trusts labels
        and keeps first-write-wins (`test_a_repeat_upload_keeps_the_first_media_type`).
        """
        try:
            found = self._meta(key, len(body))
        except BlobCorrupted as exc:
            # WHY heal: the upload's bytes were just verified (digest, cap, type, signature), so
            # a fresh record over a corrupt one restores the blob instead of leaving it
            # unreadable until the TTL sweep.
            _logger.warning("blob sidecar corrupt, rewriting it: %s", exc.reason)
            return None, True
        if (
            found is not None
            and self._policy.verify_signature
            and not has_signature(found.media_type, body)
        ):
            _logger.warning(
                "blob sidecar corrupt, rewriting it: digest=sha256:%s recorded type %r is not "
                "the verified bytes' type",
                found.sha256,
                found.media_type,
            )
            return None, True
        return found, False

    def read(self, scope: BlobScope, sha256: str) -> tuple[StoredBlob, bytes] | None:
        """The verified blob and its bytes, or None when absent, out of scope or malformed.

        INVARIANT (#1603 review round 2, items 2-3): nothing is served unless the sidecar is the
        closed schema, the bytes fit the cap, their length is the recorded size, they hash to
        the digest and — with `verify_signature` — open with the recorded type's signature.

        Raises:
            BlobDigestMismatch: the stored bytes no longer hash to `sha256` (store corruption).
            BlobCorrupted: the sidecar or the bytes break the contract above (store corruption).
        """
        if _HEX.fullmatch(sha256) is None:
            return None
        key = f"{scope.key_prefix}/{sha256}"
        blob = self._meta(key)
        body = None if blob is None else self._backend.get_at_most(key, self._policy.max_bytes)
        if blob is None or body is None:
            return None
        if len(body) != blob.size_bytes:
            raise self._corrupt(sha256, f"holds {len(body)} bytes, recorded {blob.size_bytes}")
        if hashlib.sha256(body).hexdigest() != sha256:
            _logger.error(
                "blob store corruption: stored bytes do not hash to digest=sha256:%s size=%d",
                sha256,
                len(body),
            )
            raise BlobDigestMismatch(sha256, at="read")
        if self._policy.verify_signature and not has_signature(blob.media_type, body):
            raise self._corrupt(sha256, f"the bytes are not a {blob.media_type!r} file")
        return blob, body

    def sweep(self, ttl_seconds: float, *, now: float | None = None) -> int:
        """Reclaim blobs older than `ttl_seconds` (the artifact TTL — owner decision Q4a)."""
        return self._objects.sweep(ttl_seconds, now=now)

    def _meta(self, key: str, size_bytes: int | None = None) -> StoredBlob | None:
        """The sidecar under `key`, validated against the CLOSED schema; None when absent.

        Raises:
            BlobCorrupted: past `SIDECAR_MAX_BYTES`, or anything `parse_sidecar` refuses.
        """
        sha256 = key.rsplit("/", 1)[-1]
        raw = self._backend.get_at_most(f"{key}.json", SIDECAR_MAX_BYTES)
        if raw is None:
            return None
        try:
            return parse_sidecar(sha256, raw, self._policy, size_bytes)
        except BlobCorrupted as exc:
            # INVARIANT: logs carry the digest and the reason, never the bytes or the scope.
            _logger.error("blob store corruption: digest=sha256:%s %s", sha256, exc.reason)
            raise

    @staticmethod
    def _corrupt(sha256: str, reason: str) -> BlobCorrupted:
        # INVARIANT: logs carry the digest and the reason, never the bytes or the scope.
        _logger.error("blob store corruption: digest=sha256:%s %s", sha256, reason)
        return BlobCorrupted(sha256, reason)


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


__all__ = [
    "ATTACHMENT_MEDIA_TYPES",
    "BLOB_DIGEST_MISMATCH",
    "BLOB_REF_PREFIX",
    "BLOB_TOO_LARGE",
    "BLOB_UNSUPPORTED_MEDIA_TYPE",
    "DEFAULT_BLOB_MAX_BYTES",
    "MEDIA_TYPE_SIGNATURES",
    "SOURCE_NOT_FOUND",
    "SIDECAR_MAX_BYTES",
    "BlobContentMismatch",
    "BlobCorrupted",
    "BlobDigestMismatch",
    "BlobError",
    "BlobObjects",
    "BlobPolicy",
    "BlobScope",
    "BlobStore",
    "BlobTooLarge",
    "BlobUnsupportedMediaType",
    "BoundedBlobObjects",
    "FilesystemBlobObjects",
    "S3BlobObjects",
    "ScopedBlobReader",
    "StoredBlob",
]
