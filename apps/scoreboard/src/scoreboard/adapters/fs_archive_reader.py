"""`FilesystemArchiveReader`: the local-mode `VersionArchiveReader` (C8 "Local mode").

FEATURE: OME-1307 (E14). The local runtime writes the archive under a directory instead of a
bucket; this reads the same layout: `<root>/cache-versions/<version_id>/{entries.jsonl.gz,
manifest.json}` (erd 3.5).

INVARIANT: read-only, and never outside `root`. A version folder that resolves outside the root
(a link) is treated as missing, so the worker fails the job as an integrity failure.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from uuid import UUID

from scoreboard.core.publish.ports import (
    ARCHIVE_DIR,
    ENTRIES_NAME,
    MANIFEST_NAME,
    ArchiveMissing,
    ArchivePair,
)


class FilesystemArchiveReader:
    def __init__(self, root: Path) -> None:
        self._root = root.resolve()

    async def read(self, version_id: UUID) -> ArchivePair:
        folder = (self._root / ARCHIVE_DIR / str(version_id)).resolve()
        if not folder.is_relative_to(self._root):
            raise ArchiveMissing(f"archive of {version_id} resolves outside the archive root")
        return ArchivePair(
            entries=await self._read(folder / ENTRIES_NAME, version_id),
            manifest=await self._read(folder / MANIFEST_NAME, version_id),
        )

    async def _read(self, path: Path, version_id: UUID) -> bytes:
        # File I/O is blocking; keep it off the loop the API serves on.
        try:
            return await asyncio.to_thread(path.read_bytes)
        except FileNotFoundError as exc:
            raise ArchiveMissing(f"archive of {version_id} has no {path.name}") from exc
