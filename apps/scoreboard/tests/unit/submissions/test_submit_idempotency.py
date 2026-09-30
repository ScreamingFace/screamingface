"""SC-3, SC-3a — a resend of one run is one reported result (SC-D1).

FEATURE: OME-1307 (E14). INVARIANT: the run id stored on the result is the SCOPED key, so a second
participant on a private board cannot reach the first one's row by reusing a key (OME-894).
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from scoreboard.scores.models import Benchmark, ReportedResult
from tests.unit.submissions._receipts import ANA, BRUNO, post_score

pytestmark = pytest.mark.asyncio


async def test_retried_submit_same_run_id_one_reported_result(
    clustered_cf_client: AsyncClient,
) -> None:
    first = await post_score(clustered_cf_client, key="run-1")
    second = await post_score(clustered_cf_client, key="run-1")

    assert (first.status_code, second.status_code) == (201, 200)
    assert second.json()["id"] == first.json()["id"]
    assert second.json()["reported_result"]["id"] == first.json()["reported_result"]["id"]
    assert await ReportedResult.filter(head_id=first.json()["id"]).count() == 1


async def test_private_run_id_is_stored_scoped_not_raw(clustered_cf_client: AsyncClient) -> None:
    response = await post_score(clustered_cf_client, benchmark_id="priv", key="run-1")

    assert response.status_code == 201
    stored = await ReportedResult.get(id=response.json()["reported_result"]["id"])
    assert stored.run_id is not None
    assert stored.run_id.startswith("sfp-")
    assert stored.run_id != "run-1"


async def test_a_second_participant_cannot_reach_the_first_ones_row_with_the_same_key(
    clustered_cf_client: AsyncClient,
) -> None:
    ana = await post_score(clustered_cf_client, benchmark_id="priv", key="run-1", user=ANA)
    bruno = await post_score(clustered_cf_client, benchmark_id="priv", key="run-1", user=BRUNO)

    assert (ana.status_code, bruno.status_code) == (201, 201)
    assert bruno.json()["id"] != ana.json()["id"]
    assert bruno.json()["submitted_by"] == "bruno"


async def test_the_same_key_on_a_public_and_a_private_board_is_two_different_runs(
    clustered_cf_client: AsyncClient,
) -> None:
    # The key is global on public boards but scoped on private ones, so the two stored keys differ.
    ana = await post_score(clustered_cf_client, key="shared", user=ANA)
    bruno = await post_score(clustered_cf_client, benchmark_id="priv", key="shared", user=BRUNO)

    assert bruno.status_code == 201
    assert bruno.json()["id"] != ana.json()["id"]
    assert bruno.json()["benchmark_id"] == "priv"


async def test_a_key_bound_to_a_row_the_caller_cannot_read_is_never_handed_back(
    clustered_cf_client: AsyncClient,
) -> None:
    # INVARIANT (OME-894): Ana's run holds the public key `k`. Her board then turns private. Bruno
    # reuses `k` on another public board: the unique run id would reject his insert, and the retry
    # branch must never answer with Ana's row. His run is stored as a NEW submission with no run
    # id.
    ana = await post_score(clustered_cf_client, key="k", user=ANA)
    await Benchmark.filter(id="pub").update(visibility="private")

    bruno = await post_score(clustered_cf_client, benchmark_id="gated", key="k", user=BRUNO)

    assert (ana.status_code, bruno.status_code) == (201, 201)
    assert bruno.json()["id"] != ana.json()["id"]
    assert bruno.json()["benchmark_id"] == "gated"
    stored = await ReportedResult.get(id=bruno.json()["reported_result"]["id"])
    assert stored.run_id is None
