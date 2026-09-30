"""In-memory fakes and plain helpers of the SB-publish tests (E14, OME-1307).

FEATURE: OME-1307 (E14). No real network: GitHub is `FakeReleasePublisher`, the bucket is
`FakeArchiveReader`. Plain classes and functions (not fixtures) so any test module can import them.
"""

from __future__ import annotations

import gzip
import hashlib
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from scoreboard.core.publish.ports import (
    ArchiveMissing,
    ArchivePair,
    AssetRef,
    PublisherError,
    ReleaseRef,
)

NOW = datetime(2026, 9, 29, 12, 0, tzinfo=UTC)


class Clock:
    """A settable clock: the worker, the store calls and the routes all read the same one."""

    def __init__(self, now: datetime = NOW) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += timedelta(seconds=seconds)


def canonical_pair() -> ArchivePair:
    """The archive bytes the way GW-freeze writes them (D7 X-16: gzip, mtime 0, level 9)."""
    entries = gzip.compress(b'{"key_hash":"k"}\n', compresslevel=9, mtime=0)
    return ArchivePair(entries=entries, manifest=b'{"schema":"screamingface.cache-version.v1"}')


def pair_sha(pair: ArchivePair) -> str:
    """The receipt `sha`: the digest of the gzip bytes (D7 X-16)."""
    return hashlib.sha256(pair.entries).hexdigest()


class FakeReleasePublisher:
    """The `ReleasePublisher` port in memory, with a call log and programmable failures."""

    def __init__(self) -> None:
        self.releases: dict[str, ReleaseRef] = {}
        self.tags: set[str] = set()
        self.assets: dict[int, bytes] = {}
        self.bodies: dict[str, str] = {}
        self.calls: list[tuple[str, ...]] = []
        # One error, raised by the next call of any method.
        self.fail_next: list[PublisherError] = []
        # An error raised by EVERY call of a method until the entry is removed.
        self.fail_methods: dict[str, PublisherError] = {}
        # Awaited just before an asset of that name is stored (a race in a test).
        self.before_upload: dict[str, Callable[[], Awaitable[None]]] = {}
        self._next_id = 100

    def _enter(self, method: str, *detail: str) -> None:
        self.calls.append((method, *detail))
        if self.fail_next:
            raise self.fail_next.pop(0)
        if method in self.fail_methods:
            raise self.fail_methods[method]

    def _new_id(self) -> int:
        self._next_id += 1
        return self._next_id

    def preload(self, tag: str, pair: ArchivePair, *, with_manifest: bool = True) -> ReleaseRef:
        """A release that already exists, as after a crash (no call is logged)."""
        release = ReleaseRef(
            id=self._new_id(),
            tag=tag,
            html_url=f"https://github.test/releases/{tag}",
            upload_url=f"https://uploads.github.test/{tag}/assets",
            assets=(),
        )
        self.releases[tag] = release
        self.tags.add(tag)
        self._store(release, "entries.jsonl.gz", pair.entries)
        if with_manifest:
            self._store(release, "manifest.json", pair.manifest)
        return self.releases[tag]

    def _store(self, release: ReleaseRef, name: str, data: bytes) -> AssetRef:
        asset = AssetRef(id=self._new_id(), name=name)
        self.assets[asset.id] = data
        current = self.releases[release.tag]
        self.releases[release.tag] = ReleaseRef(
            id=current.id,
            tag=current.tag,
            html_url=current.html_url,
            upload_url=current.upload_url,
            assets=(*current.assets, asset),
        )
        return asset

    async def get_release_by_tag(self, tag: str) -> ReleaseRef | None:
        self._enter("get_release_by_tag", tag)
        return self.releases.get(tag)

    async def create_release(self, tag: str, name: str, body: str) -> ReleaseRef:
        self._enter("create_release", tag)
        release = ReleaseRef(
            id=self._new_id(),
            tag=tag,
            html_url=f"https://github.test/releases/{tag}",
            upload_url=f"https://uploads.github.test/{tag}/assets",
            assets=(),
        )
        self.releases[tag] = release
        self.tags.add(tag)
        self.bodies[tag] = body
        return release

    async def upload_asset(
        self, release: ReleaseRef, name: str, data: bytes, content_type: str
    ) -> AssetRef:
        self._enter("upload_asset", name)
        if name in self.before_upload:
            await self.before_upload[name]()
        return self._store(release, name, data)

    async def download_asset(self, asset: AssetRef) -> bytes:
        self._enter("download_asset", asset.name)
        return self.assets[asset.id]

    async def delete_release(self, release_id: int) -> None:
        self._enter("delete_release", str(release_id))
        for tag, release in list(self.releases.items()):
            if release.id == release_id:
                for asset in release.assets:
                    self.assets.pop(asset.id, None)
                del self.releases[tag]

    async def delete_tag(self, tag: str) -> None:
        self._enter("delete_tag", tag)
        self.tags.discard(tag)

    def factory(self) -> Callable[[], Awaitable[FakeReleasePublisher]]:
        async def _mint() -> FakeReleasePublisher:
            return self

        return _mint


class FakeArchiveReader:
    def __init__(self, pairs: dict[UUID, ArchivePair]) -> None:
        self.pairs = pairs
        self.reads: list[UUID] = []

    async def read(self, version_id: UUID) -> ArchivePair:
        self.reads.append(version_id)
        if version_id not in self.pairs:
            raise ArchiveMissing(str(version_id))
        return self.pairs[version_id]


@dataclass(frozen=True)
class Seeded:
    head_id: str
    result_id: str
    version_id: UUID
    pair: ArchivePair

    @property
    def result_uuid(self) -> UUID:
        return UUID(self.result_id)
