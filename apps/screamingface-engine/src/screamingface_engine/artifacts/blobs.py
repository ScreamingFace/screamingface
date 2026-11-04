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
from typing import Literal, Protocol, runtime_checkable

from screamingface_engine.artifacts.s3 import S3ArtifactStore, S3ObjectTooLarge

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
    # WHY off by default and ON in the App (`app._build_blob_store`): the App is the only
    # ingest path (uploads, and OME-1543's write-through); the Runner only reads. A store built
    # bare keeps the original label-trusting behaviour its first tests pinned.
    verify_signature: bool = False


class BlobObjects(Protocol):
    """The byte-object backend under the store: keyed put/get plus TTL reclamation."""

    def put(self, key: str, data: bytes) -> None: ...

    def get(self, key: str) -> bytes | None: ...

    def sweep(self, ttl_seconds: float, *, now: float | None = None) -> int: ...


@runtime_checkable
class BoundedBlobObjects(BlobObjects, Protocol):
    """A backend that reads with a cap and creates exclusively — both shipped backends are.

    FEATURE: #1603 review round 2 (owner decision 2026-11-04, items 2 and 5).

    WHY a second protocol rather than widening `BlobObjects`: `BlobObjects` is the public port a
    backend may implement with put/get alone; `BlobStore` adapts such a backend
    (`_UnboundedObjects`) instead of refusing it.
    """

    def get_at_most(self, key: str, max_bytes: int) -> bytes | None:
        """The object, or None when absent. Raises `BlobCorrupted` past `max_bytes`."""
        ...

    def create(self, key: str, data: bytes) -> bool:
        """Write `key` only if absent; True when THIS call created it."""
        ...


class _UnboundedObjects:
    """A put/get-only backend seen through `BoundedBlobObjects`.

    AIDEV-NOTE: the cap is enforced AFTER the backend has returned the whole object, and the
    create is check-then-put — neither is the memory bound nor the atomicity the two real
    backends give. Only a third-party (or test) backend lands here.
    """

    def __init__(self, inner: BlobObjects) -> None:
        self._inner = inner

    def put(self, key: str, data: bytes) -> None:
        self._inner.put(key, data)

    def get(self, key: str) -> bytes | None:
        return self._inner.get(key)

    def sweep(self, ttl_seconds: float, *, now: float | None = None) -> int:
        return self._inner.sweep(ttl_seconds, now=now)

    def get_at_most(self, key: str, max_bytes: int) -> bytes | None:
        found = self._inner.get(key)
        if found is not None and len(found) > max_bytes:
            raise _too_large(key, max_bytes)
        return found

    def create(self, key: str, data: bytes) -> bool:
        if self._inner.get(key) is not None:
            return False
        self._inner.put(key, data)
        return True


def _too_large(key: str, max_bytes: int) -> BlobCorrupted:
    return BlobCorrupted(key.rsplit("/", 1)[-1], f"object exceeds the {max_bytes}-byte read cap")


class FilesystemBlobObjects:
    """Blob objects as files below `<root>/blobs/` — `root` is the blob directory."""

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
        """The object, capped at the default blob size (see `get_at_most`)."""
        return self.get_at_most(key, DEFAULT_BLOB_MAX_BYTES)

    def get_at_most(self, key: str, max_bytes: int) -> bytes | None:
        # INVARIANT: never more than `max_bytes + 1` bytes leave the disk (item 2).
        try:
            with (self._root / key).open("rb") as handle:
                data = handle.read(max_bytes + 1)
        except FileNotFoundError:
            return None
        if len(data) > max_bytes:
            raise _too_large(key, max_bytes)
        return data

    def create(self, key: str, data: bytes) -> bool:
        """Create `key` exclusively; False when it already exists (item 5).

        WHY tmp + `os.link`: `link` fails with EEXIST if the name is taken and is atomic, so the
        name appears complete or not at all — never a half-written sidecar a reader could parse.
        """
        final = self._root / key
        final.parent.mkdir(parents=True, exist_ok=True)
        tmp = final.parent / f".{final.name}.{uuid.uuid4().hex}.tmp"
        tmp.write_bytes(data)
        try:
            os.link(tmp, final)
        except FileExistsError:
            return False
        finally:
            tmp.unlink(missing_ok=True)
        return True

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
    """Blob objects in the blob bucket, below the `blobs/` key prefix."""

    def __init__(self, store: S3ArtifactStore) -> None:
        self._store = store

    def put(self, key: str, data: bytes) -> None:
        self._store.put_object(key, data)

    def get(self, key: str) -> bytes | None:
        """The object, capped at the default blob size (see `get_at_most`)."""
        return self.get_at_most(key, DEFAULT_BLOB_MAX_BYTES)

    def get_at_most(self, key: str, max_bytes: int) -> bytes | None:
        # INVARIANT: a streamed read that stops past the cap — never `response.content` (item 2).
        try:
            return self._store.get_object_at_most(key, max_bytes)
        except S3ObjectTooLarge:
            raise _too_large(key, max_bytes) from None

    def create(self, key: str, data: bytes) -> bool:
        # AIDEV-NOTE: atomic on a conforming S3; Garage ignores the condition (see
        # `S3ArtifactStore.put_object_if_absent`), where `BlobStore`'s prior read is the guard.
        return self._store.put_object_if_absent(key, data)

    def sweep(self, ttl_seconds: float, *, now: float | None = None) -> int:
        """Always 0 — expiry is the bucket's lifecycle rule, exactly as for result artifacts.

        AIDEV-NOTE: the operator's lifecycle rule must cover the `blobs/` prefix too — the Helm
        README's "Expiry" section documents it with an example rule (#1603 review).
        """
        return 0


