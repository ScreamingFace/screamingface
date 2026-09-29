"""CV-23 and support: the archive exporter (outbox by ``status = 'frozen'``).

FEATURE: OME-1307 (E14) - a frozen version is archived to a bucket, then marked `archived`.
INVARIANT (CV-E5): while the bucket is down a version stays `frozen`, and its rows stay readable
and complete, so replay keeps working from the database (DR-3).
INVARIANT: bytes whose sha256 differs from `archive_sha256` are never uploaded.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
from collections.abc import Collection
from datetime import UTC, datetime, timedelta
from io import BytesIO
from pathlib import Path
from typing import Any, Literal
from uuid import UUID, uuid4

import pytest

from aigateway.core.cache_versions.archive import (
    ENTRIES_OBJECT,
    MANIFEST_OBJECT,
    archive_prefix,
    manifest_bytes,
    write_entries,
)
from aigateway.core.cache_versions.exporter import CacheVersionExporter
from aigateway.core.cache_versions.freeze import FreezeService
from aigateway.core.cache_versions.freeze_store import TortoiseFreezeStore
from aigateway.core.cache_versions.models import CacheVersion, CacheVersionBlob
from aigateway.core.cache_versions.ports import (
    ArchiveEntry,
    ArchiveStoreError,
    ReceiptClaims,
    StoredVersion,
)
from aigateway.core.cache_versions.stats import CaptureStats
from tests.unit.cache_versions.conftest import seed_stored_calls

_ACCOUNT = "acct-export"
_TRACE = "e5" * 16


class _Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


class _Archive:
    """A VersionArchiveStore that fails a given number of times, then works. Records every call."""

    def __init__(
        self, *, fail_first: int = 0, clock: _Clock | None = None, existing: set[str] | None = None
    ) -> None:
        self._fail_first = fail_first
        self._clock = clock
        self._existing = existing or set()
        self.calls: list[tuple[str, float]] = []
        self.objects: dict[str, bytes] = {}
        self.sha_headers: dict[str, str] = {}

    async def put_once(
        self, key: str, path: Path, *, sha256_hex: str
    ) -> Literal["written", "exists"]:
        self.calls.append((key, self._clock.now if self._clock else 0.0))
        if len(self.calls) <= self._fail_first:
            raise ArchiveStoreError("the bucket is down")
        if key in self._existing:
            return "exists"
        data = path.read_bytes()
        assert hashlib.sha256(data).hexdigest() == sha256_hex, "uploaded bytes must match the hash"
        self.objects[key] = data
        self.sha_headers[key] = sha256_hex
        return "written"


class _FakeSigner:
    kid = "k"

    def sign(self, claims: ReceiptClaims) -> str:
        return "receipt"


async def _freeze_one(count: int = 3) -> StoredVersion:
    await seed_stored_calls(_ACCOUNT, _TRACE, count)
    service = FreezeService(
        store=TortoiseFreezeStore(),
        signer=_FakeSigner(),
        stats=CaptureStats(),
        max_entries=100,
        max_archive_bytes=10**9,
    )
    result = await service.freeze(account_id=_ACCOUNT, subject="ada", trace_id=_TRACE)
    version = await TortoiseFreezeStore().find_version(_ACCOUNT, _TRACE)
    assert version is not None and version.id == result.version_id
    return version


def _exporter(
    archive: _Archive,
    stats: CaptureStats,
    *,
    clock: _Clock | None = None,
    spool_root: Path | None = None,
    base_backoff_s: float = 1.0,
    max_backoff_s: float = 300.0,
) -> CacheVersionExporter:
    return CacheVersionExporter(
        store=TortoiseFreezeStore(),
        archive=archive,
        stats=stats,
        poll_interval_s=3600.0,
        monotonic=clock or _Clock(),
        jitter=lambda: 0.0,
        spool_root=spool_root,
        base_backoff_s=base_backoff_s,
        max_backoff_s=max_backoff_s,
    )


def _status(client: Any, version_id: UUID) -> str:
    async def _get() -> str:
        return (await CacheVersion.get(id=version_id)).status

    return client.portal.call(_get)


def test_export_retries_when_bucket_down_replay_still_works(client: Any) -> None:
    clock, stats = _Clock(), CaptureStats()
    archive = _Archive(fail_first=3, clock=clock)
    exporter = _exporter(archive, stats, clock=clock)

    async def _scenario() -> tuple[list[str], list[ArchiveEntry], list[ArchiveEntry]]:
        version = await _freeze_one()
        frozen_entries = await TortoiseFreezeStore().load_archive_entries(version.id)
        statuses: list[str] = []
        # Advance in half-second steps until the version is archived.
        for _ in range(40):
            await exporter.run_once()
            statuses.append((await CacheVersion.get(id=version.id)).status)
            if statuses[-1] == "archived":
                break
            clock.now += 0.5
        await exporter.run_once()  # a pass with nothing left to do
        return (
            statuses,
            frozen_entries,
            await TortoiseFreezeStore().load_archive_entries(version.id),
        )

    statuses, before, after = client.portal.call(_scenario)

    assert statuses[0] == statuses[1] == "frozen"
    assert statuses[-1] == "archived"
    # The put attempts of the ENTRIES object: at 0 s, then after 1 s, 2 s and 4 s of backoff.
    attempts = [t for key, t in archive.calls if key.endswith(ENTRIES_OBJECT)]
    assert attempts[:4] == [0.0, 1.0, 3.0, 7.0]
    assert stats.export_failures == 3
    assert stats.export_pending == 0
    # Replay reads Postgres (DR-3): the rows stayed complete while the bucket was down.
    assert len(before) == 3
    assert before == after


def test_backoff_is_capped_at_five_minutes(client: Any) -> None:
    clock, stats = _Clock(), CaptureStats()
    archive = _Archive(fail_first=10**6, clock=clock)
    exporter = _exporter(archive, stats, clock=clock, base_backoff_s=100.0, max_backoff_s=300.0)

    async def _scenario() -> None:
        await _freeze_one()
        # One-second steps land exactly on each retry time, because every delay is whole seconds.
        while len(archive.calls) < 5:
            await exporter.run_once()
            clock.now += 1.0

    client.portal.call(_scenario)

    times = [t for _, t in archive.calls]
    assert times[0] == 0.0
    deltas = [round(b - a, 6) for a, b in zip(times, times[1:], strict=False)]
    assert deltas == [100.0, 200.0, 300.0, 300.0]


def test_export_uploads_entries_then_manifest_then_marks_archived(
    client: Any, tmp_path: Path
) -> None:
    stats, archive = CaptureStats(), _Archive()
    spool_root = tmp_path / "spool"  # tmp_path also holds the test database
    spool_root.mkdir()
    exporter = _exporter(archive, stats, spool_root=spool_root)

    async def _scenario() -> tuple[StoredVersion, int]:
        version = await _freeze_one()
        return version, await exporter.run_once()

    version, archived = client.portal.call(_scenario)

    prefix = archive_prefix(version.id)
    assert archived == 1
    assert [key for key, _ in archive.calls] == [prefix + ENTRIES_OBJECT, prefix + MANIFEST_OBJECT]
    entries_bytes = archive.objects[prefix + ENTRIES_OBJECT]
    assert hashlib.sha256(entries_bytes).hexdigest() == version.archive_sha256
    assert archive.objects[prefix + MANIFEST_OBJECT] == manifest_bytes(version)
    assert (
        archive.sha_headers[prefix + MANIFEST_OBJECT]
        == hashlib.sha256(manifest_bytes(version)).hexdigest()
    )
    assert _status(client, version.id) == "archived"
    assert list(spool_root.iterdir()) == [], "the spool directory is removed"


def test_a_pre_existing_object_is_not_an_error_and_the_version_is_archived(
    client: Any,
) -> None:
    async def _scenario() -> UUID:
        version = await _freeze_one()
        prefix = archive_prefix(version.id)
        archive = _Archive(existing={prefix + ENTRIES_OBJECT, prefix + MANIFEST_OBJECT})
        await _exporter(archive, CaptureStats()).run_once()
        assert archive.objects == {}, "an existing object is never overwritten"
        return version.id

    assert _status(client, client.portal.call(_scenario)) == "archived"


def test_a_failed_upload_leaves_no_spool(client: Any, tmp_path: Path) -> None:
    archive = _Archive(fail_first=1)
    spool_root = tmp_path / "spool"  # tmp_path also holds the test database
    spool_root.mkdir()
    exporter = _exporter(archive, CaptureStats(), spool_root=spool_root)

    async def _scenario() -> None:
        await _freeze_one()
        await exporter.run_once()

    client.portal.call(_scenario)

    assert list(spool_root.iterdir()) == [], "the spool directory is removed after a failure too"


def test_a_digest_mismatch_uploads_nothing_and_counts(
    client: Any, caplog: pytest.LogCaptureFixture
) -> None:
    stats, archive, clock = CaptureStats(), _Archive(), _Clock()
    exporter = _exporter(archive, stats, clock=clock)

    async def _scenario() -> UUID:
        version = await _freeze_one()
        # Change a stored blob after the freeze: the rebuilt archive no longer hashes to the record.
        await CacheVersionBlob.all().update(response_json='{"changed":true}')
        with caplog.at_level(logging.ERROR):
            await exporter.run_once()
            clock.now += 299.0
            await exporter.run_once()  # still inside the max backoff: skipped
            clock.now += 2.0
            await exporter.run_once()  # backoff is over: checked (and refused) again
        return version.id

    version_id = client.portal.call(_scenario)

    assert archive.calls == [], "wrong bytes are never uploaded"
    assert stats.export_digest_mismatches == 2
    assert _status(client, version_id) == "frozen"
    assert str(version_id) in caplog.text


def test_notify_wakes_the_loop_without_waiting_for_the_poll_interval(client: Any) -> None:
    archive = _Archive()
    exporter = CacheVersionExporter(
        store=TortoiseFreezeStore(),
        archive=archive,
        stats=CaptureStats(),
        poll_interval_s=3600.0,
    )

    async def _scenario() -> str:
        exporter.start()
        try:
            await asyncio.sleep(0.05)  # the first pass finds nothing
            version = await _freeze_one()
            exporter.notify()
            for _ in range(100):
                await asyncio.sleep(0.05)
                if (await CacheVersion.get(id=version.id)).status == "archived":
                    break
            return (await CacheVersion.get(id=version.id)).status
        finally:
            await exporter.stop()

    assert client.portal.call(_scenario) == "archived"


@pytest.fixture
def _filesystem_archive_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    root = tmp_path / "archive"  # tmp_path also holds the test database
    monkeypatch.setenv("AIGW_CACHE_VERSION_ARCHIVE_BACKEND", "filesystem")
    monkeypatch.setenv("AIGW_CACHE_VERSION_ARCHIVE_DIR", str(root))
    return root


def test_the_app_starts_the_exporter_and_a_freeze_wakes_it(
    _filesystem_archive_env: Path, freeze_client: Any
) -> None:
    # FEATURE: the lifespan owns the exporter task; `FreezeService.on_frozen` wakes it, so a
    # frozen version reaches the archive directory within moments, not after the poll interval.
    account_id = freeze_client.get("/v1/auth/me").json()["id"]
    freeze_client.portal.call(lambda: seed_stored_calls(account_id, _TRACE, 2))

    resp = freeze_client.post("/v1/cache-versions", json={"trace_id": _TRACE})

    assert resp.status_code == 201, resp.text
    prefix = _filesystem_archive_env / archive_prefix(UUID(resp.json()["cache_version_id"]))
    for _ in range(100):
        if (prefix / MANIFEST_OBJECT).exists():
            break
        time.sleep(0.05)
    assert (
        hashlib.sha256((prefix / ENTRIES_OBJECT).read_bytes()).hexdigest()
        == (resp.json()["archive_sha256"])
    )
    assert (
        json.loads((prefix / MANIFEST_OBJECT).read_bytes())["entries_sha256"]
        == (resp.json()["archive_sha256"])
    )


class _FlakyStore:
    """An ExportStore whose first listing raises, to prove the loop survives a bad pass."""

    def __init__(self) -> None:
        self.list_calls = 0
        self.done = asyncio.Event()

    async def list_frozen(self, limit: int, exclude: Collection[UUID] = ()) -> list[StoredVersion]:
        self.list_calls += 1
        if self.list_calls == 1:
            raise RuntimeError("the database blinked")
        self.done.set()
        return []

    async def count_frozen(self) -> int:
        return 0

    async def load_archive_entries(self, version_id: UUID) -> list[ArchiveEntry]:
        return []

    async def mark_archived(self, version_id: UUID) -> None:
        return None


@pytest.mark.asyncio
async def test_the_loop_survives_a_failed_pass_and_stops_cleanly(
    caplog: pytest.LogCaptureFixture,
) -> None:
    store = _FlakyStore()
    exporter = CacheVersionExporter(
        store=store,
        archive=_Archive(),
        stats=CaptureStats(),
        poll_interval_s=0.01,
    )

    with caplog.at_level(logging.ERROR):
        exporter.start()
        exporter.start()  # idempotent: a live task is left alone
        await asyncio.wait_for(store.done.wait(), timeout=5)
        await exporter.stop()
        await exporter.stop()  # stopping twice is harmless

    assert store.list_calls >= 2
    assert "the database blinked" in caplog.text or "export pass failed" in caplog.text


class _MemoryExportStore:
    """An ExportStore over a list, oldest first. A version id in ``bad_load`` raises on load."""

    def __init__(self, versions: list[StoredVersion], *, bad_load: set[UUID] | None = None) -> None:
        self._versions = versions
        self._bad_load = bad_load or set()
        self.archived: list[UUID] = []

    async def list_frozen(self, limit: int, exclude: Collection[UUID] = ()) -> list[StoredVersion]:
        frozen = [v for v in self._versions if v.id not in self.archived and v.id not in exclude]
        return frozen[:limit]

    async def count_frozen(self) -> int:
        return len([v for v in self._versions if v.id not in self.archived])

    async def load_archive_entries(self, version_id: UUID) -> list[ArchiveEntry]:
        if version_id in self._bad_load:
            raise ValueError("secret-row-text that must not reach a log")
        return []

    async def mark_archived(self, version_id: UUID) -> None:
        self.archived.append(version_id)


def _memory_version(index: int, *, matching: bool) -> StoredVersion:
    # The store returns no entries, so the rebuilt archive is the empty one: that hash matches.
    empty_sha = write_entries([], BytesIO(), max_bytes=10**6).sha256
    return StoredVersion(
        id=uuid4(),
        owner_account_id=_ACCOUNT,
        trace_id=f"{index:032x}",
        status="frozen",
        entry_count=0,
        call_count=0,
        missing_count=0,
        coverage_status="complete",
        archive_sha256=empty_sha if matching else "0" * 64,
        archive_key="",
        created_at=datetime(2026, 9, 29, tzinfo=UTC) + timedelta(seconds=index),
    )


@pytest.mark.asyncio
async def test_versions_stuck_in_backoff_do_not_block_a_newer_version() -> None:
    # INVARIANT (CV-H6): every frozen version is archived eventually. More stuck versions than one
    # batch must not fill the batch pass after pass, so a newer good version still gets its turn.
    stuck = [_memory_version(i, matching=False) for i in range(11)]
    good = _memory_version(11, matching=True)
    store = _MemoryExportStore([*stuck, good])
    stats, clock = CaptureStats(), _Clock()
    exporter = CacheVersionExporter(
        store=store,
        archive=_Archive(),
        stats=stats,
        poll_interval_s=3600.0,
        batch_size=10,
        monotonic=clock,
        jitter=lambda: 0.0,
    )

    for _ in range(4):
        await exporter.run_once()
        clock.now += 1.0  # far inside the 300 s backoff of the stuck versions

    assert store.archived == [good.id]
    assert stats.export_digest_mismatches == 11


@pytest.mark.asyncio
async def test_a_version_that_raises_on_load_does_not_stop_the_pass(
    caplog: pytest.LogCaptureFixture,
) -> None:
    # A row that fails with any error (bad JSON, a database error) is counted and backed off for
    # that version alone, and the pass goes on to the next version.
    bad, good = _memory_version(0, matching=True), _memory_version(1, matching=True)
    store = _MemoryExportStore([bad, good], bad_load={bad.id})
    stats, clock = CaptureStats(), _Clock()
    exporter = CacheVersionExporter(
        store=store,
        archive=_Archive(),
        stats=stats,
        poll_interval_s=3600.0,
        monotonic=clock,
        jitter=lambda: 0.0,
    )

    with caplog.at_level(logging.WARNING):
        archived = await exporter.run_once()
        second = await exporter.run_once()  # the bad version is in backoff: not tried again

    assert archived == 1
    assert store.archived == [good.id]
    assert stats.export_failures == 1
    assert second == 0
    assert "ValueError" in caplog.text
    assert "secret-row-text" not in caplog.text, "the error text is never logged"


@pytest.mark.asyncio
async def test_a_failing_spool_directory_is_counted_not_raised(tmp_path: Path) -> None:
    # `mkdtemp` sits inside the guarded block: a missing spool root is an export failure.
    version = _memory_version(0, matching=True)
    store, stats = _MemoryExportStore([version]), CaptureStats()
    exporter = CacheVersionExporter(
        store=store,
        archive=_Archive(),
        stats=stats,
        poll_interval_s=3600.0,
        jitter=lambda: 0.0,
        spool_root=tmp_path / "does-not-exist",
    )

    assert await exporter.run_once() == 0
    assert stats.export_failures == 1
    assert store.archived == []


def test_the_database_listing_leaves_out_excluded_ids(client: Any) -> None:
    async def _scenario() -> tuple[list[UUID], list[UUID], list[UUID]]:
        version = await _freeze_one()
        store = TortoiseFreezeStore()
        return (
            [v.id for v in await store.list_frozen(10)],
            [v.id for v in await store.list_frozen(10, [version.id])],
            [v.id for v in await store.list_frozen(10, [uuid4()])],
        )

    plain, excluded, unrelated = client.portal.call(_scenario)

    assert len(plain) == 1
    assert excluded == []
    assert unrelated == plain
