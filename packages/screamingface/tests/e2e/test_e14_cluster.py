"""E14 spine SC-23: two users, one system, one row, two results, the original ranks.

FEATURE: OME-1307 (E14) E2E. STORY: as Bruno, I re-run Ana's published system and submit it, and
the board keeps one row (Ana's original) with two reported results under it.

Real gateway, real engine, real scoreboard, zero provider spend (the ``ifeval`` snapshot serves
every model answer). The scoreboard and the gateway run ``cloudflare_headers`` (D5), so Ana and
Bruno are the verified emails the test edge sets, and the receipt ``sub`` is checked for real.
"""

from __future__ import annotations

from typing import Any

import pytest
from harness.e14_stack import E14Stack, e14_candidate
from harness.goldens import GoldenReport
from harness.identity import edge_client, edge_http

import screamingface as sf

pytestmark = pytest.mark.e2e

ANA = "ana@e2e.example"
BRUNO = "bruno@e2e.example"
BOARD = "ifeval"
_RANKED_COLUMNS = ("score", "run_cost_usd", "total_questions", "submitted_by")


def _run_and_submit(
    stack: E14Stack, user: str, golden: GoldenReport
) -> tuple[Any, sf.LeaderboardScore]:
    with edge_client(stack, user) as client:
        report = client.evaluate(
            e14_candidate(golden), benchmark=BOARD, limit=golden.limit, progress=False
        )
        return report.candidates.only, client.leaderboards.submit(report.candidates.only)


def _get(stack: E14Stack, path: str) -> dict[str, Any]:
    # WHY anonymous: these are public reads of a public board.
    with edge_http(stack.scoreboard_url, None) as http:
        response = http.get(path)
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


def _ranked_columns(stack: E14Stack, score_id: object) -> dict[str, Any]:
    body = _get(stack, f"/v1/scores/{score_id}")
    return {column: body[column] for column in _RANKED_COLUMNS}


def test_two_users_same_system_one_row_two_results_original_ranks(
    e14: E14Stack, e14_golden: GoldenReport
) -> None:
    candidate_a, a = _run_and_submit(e14, ANA, e14_golden)

    assert a.reported_result is not None
    assert a.reported_result.is_original is True
    assert a.reported_result.cache_version is not None
    assert a.reported_result.cache_version.coverage_status == "complete"
    # WHY the warning check: the scoreboard checks that the receipt `sub` equals the verified
    # submitter (C3). A `sub` mismatch gives `403 cache_version_not_yours`, and a gateway that did
    # not see Ana's email gives no receipt.
    assert a.cache_version_warning is None
    ranked_before = _ranked_columns(e14, a.id)
    assert ranked_before["submitted_by"] == "ana"

    _candidate_b, b = _run_and_submit(e14, BRUNO, e14_golden)

    assert b.id == a.id, "the second run of one system must cluster under the first head"
    assert b.reported_result is not None
    assert b.reported_result.is_original is False
    assert any(
        notice.code == "clustered_under" and notice.details.get("score_id") == str(a.id)
        for notice in b.notices
    ), b.notices
    # INVARIANT (SC-H3): the original keeps its rank; a later result never changes it.
    assert _ranked_columns(e14, a.id) == ranked_before

    _assert_one_row(e14, str(candidate_a.url4), a.id, ranked_before)
    _assert_two_results(e14, a.id)


def _assert_one_row(
    stack: E14Stack, expression: str, head_id: object, ranked: dict[str, Any]
) -> None:
    entries = _get(stack, f"/v1/leaderboard/{BOARD}")["entries"]
    matching = [entry for entry in entries if entry["url4_expression"] == expression]
    assert len(matching) == 1, "two results of one system must show as ONE leaderboard row"
    entry = matching[0]
    assert {column: entry[column] for column in ("score", "run_cost_usd")} == {
        column: ranked[column] for column in ("score", "run_cost_usd")
    }
    assert entry["submitted_by"] == "ana"
    assert entry["score_id"] == str(head_id)
    assert entry["reported_results_count"] == 2


def _assert_two_results(stack: E14Stack, head_id: object) -> None:
    results = _get(stack, f"/v1/scores/{head_id}/results")["results"]
    assert len(results) == 2
    assert [result["reporter"] for result in results] == ["bruno", "ana"], "newest first"
    versions = {result["cache_version"]["id"] for result in results}
    assert len(versions) == 2, "each run freezes its own cache version"
