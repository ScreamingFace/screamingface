"""The byte-object backends under the run blob store: filesystem and S3, plus the adapter
that lets a put/get-only backend stand in for a bounded one.

FEATURE: run blob store (OME-1540), epic OME-1529. Split out of `artifacts.blobs` (#1603 review
round 3, module size); `artifacts.blobs` re-exports the public names.

INVARIANT (#1603 review round 2, item 2): both shipped backends read with a cap — never more than
`max_bytes + 1` bytes (plus, on S3, one network chunk) before refusing as `BlobCorrupted`.
"""

from __future__ import annotations

import os
import time
import uuid
from pathlib import Path
from typing import Protocol, runtime_checkable

from screamingface_engine.artifacts.blob_schema import (
    BLOB_KEY_ROOT,
    DEFAULT_BLOB_MAX_BYTES,
    BlobCorrupted,
)
from screamingface_engine.artifacts.s3 import S3ArtifactStore, S3ObjectTooLarge


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
    (`UnboundedObjects`) instead of refusing it.
    """

    def get_at_most(self, key: str, max_bytes: int) -> bytes | None:
        """The object, or None when absent. Raises `BlobCorrupted` past `max_bytes`."""
        ...

    def create(self, key: str, data: bytes) -> bool:
        """Write `key` only if absent; True when THIS call created it."""
        ...


class UnboundedObjects:
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
        tree = self._root / BLOB_KEY_ROOT
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
