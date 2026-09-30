"""Ports of publish and takedown: the GitHub release API and the bucket archive (C7, C8b).

FEATURE: OME-1307 (E14). The core defines these; only `scoreboard.adapters` implements them
(hexagonal, C11). INVARIANT: standard library only.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID


@dataclass(frozen=True, slots=True)
class AssetRef:
    id: int
    name: str


@dataclass(frozen=True, slots=True)
class ReleaseRef:
    id: int
    tag: str
    html_url: str
    upload_url: str  # the template with "{?name,label}" already removed
    assets: tuple[AssetRef, ...]


class PublisherError(Exception):
    """A GitHub or bucket failure the worker can act on.

    INVARIANT: `message` is sanitized: the status code and GitHub's "message" field only, cut to
    200 chars. Never a header, a token or a URL with a query.
    """

    def __init__(
        self, message: str, *, retryable: bool, retry_after_s: float | None = None
    ) -> None:
        super().__init__(message)
        self.message = message
        self.retryable = retryable
        self.retry_after_s = retry_after_s


class ReleasePublisher(Protocol):
    async def get_release_by_tag(self, tag: str) -> ReleaseRef | None: ...

    async def create_release(self, tag: str, name: str, body: str) -> ReleaseRef: ...

    async def upload_asset(
        self, release: ReleaseRef, name: str, data: bytes, content_type: str
    ) -> AssetRef: ...

    async def download_asset(self, asset: AssetRef) -> bytes: ...

    async def delete_release(self, release_id: int) -> None:
        """404 counts as done."""
        ...

    async def delete_tag(self, tag: str) -> None:
        """404 and 422 count as done."""
        ...


# WHY a factory and not one publisher: the installation token lives one hour, and PB-D7 mints a
# token per job.
ReleasePublisherFactory = Callable[[], Awaitable[ReleasePublisher]]


# The archive layout, shared by the readers and the worker: `cache-versions/<version_id>/<name>`.
ARCHIVE_DIR = "cache-versions"
ENTRIES_NAME = "entries.jsonl.gz"
MANIFEST_NAME = "manifest.json"


@dataclass(frozen=True, slots=True)
class ArchivePair:
    entries: bytes  # ENTRIES_NAME
    manifest: bytes  # MANIFEST_NAME


class ArchiveMissing(Exception):
    """The bucket has no archive for this cache version."""


class VersionArchiveReader(Protocol):
    async def read(self, version_id: UUID) -> ArchivePair:
        """Raises `ArchiveMissing`."""
        ...
