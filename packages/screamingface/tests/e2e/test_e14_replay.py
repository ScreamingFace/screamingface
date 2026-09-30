"""E14 spines RP-21 and RP-22: replay a pinned run, then submit it labelled as a replay.

FEATURE: OME-1307 (E14) E2E. STORY: as Bruno, I replay Ana's submitted run from her frozen
cache version, and the board shows my result as a replay of hers.

Real gateway, real engine, real scoreboard, zero provider spend. The scoreboard signs the grant
for the verified email (D5), and the gateway checks the grant ``sub`` against the caller.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest
from harness.e14_stack import E14Stack, e14_candidate
from harness.goldens import GoldenReport
from harness.identity import edge_client, edge_http

pytestmark = pytest.mark.e2e

ANA = "ana@e2e.example"
BRUNO = "bruno@e2e.example"
BOARD = "ifeval"


def _results(stack: E14Stack, head_id: object) -> list[dict[str, Any]]:
    # WHY anonymous: the results list of a public board is a public read.
    with edge_http(stack.scoreboard_url, None) as http:
        response = http.get(f"/v1/scores/{head_id}/results")
    assert response.status_code == 200, response.text
    results: list[dict[str, Any]] = response.json()["results"]
    return results


def test_submit_then_other_user_replays_all_hits_zero_cost_then_submit_labelled_replay(
    e14: E14Stack, e14_golden: GoldenReport
) -> None:
    candidate = e14_candidate(e14_golden)
    with edge_client(e14, ANA) as ana:
        ana_report = ana.evaluate(
            candidate, benchmark=BOARD, limit=e14_golden.limit, progress=False
        )
        a = ana.leaderboards.submit(ana_report.candidates.only)
    assert a.reported_result is not None
    assert a.reported_result.cache_version is not None
    x = a.reported_result.id
    version = a.reported_result.cache_version

    with edge_client(e14, BRUNO) as bruno:
        # Bruno is not the owner: a non-owner replay needs the redistributable board.
        report = bruno.evaluate(
            candidate,
            benchmark=BOARD,
            limit=e14_golden.limit,
            replay=f"result:{x}",
            progress=False,
        )
        replayed = report.candidates.only
        _assert_all_hits(replayed, x, version)
        b = bruno.leaderboards.submit(replayed)

    assert replayed.replay is not None
    assert b.reported_result is not None
    assert b.reported_result.is_original is False
    assert b.id == a.id, "the replay result clusters under Ana's head"
    _assert_labelled_replay(_results(e14, a.id), b.reported_result.id, x, replayed.replay.hits)


def _assert_all_hits(candidate_result: Any, x: object, version: Any) -> None:
    replay = candidate_result.replay
    assert replay is not None
    assert replay.result_id == x
    assert replay.cache_version_id == version.id
    assert replay.misses == 0
    # WHY call_count and not entry_count: `hits` counts calls, and `call_count` counts the ledger
    # rows of the original trace. `entry_count` counts distinct (key_hash, blob) pairs, so it is
    # smaller when a call repeats.
    assert replay.hits == version.call_count
    assert replay.coverage == "complete"
    # AIDEV-NOTE: in this keyless stack a global-cache hit is also free, so the cost check alone
    # is weak. The strong check is `misses == 0`: every call was served from the version.
    assert candidate_result.usage.cost_usd == Decimal("0")


def _assert_labelled_replay(
    results: list[dict[str, Any]], result_id: object, x: object, hits: int | None
) -> None:
    item = next(result for result in results if result["id"] == str(result_id))
    assert item["replay"]["replayed_from_result_id"] == str(x)
    assert item["replay"]["hits"] == hits
    assert item["replay"]["misses"] == 0


KEVIN = "kevin@e2e.example"
RECIPE_NAME = "e2e-kevins-best"


def _kevin_baseline_and_changed_recipe(golden: GoldenReport) -> tuple[Any, Any]:
    """`A` (the pinned version) and `B` (the changed recipe). Both carry the same name."""
    version_recipe = e14_candidate(golden, name=RECIPE_NAME, max_rounds=_rounds(golden) - 1)
    return version_recipe, e14_candidate(golden, name=RECIPE_NAME)


def _rounds(golden: GoldenReport) -> int:
    assert golden.max_rounds is not None
    return golden.max_rounds


# WHY skipped (OD-4, open item in docs/work/2026-09-29-e14-e2e.md): RP-22 needs a changed recipe
# whose calls overlap the pinned version and whose other calls are all in the seeded snapshot.
# The Step 6 feasibility probe of the plan ran `A = max_rounds - 1` against the committed `ifeval`
# snapshot: check 1 FAILED. Six cases of `A` got a gateway `404` (a cache miss, `upstream_error`
# with status 404), so the calls of `A` are NOT a subset of the recording. A recipe with no miss
# needs a new fixture, which needs a paid owner run (`tests/e2e/README.md` step 3). No paid call
# was made. Remove this mark when a zero-spend E14 RP-22 fixture is committed.
@pytest.mark.skip(
    reason=(
        "RP-22 needs a zero-spend fixture that does not exist: a changed-recipe variant of the "
        "ifeval snapshot whose calls are all recorded (the max_rounds-1 probe missed the cache on "
        "6 of 50 cases). A new fixture needs a paid owner run (OD-4)."
    )
)
def test_changed_recipe_pin_by_date_partial_hits(e14: E14Stack, e14_golden: GoldenReport) -> None:
    version_recipe, changed_recipe = _kevin_baseline_and_changed_recipe(e14_golden)
    with edge_client(e14, KEVIN) as kevin:
        run = kevin.evaluate(
            version_recipe, benchmark=BOARD, limit=e14_golden.limit, progress=False
        )
        r1 = kevin.leaderboards.submit(run.candidates.only)
        assert r1.spec_id == RECIPE_NAME
        assert r1.reported_result is not None
        assert r1.reported_result.is_original is True
        x1 = r1.reported_result.id
        pin = f"{RECIPE_NAME}@{_submitted_at(e14, r1.id)}"

        report = kevin.evaluate(
            changed_recipe, benchmark=BOARD, limit=e14_golden.limit, replay=pin, progress=False
        )
        replayed = report.candidates.only
        replay = replayed.replay
        assert replay is not None
        assert replay.pinned_baseline_result_id == x1
        assert replay.result_id == x1
        assert (replay.hits or 0) > 0
        assert (replay.misses or 0) > 0
        assert replay.coverage == "partial"

        r2 = kevin.leaderboards.submit(replayed, revision_of=RECIPE_NAME)

    _assert_new_head_labelled_from(e14, r1.id, r2, x1, replay)


def _assert_new_head_labelled_from(
    stack: E14Stack, old_head: object, new: Any, x1: object, replay: Any
) -> None:
    assert new.id != old_head, "a changed recipe makes a NEW head"
    assert new.spec_id == RECIPE_NAME
    assert new.reported_result is not None
    assert new.reported_result.is_original is True
    (item,) = _results(stack, new.id)
    assert item["replay"]["pinned_baseline_result_id"] == str(x1)
    assert item["replay"]["replayed_from_result_id"] == str(x1)
    assert (item["replay"]["hits"], item["replay"]["misses"]) == (replay.hits, replay.misses)


def _submitted_at(stack: E14Stack, score_id: object) -> str:
    # WHY equal-T: a result with `submitted_at == T` is included by the pin (RP-D7), so the pin is
    # deterministic with no clock control and no sleep. The pin grammar needs a UTC offset.
    with edge_http(stack.scoreboard_url, None) as http:
        response = http.get(f"/v1/scores/{score_id}")
    assert response.status_code == 200, response.text
    submitted_at: str = response.json()["submitted_at"]
    assert submitted_at.endswith(("Z", "+00:00")), submitted_at
    return submitted_at
