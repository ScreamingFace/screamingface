"""E14 spine RP-21: replay a pinned run, then submit it labelled as a replay.

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
