"""PB-3, PB-4, PB-4a, PB-5, PB-7, PB-9, PB-11, PB-14 — the publish worker (`run_once`).

FEATURE: OME-1307 (E14). INVARIANTS under test: no GitHub call happens before the archive digest
matches (PB-3); a retry finds the release by its tag and never duplicates it (PB-4); an existing
asset with other bytes stops the job (PB-5).
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from datetime import timedelta

import pytest
from fastapi import FastAPI
from httpx import AsyncClient

from scoreboard.core.publish.ports import ArchivePair, PublisherError
from scoreboard.core.publish.release_body import render_release_body
from scoreboard.publish.worker import PublishWorker
from scoreboard.scores.models import Benchmark, CacheVersionPublication
from tests.unit.publish._fakes import NOW, Clock, FakeArchiveReader, FakeReleasePublisher, Seeded
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


PENDING = "scoreboard_withdraw_cleanup_pending"


def _gauge(app: FastAPI, name: str, labels: dict[str, str] | None = None) -> float:
    return _counter(app, name, labels)


async def _pending_after(
    worker: PublishWorker, app: FastAPI, clock: Clock, seconds: float
) -> float:
    """Move the clock, let the worker run once, and read the pending-cleanup gauge."""
    clock.advance(seconds)
    await worker.run_once()
    return _gauge(app, PENDING)


async def test_withdraw_github_delete_failure_marks_cleanup_pending_and_retries(
    publish_client: AsyncClient,
    publish_app: FastAPI,
    seed_result: Seed,
    build_worker: Build,
    fake_publisher: FakeReleasePublisher,
    clock: Clock,
) -> None:
    seeded = await _requested(publish_client, seed_result)
    worker = build_worker(seeded)
    await worker.run_once()
    await publish_app.state.publication_store.withdraw(
        seeded.result_uuid, actor="admin@x.org", reason="license", now=clock()
    )
    fake_publisher.fail_methods["delete_release"] = PublisherError("HTTP 502", retryable=True)

    await worker.run_once()

    row = await _row(seeded)
    assert row.state == "withdrawn"
    assert row.attempts == 1
    assert row.next_attempt_at == NOW + timedelta(seconds=60)
    assert row.last_error == "HTTP 502"
    # The delete keeps failing; the pending measure counts from `withdrawn_at`, not from the retry.
    assert await _pending_after(worker, publish_app, clock, 59 * 60) == 0
    assert await _pending_after(worker, publish_app, clock, 2 * 60) == 1
    assert (await _row(seeded)).state == "withdrawn"

    del fake_publisher.fail_methods["delete_release"]
    clock.advance(3600)
    await worker.run_once()

    row = await _row(seeded)
    assert row.next_attempt_at is None
    assert fake_publisher.releases == {}
    assert _gauge(publish_app, PENDING) == 0
    assert _gauge(publish_app, "scoreboard_publish_jobs", {"state": "withdrawn"}) == 1


async def test_github_5xx_429_backoff_then_failed_after_8(
    publish_client: AsyncClient,
    seed_result: Seed,
    build_worker: Build,
    fake_publisher: FakeReleasePublisher,
    clock: Clock,
) -> None:
    seeded = await _requested(publish_client, seed_result)
    worker = build_worker(seeded)
    errors = [
        PublisherError("HTTP 429: rate limited " + "x" * 900, retryable=True, retry_after_s=900),
        PublisherError("HTTP 502: bad gateway", retryable=True),
        PublisherError("HTTP 403: secondary rate limit", retryable=True, retry_after_s=120),
    ]
    fake_publisher.fail_next = [errors[i % 3] for i in range(8)]

    for attempt in range(1, 8):
        await worker.run_once()
        row = await _row(seeded)
        assert (row.state, row.attempts) == ("requested", attempt)
        raw = min(3600.0, 60.0 * 2 ** (attempt - 1))
        delay = max(raw, errors[(attempt - 1) % 3].retry_after_s or 0)
        # rng is 0.0 in the tests, so the delay is the plain capped backoff or Retry-After,
        # whichever is larger; the row is not due before it.
        assert row.next_attempt_at == clock() + timedelta(seconds=delay)
        assert await worker.run_once() is False
        clock.advance(4000)
    await worker.run_once()

    row = await _row(seeded)
    assert (row.state, row.attempts) == ("failed", 8)
    assert row.last_error is not None
    assert len(row.last_error) <= 512
    assert "ghs_" not in row.last_error
    assert await worker.run_once() is False


async def test_a_final_github_error_fails_the_job_and_counts_an_error(
    publish_client: AsyncClient,
    publish_app: FastAPI,
    seed_result: Seed,
    build_worker: Build,
    fake_publisher: FakeReleasePublisher,
) -> None:
    seeded = await _requested(publish_client, seed_result)
    fake_publisher.fail_next = [PublisherError("HTTP 422: tag already exists", retryable=False)]

    await build_worker(seeded).run_once()

    row = await _row(seeded)
    assert (row.state, row.last_error, row.attempts) == (
        "failed",
        "HTTP 422: tag already exists",
        0,
    )
    assert _counter(publish_app, "scoreboard_publish_attempts_total", {"result": "error"}) == 1
    # A GitHub error is not an integrity failure: the alert counter stays at zero.
    assert _counter(publish_app, "scoreboard_publish_integrity_failures_total") == 0


async def test_a_delete_that_fails_after_a_lost_race_stays_pending_and_retries(
    publish_client: AsyncClient,
    publish_app: FastAPI,
    seed_result: Seed,
    build_worker: Build,
    fake_publisher: FakeReleasePublisher,
    clock: Clock,
) -> None:
    seeded = await _requested(publish_client, seed_result)
    worker = build_worker(seeded)

    async def admin_wins_the_race() -> None:
        await publish_app.state.publication_store.withdraw(
            seeded.result_uuid, actor="admin@x.org", reason="x", now=NOW
        )

    fake_publisher.before_upload["manifest.json"] = admin_wins_the_race
    fake_publisher.fail_methods["delete_release"] = PublisherError("HTTP 502", retryable=True)

    await worker.run_once()

    row = await _row(seeded)
    assert (row.state, row.published_at, row.lease_until) == ("withdrawn", None, None)
    assert row.next_attempt_at == NOW
    assert fake_publisher.releases
    del fake_publisher.fail_methods["delete_release"]
    await worker.run_once()
    assert fake_publisher.releases == {}
    assert (await _row(seeded)).next_attempt_at is None


async def test_an_unexpected_error_is_logged_and_the_worker_reports_no_job(
    publish_app: FastAPI,
    build_worker: Build,
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def broken(now: object) -> None:
        raise RuntimeError("database is gone")

    monkeypatch.setattr(publish_app.state.publication_store, "lease_next", broken)
    seeded = Seeded("h", "r", uuid.uuid4(), ArchivePair(b"", b""))

    handled = await build_worker(seeded).run_once()

    # INVARIANT: `run_once` never raises. It reports False, so the loop sleeps the poll interval
    # instead of hammering a database that is down.
    assert handled is False
    assert "publish worker job failed" in caplog.text


async def _withdrawn_after_publish(
    client: AsyncClient,
    app: FastAPI,
    seed_result: Seed,
    build_worker: Build,
    clock: Clock,
) -> tuple[Seeded, PublishWorker]:
    seeded = await _requested(client, seed_result)
    worker = build_worker(seeded)
    await worker.run_once()
    await app.state.publication_store.withdraw(
        seeded.result_uuid, actor="admin@x.org", reason="license", now=clock()
    )
    return seeded, worker


@pytest.mark.parametrize("mint_fails", [False, True], ids=["delete-refused", "token-mint-refused"])
async def test_a_final_error_in_a_cleanup_backs_off_and_records_the_error(
    publish_client: AsyncClient,
    publish_app: FastAPI,
    seed_result: Seed,
    build_worker: Build,
    fake_publisher: FakeReleasePublisher,
    clock: Clock,
    mint_fails: bool,
) -> None:
    """A 401 or 403 that no retry fixes must not turn the cleanup into a loop with no sleep.

    INVARIANT: after any `PublisherError` a cleanup job waits (`next_attempt_at > now`), counts the
    attempt and keeps `last_error`, so `run_once` returns False until the delay is over and an
    operator can see why the cleanup is stuck.
    """
    seeded, worker = await _withdrawn_after_publish(
        publish_client, publish_app, seed_result, build_worker, clock
    )
    assert f"cv-{seeded.version_id}" in fake_publisher.releases
    refusal = PublisherError("HTTP 403: Resource not accessible by integration", retryable=False)
    if mint_fails:

        async def no_token() -> FakeReleasePublisher:
            raise refusal

        worker = PublishWorker(
            store=publish_app.state.publication_store,
            publisher_factory=no_token,
            archive_reader=FakeArchiveReader({}),
            facts_loader=publish_app.state.publication_store.release_facts,
            metrics=publish_app.state.metrics,
            clock=clock,
            rng=lambda: 0.0,
        )
    else:
        fake_publisher.fail_methods["delete_release"] = refusal
    fake_publisher.calls.clear()

    assert await worker.run_once() is True

    row = await _row(seeded)
    assert row.state == "withdrawn"
    assert row.attempts == 1
    assert row.next_attempt_at == clock() + timedelta(seconds=60)
    assert row.last_error == "HTTP 403: Resource not accessible by integration"
    assert row.lease_until is None
    calls_after_first = len(fake_publisher.calls)
    # The clock is held still: nothing is due, so the loop of `main` sleeps.
    assert await worker.run_once() is False
    assert len(fake_publisher.calls) == calls_after_first


async def _turn_board(seeded: Seeded, **fields: object) -> None:
    del seeded
    await Benchmark.filter(id="pub").update(**fields)


@pytest.mark.parametrize(
    ("fields", "error"),
    [
        pytest.param({"visibility": "private"}, "private_board", id="turned-private"),
        pytest.param({"redistributable": False}, "not_redistributable", id="not-redistributable"),
    ],
)
async def test_a_board_that_stops_being_publishable_after_the_request_is_not_published(
    publish_client: AsyncClient,
    seed_result: Seed,
    build_worker: Build,
    fake_publisher: FakeReleasePublisher,
    fields: dict[str, object],
    error: str,
) -> None:
    """PRD Q6: private-board and gated-benchmark versions never go to the public repo.

    INVARIANT: the worker re-reads the board when the job runs, because a request can wait for
    hours (backoff and lease) after the route checked it. The check comes before the archive read
    (the reader here is empty: a read first would fail as `archive_missing`) and before any GitHub
    call.
    """
    seeded = await _requested(publish_client, seed_result)
    await _turn_board(seeded, **fields)

    handled = await build_worker(seeded, FakeArchiveReader({})).run_once()

    assert handled is True
    row = await _row(seeded)
    assert (row.state, row.last_error, row.lease_until) == ("failed", error, None)
    assert fake_publisher.calls == []
    assert fake_publisher.releases == {}


async def test_the_owner_can_publish_again_when_the_board_is_publishable_again(
    publish_client: AsyncClient,
    seed_result: Seed,
    build_worker: Build,
    fake_publisher: FakeReleasePublisher,
) -> None:
    """A refusal of the worker is not an integrity failure: PB-E5 lets the owner retry it."""
    seeded = await _requested(publish_client, seed_result)
    await _turn_board(seeded, visibility="private")
    await build_worker(seeded).run_once()
    await _turn_board(seeded, visibility="public")

    again = await publish_client.post(
        f"/v1/results/{seeded.result_id}/publish", headers=as_user(ANA)
    )
    await build_worker(seeded).run_once()

    assert again.status_code == 202
    assert (await _row(seeded)).state == "published"
    assert f"cv-{seeded.version_id}" in fake_publisher.releases
