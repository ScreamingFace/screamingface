"""PB-8a and the contracts of `PublicationStore` that no route or worker test pins alone.

FEATURE: OME-1307 (E14). INVARIANTS under test: every write re-reads the state under the row lock
(an admin takedown can win any race); a takedown never clears a lease; the lease query really
locks with SKIP LOCKED on PostgreSQL.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from fastapi import FastAPI

from scoreboard.core.publish.backoff import MAX_ATTEMPTS
from scoreboard.core.publish.ports import ReleaseRef
from scoreboard.scores.models import CacheVersionPublication, ReportedResult, Score
from scoreboard.scores.publication_store import LEASE_S, PublicationStore, PublishJob
from tests.unit.publish._fakes import NOW, Seeded
from tests.unit.publish._rows import seed_rows
from tests.unit.submissions._receipts import ANA

pytestmark = pytest.mark.asyncio

_RELEASE = ReleaseRef(id=1, tag="t", html_url="https://github.test/r", upload_url="u", assets=())


def _store(app: FastAPI) -> PublicationStore:
    return app.state.publication_store


async def _leased(app: FastAPI) -> tuple[Seeded, PublishJob]:
    seeded = await seed_rows(state="private")
    store = _store(app)
    await store.request_publish(seeded.result_uuid, requested_by=ANA, now=NOW)
    job = await store.lease_next(NOW)
    assert job is not None
    return seeded, job


async def _row(seeded: Seeded) -> CacheVersionPublication:
    return await CacheVersionPublication.get(result_id=seeded.result_id)


async def test_lease_query_really_skips_locked_rows() -> None:
    """The due-job read must emit `FOR UPDATE SKIP LOCKED` on PostgreSQL (PB-8a).

    WHY rendered and not run: SQLite implements no row lock, so no behavioural test can hold the
    claim there. Rendering the query PRODUCTION runs on the dialect that has the lock is the check
    (same as `test_the_replay_row_read_really_locks_the_row`).
    """
    from tortoise import Tortoise

    await Tortoise.init(
        db_url="asyncpg://user:pass@127.0.0.1:1/unused",
        modules={"models": ["scoreboard.scores.models"]},
        _create_db=False,
    )
    try:
        sql = PublicationStore("https://scoreboard.test").lease_query(NOW).sql()
    finally:
        await Tortoise.close_connections()

    assert "FOR UPDATE SKIP LOCKED" in sql.upper(), f"the lease read lost its lock: {sql}"


async def test_release_facts_publish_local_parts_only(publish_app: FastAPI) -> None:
    seeded = await seed_rows()
    head = await Score.get(id=seeded.head_id)
    head.authors = ["Ana@X.org", "ana@x.org", "bruno@y.org"]
    head.paper_url = "https://arxiv.org/abs/1"
    await head.save()

    facts = await _store(publish_app).release_facts(seeded.result_uuid, NOW)

    # WHY: the release is public, and the read API already publishes the local part only (OME-834).
    assert facts.reporter == "ana"
    assert facts.authors == ["Ana", "bruno"]
    assert facts.scoreboard_url == f"https://scoreboard.screamingface.ai/v1/scores/{seeded.head_id}"
    assert (facts.entry_count, facts.call_count, facts.coverage_status) == (1, 1, "complete")
    assert (
        facts.archive_sha256 == (await ReportedResult.get(id=seeded.result_id)).cache_version_sha256
    )
    assert facts.published_at == NOW
    assert facts.system_name is None


@pytest.mark.parametrize("previous", ["requested", "published", "failed"])
async def test_withdraw_schedules_cleanup_and_keeps_the_lease(
    publish_app: FastAPI, previous: str
) -> None:
    seeded, job = await _leased(publish_app)
    row = await _row(seeded)
    row.state = previous
    row.attempts = 3
    await row.save()
    lease = (await _row(seeded)).lease_until
    assert lease == NOW + timedelta(seconds=LEASE_S)
    assert job.state == "requested"
    later = NOW + timedelta(minutes=5)

    state = await _store(publish_app).withdraw(
        seeded.result_uuid, actor="admin@x.org", reason="license", now=later
    )

    assert state == "withdrawn"
    row = await _row(seeded)
    assert (row.state, row.withdrawn_by, row.withdrawn_reason) == (
        "withdrawn",
        "admin@x.org",
        "license",
    )
    assert row.withdrawn_at == later
    assert row.next_attempt_at == later
    assert row.attempts == 0
    # INVARIANT: a takedown never clears the lease of a worker that is mid-publish.
    assert row.lease_until == lease


async def test_withdraw_of_a_never_published_row_schedules_no_cleanup(publish_app: FastAPI) -> None:
    seeded = await seed_rows(state="private")

    state = await _store(publish_app).withdraw(
        seeded.result_uuid, actor="admin@x.org", reason="license", now=NOW
    )

    assert state == "withdrawn"
    row = await _row(seeded)
    assert row.next_attempt_at is None
    assert await _store(publish_app).lease_next(NOW + timedelta(days=1)) is None


async def test_a_repeated_withdraw_is_a_no_op(publish_app: FastAPI) -> None:
    seeded = await seed_rows(state="published")
    store = _store(publish_app)
    await store.withdraw(seeded.result_uuid, actor="admin@x.org", reason="first", now=NOW)

    again = await store.withdraw(
        seeded.result_uuid, actor="other@x.org", reason="second", now=NOW + timedelta(hours=1)
    )

    assert again == "withdrawn"
    row = await _row(seeded)
    assert (row.withdrawn_by, row.withdrawn_reason, row.withdrawn_at) == (
        "admin@x.org",
        "first",
        NOW,
    )


async def test_a_leased_row_is_not_due_until_the_lease_ends(publish_app: FastAPI) -> None:
    _, job = await _leased(publish_app)
    store = _store(publish_app)

    assert job.state == "requested"
    assert await store.lease_next(NOW + timedelta(seconds=LEASE_S - 1)) is None
    assert await store.lease_next(NOW + timedelta(seconds=LEASE_S + 1)) is not None


async def test_finish_published_after_a_withdraw_schedules_cleanup_and_publishes_nothing(
    publish_app: FastAPI,
) -> None:
    seeded, job = await _leased(publish_app)
    store = _store(publish_app)
    await store.withdraw(seeded.result_uuid, actor="admin@x.org", reason="x", now=NOW)

    published = await store.finish_published(job, release=_RELEASE, now=NOW + timedelta(seconds=5))

    assert published is False
    row = await _row(seeded)
    assert (row.state, row.published_at, row.release_url) == ("withdrawn", None, None)
    assert row.next_attempt_at == NOW + timedelta(seconds=5)
    assert row.lease_until is None


async def test_record_failed_after_a_withdraw_only_schedules_cleanup(publish_app: FastAPI) -> None:
    seeded, job = await _leased(publish_app)
    store = _store(publish_app)
    await store.withdraw(seeded.result_uuid, actor="admin@x.org", reason="x", now=NOW)

    await store.record_failed(job, error="archive_mismatch", now=NOW)

    row = await _row(seeded)
    assert (row.state, row.last_error, row.next_attempt_at) == ("withdrawn", None, NOW)


async def test_record_retry_counts_backs_off_and_fails_after_the_cap(publish_app: FastAPI) -> None:
    seeded, job = await _leased(publish_app)
    store = _store(publish_app)

    state = await store.record_retry(job, error="HTTP 502", delay_s=60, now=NOW)

    row = await _row(seeded)
    assert state == "requested"
    assert (row.attempts, row.last_error, row.lease_until) == (1, "HTTP 502", None)
    assert row.next_attempt_at == NOW + timedelta(seconds=60)
    row.attempts = MAX_ATTEMPTS - 1
    await row.save()

    assert await store.record_retry(job, error="HTTP 502", delay_s=60, now=NOW) == "failed"
    assert (await _row(seeded)).state == "failed"


async def test_record_retry_after_a_withdraw_leaves_the_cleanup_due(publish_app: FastAPI) -> None:
    seeded, job = await _leased(publish_app)
    store = _store(publish_app)
    await store.withdraw(seeded.result_uuid, actor="admin@x.org", reason="x", now=NOW)

    state = await store.record_retry(job, error="HTTP 502", delay_s=600, now=NOW)

    assert state == "withdrawn"
    row = await _row(seeded)
    assert (row.state, row.attempts, row.next_attempt_at, row.lease_until) == (
        "withdrawn",
        0,
        NOW,
        None,
    )


async def test_a_cleanup_retry_has_no_cap_and_finish_cleanup_clears_it(
    publish_app: FastAPI,
) -> None:
    seeded = await seed_rows(state="published")
    store = _store(publish_app)
    await store.withdraw(seeded.result_uuid, actor="admin@x.org", reason="x", now=NOW)
    job = await store.lease_next(NOW)
    assert job is not None and job.state == "withdrawn"
    row = await _row(seeded)
    row.attempts = MAX_ATTEMPTS + 5
    await row.save()

    state = await store.record_retry(job, error="HTTP 502", delay_s=120, now=NOW)

    assert state == "withdrawn"
    row = await _row(seeded)
    assert (row.attempts, row.next_attempt_at) == (MAX_ATTEMPTS + 6, NOW + timedelta(seconds=120))

    await store.finish_cleanup(job)

    row = await _row(seeded)
    assert (row.next_attempt_at, row.attempts, row.lease_until) == (None, 0, None)
    assert row.state == "withdrawn"


async def test_gauges_count_by_state_and_measure_the_pending_cleanup_from_withdrawn_at(
    publish_app: FastAPI,
) -> None:
    published = await seed_rows(state="published")
    await seed_rows(state="private")
    store = _store(publish_app)
    await store.withdraw(published.result_uuid, actor="admin@x.org", reason="x", now=NOW)
    # The backoff moves next_attempt_at forward; it must not reset the one-hour measure.
    row = await _row(published)
    row.next_attempt_at = NOW + timedelta(hours=5)
    await row.save()

    by_state, pending_at_59 = await store.gauges(NOW + timedelta(minutes=59))
    _, pending_at_61 = await store.gauges(NOW + timedelta(minutes=61))

    assert by_state == {"withdrawn": 1, "private": 1}
    assert (pending_at_59, pending_at_61) == (0, 1)