class BlobStore:
    """Ingest and read blobs within one (tenant, run) scope, verifying sha256 both ways."""

    def __init__(self, objects: BlobObjects, policy: BlobPolicy | None = None) -> None:
        self._objects = objects
        self._backend: BoundedBlobObjects = (
            objects if isinstance(objects, BoundedBlobObjects) else _UnboundedObjects(objects)
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
            self._backend.put(f"{key}.json", _sidecar(kept))
            return kept, False
        if not self._backend.create(f"{key}.json", _sidecar(blob)):
            # Another upload of these bytes created the record between our check and our write.
            return self._meta(key, len(body)) or blob, False
        _logger.info("blob ingested digest=sha256:%s size=%d", sha256, len(body))
        return blob, True

    def _admit(self, sha256: str, media_type: str, body: bytes) -> str:
        """The bare media type of an upload the policy accepts, or the refusal `ingest` names."""
        bare = _bare_media_type(media_type)
        if bare not in self._policy.media_types:
            raise BlobUnsupportedMediaType(f"media type {bare!r} is not accepted for blobs")
        if self._policy.verify_signature and not _has_signature(bare, body):
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
            and not _has_signature(found.media_type, body)
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
        if self._policy.verify_signature and not _has_signature(blob.media_type, body):
            raise self._corrupt(sha256, f"the bytes are not a {blob.media_type!r} file")
        return blob, body

    def sweep(self, ttl_seconds: float, *, now: float | None = None) -> int:
        """Reclaim blobs older than `ttl_seconds` (the artifact TTL — owner decision Q4a)."""
        return self._objects.sweep(ttl_seconds, now=now)

    def _meta(self, key: str, size_bytes: int | None = None) -> StoredBlob | None:
        """The sidecar under `key`, validated against the CLOSED schema; None when absent.

        `size_bytes`, when given, must equal the recorded size (the ingest path knows it before
        reading the data back; the read path checks it against the bytes instead).

        Raises:
            BlobCorrupted: past `SIDECAR_MAX_BYTES`, not JSON, not exactly the two keys, a size
                that is not a non-negative int within the cap, or a type outside the policy.
        """
        sha256 = key.rsplit("/", 1)[-1]
        raw = self._backend.get_at_most(f"{key}.json", SIDECAR_MAX_BYTES)
        if raw is None:
            return None
        try:
            meta = json.loads(raw)
        except ValueError:  # JSONDecodeError and UnicodeDecodeError are both ValueErrors
            raise self._corrupt(sha256, "metadata is not valid JSON") from None
        if not isinstance(meta, dict) or set(meta) != _SIDECAR_KEYS:
            raise self._corrupt(sha256, "metadata is not the closed sidecar schema")
        size, media = meta["size_bytes"], meta["media_type"]
        # WHY `type(...) is int`: `bool` is an `int` subclass, and `true` is not a size.
        if type(size) is not int or not 0 <= size <= self._policy.max_bytes:
            raise self._corrupt(sha256, "recorded size is not a size within the cap")
        if size_bytes is not None and size != size_bytes:
            raise self._corrupt(sha256, f"recorded size {size} is not {size_bytes}")
        if not isinstance(media, str) or media not in self._policy.media_types:
            raise self._corrupt(sha256, "recorded media type is not an accepted type")
        return StoredBlob(sha256=sha256, size_bytes=size, media_type=media)

    @staticmethod
    def _corrupt(sha256: str, reason: str) -> BlobCorrupted:
        # INVARIANT: logs carry the digest and the reason, never the bytes or the scope.
        _logger.error("blob store corruption: digest=sha256:%s %s", sha256, reason)
        return BlobCorrupted(sha256, reason)


def _sidecar(blob: StoredBlob) -> bytes:
    return json.dumps({"media_type": blob.media_type, "size_bytes": blob.size_bytes}).encode()


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


def _has_signature(media_type: str, body: bytes) -> bool:
    """Whether `body` opens with one of `media_type`'s signatures (absent type → False)."""
    return any(
        all(body[at : at + len(magic)] == magic for at, magic in alternative)
        for alternative in MEDIA_TYPE_SIGNATURES.get(media_type, ())
    )


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
