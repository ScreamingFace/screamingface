"""RP-6, RP-7, RP-8, RP-8a and RP-10: how a pin becomes one result.

FEATURE: OME-1307 (E14) replay grants. INVARIANT (RP-D4): the pin resolves ONCE, in the scoreboard;
the date rules are the merged parser's (`parse_pin`), so no second date rule is tested here.
STORY: as Bruno I pin `kevins-best@2026-09-01` and get the run Ana had made by then.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient

from scoreboard.scores.models import CacheVersionPublication, ReportedResult
from tests.unit.replay._helpers import granted_result_id, request_grant
from tests.unit.replay.conftest import SeedResult
from tests.unit.submissions._receipts import ANA, BRUNO, URL4_B

pytestmark = pytest.mark.asyncio


def _at(text: str) -> datetime:
    return datetime.fromisoformat(text).astimezone(UTC)


async def test_pin_by_date_newest_at_or_before_T_across_revisions(
    grant_cf_client: AsyncClient, seed_result: SeedResult
) -> None:
    r1 = await seed_result(reporter=ANA, submitted_at=_at("2026-08-10T09:00:00+00:00"))
    r2 = await seed_result(
        reporter=ANA,
        url4=URL4_B,
        revision_of="kevins-best",
        submitted_at=_at("2026-09-05T09:00:00+00:00"),
    )

    before = await request_grant(grant_cf_client, "kevins-best@2026-09-01", user=BRUNO)
    after = await request_grant(grant_cf_client, "kevins-best@2026-09-06", user=BRUNO)

    assert granted_result_id(before) == r1.result_id
    assert granted_result_id(after) == r2.result_id


@pytest.mark.parametrize(
    ("pin_time", "expected"),
    [
        ("2026-09-05", "at"),  # date-only: the end of that day, UTC
        ("2026-09-05T10:00:00+02:00", "at"),  # 08:00Z, and a result at exactly 08:00:00Z is in
        ("2099-01-01", "newest"),
        ("2026-09-04", "none"),
    ],
)
async def test_pin_by_date_boundaries(
    grant_cf_client: AsyncClient, seed_result: SeedResult, pin_time: str, expected: str
) -> None:
    exact = "2026-09-05T08:00:00+00:00" if "+02:00" in pin_time else "2026-09-05T23:59:59+00:00"
    at = await seed_result(reporter=ANA, submitted_at=_at(exact))
    newest = await seed_result(reporter=BRUNO, submitted_at=_at("2026-09-07T00:00:00+00:00"))

    response = await request_grant(grant_cf_client, f"kevins-best@{pin_time}", user=BRUNO)

    if expected == "none":
        assert response.status_code == 404
    else:
        wanted = {"at": at, "newest": newest}[expected]
        assert granted_result_id(response) == wanted.result_id


async def test_pin_by_date_a_tie_gives_the_greater_id(
    grant_cf_client: AsyncClient, seed_result: SeedResult
) -> None:
    stamp = _at("2026-09-05T12:00:00+00:00")
    first = await seed_result(reporter=ANA, submitted_at=stamp)
    second = await seed_result(reporter=BRUNO, submitted_at=stamp)
    winner = max(first.result_id, second.result_id, key=uuid.UUID)

    response = await request_grant(grant_cf_client, "kevins-best@2026-09-06", user=BRUNO)

    assert granted_result_id(response) == winner


async def test_pin_forms_resolve_result_score_name_revision(
    grant_cf_client: AsyncClient, seed_result: SeedResult
) -> None:
    original = await seed_result(reporter=ANA, submitted_at=_at("2026-08-10T09:00:00+00:00"))
    joined = await seed_result(reporter=BRUNO, submitted_at=_at("2026-08-11T09:00:00+00:00"))
    r2 = await seed_result(
        reporter=ANA,
        url4=URL4_B,
        revision_of="kevins-best",
        submitted_at=_at("2026-09-05T09:00:00+00:00"),
    )

    by_result = await request_grant(grant_cf_client, f"result:{joined.result_id}", user=BRUNO)
    by_score = await request_grant(grant_cf_client, f"score:{original.head_id}", user=BRUNO)
    by_name = await request_grant(grant_cf_client, "kevins-best", user=BRUNO)
    by_revision = await request_grant(grant_cf_client, "kevins-best@r1", user=BRUNO)

    assert granted_result_id(by_result) == joined.result_id
    assert granted_result_id(by_score) == original.result_id
    assert granted_result_id(by_name) == r2.result_id
    assert granted_result_id(by_revision) == original.result_id


async def test_name_pin_picks_newest_versioned_original_and_does_not_skip_withdrawn(
    grant_cf_client: AsyncClient, seed_result: SeedResult
) -> None:
    old = await seed_result(
        reporter=ANA, benchmark_revision="R1", submitted_at=_at("2026-08-01T09:00:00+00:00")
    )
    unversioned = await seed_result(
        reporter=ANA,
        benchmark_revision="R2",
        receipt=False,
        submitted_at=_at("2026-08-02T09:00:00+00:00"),
    )
    assert unversioned.head_id != old.head_id

    case_a = await request_grant(grant_cf_client, "kevins-best", user=BRUNO)

    await ReportedResult.filter(id=unversioned.result_id).update(cache_version_id=uuid.uuid4())
    await CacheVersionPublication.create(result_id=unversioned.result_id, state="withdrawn")
    case_b = await request_grant(grant_cf_client, "kevins-best", user=BRUNO)
    owner = await request_grant(grant_cf_client, "kevins-best", user=ANA)

    assert granted_result_id(case_a) == old.result_id
    assert case_b.status_code == 410
    assert case_b.json()["detail"]["code"] == "cache_version_withdrawn"
    assert granted_result_id(owner) == unversioned.result_id


async def test_benchmark_mismatch_422(
    grant_cf_client: AsyncClient, seed_result: SeedResult
) -> None:
    on_other = await seed_result(benchmark="other", reporter=ANA)
    on_priv = await seed_result(benchmark="priv", reporter=ANA, url4=URL4_B)

    mismatch = await request_grant(
        grant_cf_client, f"result:{on_other.result_id}", user=BRUNO, benchmark_id="pub"
    )
    hidden = await request_grant(
        grant_cf_client, f"result:{on_priv.result_id}", user=BRUNO, benchmark_id="pub"
    )

    assert mismatch.status_code == 422
    assert mismatch.json()["detail"]["code"] == "replay_benchmark_mismatch"
    assert hidden.status_code == 404


async def test_the_candidate_scan_pages_past_a_full_page_of_unreadable_rows(
    grant_cf_client: AsyncClient, seed_result: SeedResult
) -> None:
    # WHY: the scan reads 100 rows at a time and stops at the first accessible one. On a gated
    # board only the caller's own rows are readable, so Bruno's run sits behind a page of Ana's.
    bruno = await seed_result(
        benchmark="gated", reporter=BRUNO, submitted_at=_at("2026-08-01T09:00:00+00:00")
    )
    head_id = bruno.head_id
    for minute in range(101):
        await ReportedResult.create(
            head_id=head_id,
            is_original=False,
            reporter=ANA,
            score=0.5,
            total_questions=2,
            cache_version_id=uuid.uuid4(),
            submitted_at=_at("2026-08-02T09:00:00+00:00") + timedelta(minutes=minute),
        )

    response = await request_grant(
        grant_cf_client, "kevins-best@2026-12-31", user=BRUNO, benchmark_id="gated"
    )

    assert response.status_code == 200
    assert granted_result_id(response) == bruno.result_id
