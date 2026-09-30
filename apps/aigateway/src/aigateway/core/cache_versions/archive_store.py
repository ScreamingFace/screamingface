"""The write-once archive adapters: bucket and filesystem (OME-1307, GW-freeze; contract C8a).

FEATURE: OME-1307 (E14) - one archive object is written once and never overwritten.

INVARIANT: an object that exists is never replaced. The S3 adapter checks with a signed HEAD first,
and the filesystem adapter links a finished temp file into place (a link never overwrites).
INVARIANT: no error message carries a credential.
WHY HEAD-then-PUT and not ``If-None-Match: *`` (OD-F5): C8a allows it, and Garage support for a
conditional PUT is not proven. Two replicas that race write identical bytes (the exporter checks the
digest first), so the loser's PUT is harmless.
"""

from __future__ import annotations

import asyncio
import os
import shutil
from collections.abc import Callable
from pathlib import Path
from typing import Literal
from uuid import uuid4

import httpx

from ..object_store import S3ObjectStore, S3ObjectStoreConfig, S3StorageError
from .ports import ArchiveStoreError


class S3VersionArchiveStore:
    def __init__(
        self,
        config: S3ObjectStoreConfig,
        *,
        client_factory: Callable[[], httpx.AsyncClient] | None = None,
    ) -> None:
        self._config = config
        self._client_factory = client_factory or (
            lambda: httpx.AsyncClient(timeout=config.timeout_s)
        )

    async def put_once(
        self, key: str, path: Path, *, sha256_hex: str
    ) -> Literal["written", "exists"]:
        store = S3ObjectStore(self._config, client_factory=self._client_factory)
        try:
            status = await store.head(key)
        except S3StorageError as exc:
            raise ArchiveStoreError(str(exc)) from None
        if status == 200:
            return "exists"
        if status != 404:
            # A 3xx lands here too: a redirect is never followed, because the signature is bound to
            # this host and path.
            raise ArchiveStoreError(f"object storage answered HEAD {key} with {status}")
        try:
            await store.put(key, path, sha256_hex=sha256_hex)
        except S3StorageError as exc:
            # The `S3StorageError` text is the store's status and error body: no credential in it.
            raise ArchiveStoreError(str(exc)) from None
        return "written"


class FilesystemVersionArchiveStore:
    def __init__(self, root: Path) -> None:
        self._root = root

    async def put_once(
        self, key: str, path: Path, *, sha256_hex: str
    ) -> Literal["written", "exists"]:
        return await asyncio.to_thread(self._put_once, key, path)

    def _put_once(self, key: str, path: Path) -> Literal["written", "exists"]:
        target = self._root / key
        if target.exists():
            return "exists"
        target.parent.mkdir(parents=True, exist_ok=True)
        temp = target.with_suffix(f"{target.suffix}.tmp-{uuid4().hex}")
        try:
            shutil.copyfile(path, temp)
            try:
                os.link(temp, target)  # a link never overwrites: the loser of a race sees the file
            except FileExistsError:
                return "exists"
            return "written"
        finally:
            temp.unlink(missing_ok=True)
