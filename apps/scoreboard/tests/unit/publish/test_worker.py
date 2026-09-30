"""PB-3, PB-4, PB-4a, PB-5, PB-7, PB-9, PB-11, PB-14 — the publish worker (`run_once`).

FEATURE: OME-1307 (E14). INVARIANTS under test: no GitHub call happens before the archive digest
matches (PB-3); a retry finds the release by its tag and never duplicates it (PB-4); an existing
asset with other bytes stops the job (PB-5).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

import pytest
from fastapi import FastAPI
from httpx import AsyncClient

from scoreboard.core.publish.ports import ArchivePair
from scoreboard.core.publish.release_body import render_release_body
from scoreboard.publish.worker import PublishWorker
from scoreboard.scores.models import CacheVersionPublication
from tests.unit.publish._fakes import NOW, FakeArchiveReader, FakeReleasePublisher, Seeded
from tests.unit.submissions._receipts import ANA, as_user

pytestmark = pytest.mark.asyncio

Seed = Callable[..., Awaitable[Seeded]]
Build = Callable[..., PublishWorker]


async def _requested(client: AsyncClient, seed_result: Seed) -> Seeded:
    seeded = await seed_result(client, board="pub")
    response = await client.post(f"/v1/results/{seeded.result_id}/publish", headers=as_user(ANA))
    assert response.status_code == 202
    return seeded


async def _row(seeded: Seeded) -> CacheVersionPublication:
    return await CacheVersionPublication.get(result_id=seeded.result_id)


def _counter(app: FastAPI, name: str, labels: dict[str, str] | None = None) -> float:
    value = app.state.metrics.registry.get_sample_value(name, labels or {})
    return 0.0 if value is None else value


def _kinds(fake: FakeReleasePublisher) -> list[str]:
    return [call[0] for call in fake.calls]


@pytest.mark.parametrize(
    ("reader", "error"),
    [
        pytest.param(
            lambda seeded: FakeArchiveReader(
                {seeded.version_id: ArchivePair(entries=b"other bytes", manifest=b"{}")}
            ),
            "archive_mismatch",
            id="digest-mismatch",
        ),
        pytest.param(lambda seeded: FakeArchiveReader({}), "archive_missing", id="missing"),
    ],
)
async def test_archive_digest_mismatch_fails_without_upload_and_alerts(
    publish_client: AsyncClient,
    publish_app: FastAPI,
    seed_result: Seed,
    build_worker: Build,
    fake_publisher: FakeReleasePublisher,
    reader: Callable[[Seeded], FakeArchiveReader],
    error: str,
) -> None:
    seeded = await _requested(publish_client, seed_result)

    handled = await build_worker(seeded, reader(seeded)).run_once()

    assert handled is True
    row = await _row(seeded)
    assert row.state == "failed"
    assert row.last_error == error
    # INVARIANT (PB-3): not one GitHub call before the digest check passes.
    assert fake_publisher.calls == []
    assert _counter(publish_app, "scoreboard_publish_integrity_failures_total") == 1


async def test_retry_after_crash_finds_release_by_tag_no_duplicate(
    publish_client: AsyncClient,
    seed_result: Seed,
    build_worker: Build,
    fake_publisher: FakeReleasePublisher,
) -> None:
    seeded = await _requested(publish_client, seed_result)
    fake_publisher.preload(f"cv-{seeded.version_id}", seeded.pair)

    await build_worker(seeded).run_once()

    assert (await _row(seeded)).state == "published"
    kinds = _kinds(fake_publisher)
    assert kinds.count("get_release_by_tag") == 1
    assert kinds.count("download_asset") == 2
    assert "create_release" not in kinds
    assert "upload_asset" not in kinds


async def test_resume_uploads_only_the_missing_manifest(
    publish_client: AsyncClient,
    seed_result: Seed,
    build_worker: Build,
    fake_publisher: FakeReleasePublisher,
) -> None:
    seeded = await _requested(publish_client, seed_result)
    fake_publisher.preload(f"cv-{seeded.version_id}", seeded.pair, with_manifest=False)

    await build_worker(seeded).run_once()

    assert (await _row(seeded)).state == "published"
    assert [c for c in fake_publisher.calls if c[0] == "upload_asset"] == [
        ("upload_asset", "manifest.json")
    ]
    assert "create_release" not in _kinds(fake_publisher)


async def test_release_by_tag_with_other_digest_fails_release_conflict(
    publish_client: AsyncClient,
    publish_app: FastAPI,
    seed_result: Seed,
    build_worker: Build,
    fake_publisher: FakeReleasePublisher,
) -> None:
    seeded = await _requested(publish_client, seed_result)
    other = ArchivePair(entries=seeded.pair.entries, manifest=b'{"tampered":true}')
    fake_publisher.preload(f"cv-{seeded.version_id}", other)

    await build_worker(seeded).run_once()

    row = await _row(seeded)
    assert (row.state, row.last_error) == ("failed", "release_conflict")
    assert "upload_asset" not in _kinds(fake_publisher)
    assert _counter(publish_app, "scoreboard_publish_integrity_failures_total") == 1


async def test_worker_publishes_assets_and_sets_published(
    publish_client: AsyncClient,
    publish_app: FastAPI,
    seed_result: Seed,
    build_worker: Build,
    fake_publisher: FakeReleasePublisher,
) -> None:
    seeded = await _requested(publish_client, seed_result)
    tag = f"cv-{seeded.version_id}"

    handled = await build_worker(seeded).run_once()

    assert handled is True
    row = await _row(seeded)
    assert row.state == "published"
    assert row.release_url == fake_publisher.releases[tag].html_url
    assert row.published_at == NOW
    assert row.lease_until is None
    assert row.last_error is None
    stored = {a.name: fake_publisher.assets[a.id] for a in fake_publisher.releases[tag].assets}
    assert stored == {
        "entries.jsonl.gz": seeded.pair.entries,
        "manifest.json": seeded.pair.manifest,
    }
    # The manifest goes last, so it marks a complete release.
    assert [c[1] for c in fake_publisher.calls if c[0] == "upload_asset"] == [
        "entries.jsonl.gz",
        "manifest.json",
    ]
    facts = await publish_app.state.publication_store.release_facts(seeded.result_id, NOW)
    assert fake_publisher.bodies[tag] == render_release_body(facts)
    assert _counter(publish_app, "scoreboard_publish_attempts_total", {"result": "ok"}) == 1
    # Nothing is due now.
    assert await build_worker(seeded).run_once() is False


async def test_withdraw_during_publish_deletes_new_release_no_published(
    publish_client: AsyncClient,
    publish_app: FastAPI,
    seed_result: Seed,
    build_worker: Build,
    fake_publisher: FakeReleasePublisher,
) -> None:
    seeded = await _requested(publish_client, seed_result)

    async def admin_wins_the_race() -> None:
        await publish_app.state.publication_store.withdraw(
            seeded.result_uuid, actor="admin@x.org", reason="license", now=NOW
        )

    fake_publisher.before_upload["manifest.json"] = admin_wins_the_race

    await build_worker(seeded).run_once()

    row = await _row(seeded)
    assert row.state == "withdrawn"
    assert row.published_at is None
    assert row.release_url is None
    # PB-D3: what this run made is gone, and the cleanup is finished.
    assert fake_publisher.releases == {}
    assert fake_publisher.tags == set()
    assert row.next_attempt_at is None
    assert await build_worker(seeded).run_once() is False
