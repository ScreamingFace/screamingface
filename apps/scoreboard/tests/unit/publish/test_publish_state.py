"""PB-13, PB-15, PB-16 — the publication state machine (erd 2.6), its table and its routes.

FEATURE: OME-1307 (E14). INVARIANT under test: every cell of the erd 2.6 table, and no other write
of `state` outside `state.apply`.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import get_args

import pytest
from httpx import AsyncClient, Response

from scoreboard.core.publish.state import Event, State, Transition, TransitionRejected, apply
from scoreboard.scores.models import CacheVersionPublication
from tests.unit.publish._fakes import NOW, Seeded
from tests.unit.publish._rows import seed_rows
from tests.unit.publish.conftest import ADMIN
from tests.unit.publish.test_worker import Build
from tests.unit.submissions._receipts import ANA, as_user

Seed = Callable[..., Awaitable[Seeded]]

_REJECT = None

# The table of erd 2.6, cell by cell: (state, event) -> (to, changed, reset_attempts) or reject.
TABLE: dict[tuple[State, Event], tuple[State, bool, bool] | None] = {
    ("private", "owner_publishes"): ("requested", True, False),
    ("private", "worker_succeeds"): _REJECT,
    ("private", "worker_fails_retryable"): _REJECT,
    ("private", "attempts_exhausted"): _REJECT,
    ("private", "admin_takedown"): ("withdrawn", True, False),
    ("requested", "owner_publishes"): ("requested", False, False),
    ("requested", "worker_succeeds"): ("published", True, False),
    ("requested", "worker_fails_retryable"): ("requested", False, False),
    ("requested", "attempts_exhausted"): ("failed", True, False),
    ("requested", "admin_takedown"): ("withdrawn", True, False),
    ("failed", "owner_publishes"): ("requested", True, True),
    ("failed", "worker_succeeds"): _REJECT,
    ("failed", "worker_fails_retryable"): _REJECT,
    ("failed", "attempts_exhausted"): _REJECT,
    ("failed", "admin_takedown"): ("withdrawn", True, False),
    ("published", "owner_publishes"): ("published", False, False),
    ("published", "worker_succeeds"): _REJECT,
    ("published", "worker_fails_retryable"): _REJECT,
    ("published", "attempts_exhausted"): _REJECT,
    ("published", "admin_takedown"): ("withdrawn", True, False),
    ("withdrawn", "owner_publishes"): _REJECT,
    ("withdrawn", "worker_succeeds"): _REJECT,
    ("withdrawn", "worker_fails_retryable"): _REJECT,
    ("withdrawn", "attempts_exhausted"): _REJECT,
    ("withdrawn", "admin_takedown"): ("withdrawn", False, False),
}


def test_the_table_covers_every_state_and_event() -> None:
    # WHY: a cell missing from this test would be a cell nothing checks.
    cells = {(s, e) for s in get_args(State) for e in get_args(Event)}

    assert set(TABLE) == cells


@pytest.mark.parametrize(("cell", "expected"), list(TABLE.items()), ids=lambda v: str(v))
def test_double_publish_is_noop_table(
    cell: tuple[State, Event], expected: tuple[State, bool, bool] | None
) -> None:
    state, event = cell

    if expected is None:
        with pytest.raises(TransitionRejected) as raised:
            apply(state, event)
        assert (raised.value.state, raised.value.event) == cell
    else:
        result = apply(state, event)
        assert result == Transition(*expected)


def test_publish_after_withdraw_is_rejected_by_the_machine() -> None:
    with pytest.raises(TransitionRejected):
        apply("withdrawn", "owner_publishes")


@pytest.mark.asyncio
async def test_publish_after_withdraw_409(publish_client: AsyncClient, seed_result: Seed) -> None:
    seeded = await seed_result(publish_client, board="pub")
    withdrawn = await publish_client.post(
        f"/v1/admin/results/{seeded.result_id}/withdraw",
        json={"reason": "license"},
        headers=as_user(ADMIN),
    )

    response = await publish_client.post(
        f"/v1/results/{seeded.result_id}/publish", headers=as_user(ANA)
    )

    assert withdrawn.status_code == 200
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "withdrawn"
    assert (await CacheVersionPublication.get(result_id=seeded.result_id)).state == "withdrawn"


async def _publish(client: AsyncClient, result_id: str) -> Response:
    return await client.post(f"/v1/results/{result_id}/publish", headers=as_user(ANA))


@pytest.mark.asyncio
async def test_republish_from_failed_resets_attempts(publish_client: AsyncClient) -> None:
    retryable = await seed_rows(state="failed")
    row = await CacheVersionPublication.get(result_id=retryable.result_id)
    row.last_error, row.attempts = "HTTP 502", 8
    await row.save()
    integrity = await seed_rows(state="failed")
    stuck = await CacheVersionPublication.get(result_id=integrity.result_id)
    stuck.last_error = "archive_mismatch"
    await stuck.save()

    again = await _publish(publish_client, retryable.result_id)
    refused = await _publish(publish_client, integrity.result_id)

    assert again.status_code == 202
    assert again.json() == {"state": "requested"}
    row = await CacheVersionPublication.get(result_id=retryable.result_id)
    assert (row.state, row.attempts, row.last_error) == ("requested", 0, None)
    # PB-E5 (OD-3): the owner cannot retry an integrity failure.
    assert refused.status_code == 409
    assert refused.json()["detail"]["code"] == "not_publishable"
    assert refused.json()["detail"]["reason"] == "integrity_failure"
    assert (await CacheVersionPublication.get(result_id=integrity.result_id)).state == "failed"


@pytest.mark.asyncio
async def test_double_publish_is_noop(
    publish_client: AsyncClient, seed_result: Seed, build_worker: Build
) -> None:
    seeded = await seed_result(publish_client, board="pub")

    first = await _publish(publish_client, seeded.result_id)
    second = await _publish(publish_client, seeded.result_id)
    await build_worker(seeded).run_once()
    third = await _publish(publish_client, seeded.result_id)

    assert (first.status_code, first.json()) == (202, {"state": "requested"})
    assert (second.status_code, second.json()) == (200, {"state": "requested"})
    row = await CacheVersionPublication.get(result_id=seeded.result_id)
    assert row.state == "published"
    assert third.status_code == 200
    assert third.json() == {"state": "published", "release_url": row.release_url}
    assert row.published_at == NOW
