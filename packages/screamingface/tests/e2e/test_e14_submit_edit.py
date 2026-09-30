"""E14 spine MD-21: submit, edit the metadata, read it back on the leaderboard.

FEATURE: OME-1307 (E14) E2E. STORY: as Ana, I submit a run, then add a co-author and my paper
link, and the public leaderboard shows both.

Real gateway, real engine, real scoreboard, zero provider spend. The auth mode is real (D5): the
owner check of the edit uses the verified email the test edge sets, and a client with no edge has
no identity at all.
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
BOARD = "ifeval"
FIRST_PAPER = "https://arxiv.org/abs/2609.01234"
SECOND_PAPER = "https://doi.org/10.1234/abc"
# WHY the edited list is the published form: the public JSON is local-part only.
EDITED_AUTHORS = ["ana@e2e.example", "carol@z.example"]
PUBLISHED_AUTHORS = ["ana", "carol"]


def _get(stack: E14Stack, path: str) -> dict[str, Any]:
    # WHY anonymous: these are public reads of a public board.
    with edge_http(stack.scoreboard_url, None) as http:
        response = http.get(path)
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


def _entries_for(stack: E14Stack, expression: str) -> list[dict[str, Any]]:
    entries = _get(stack, f"/v1/leaderboard/{BOARD}")["entries"]
    return [entry for entry in entries if entry["url4_expression"] == expression]


def _assert_no_identity_no_write(stack: E14Stack, result: Any) -> None:
    # A plain client: no edge, so no verified identity on any request it makes.
    with sf.Client(engine_url=stack.engine_url, scoreboard_url=stack.scoreboard_url) as anonymous:
        with pytest.raises(sf.LeaderboardError) as caught:
            anonymous.leaderboards.submit(result)
    assert caught.value.status == 401
    assert _entries_for(stack, str(result.url4)) == [], "nothing was written"


def test_submit_then_edit_then_read_on_leaderboard(e14: E14Stack, e14_golden: GoldenReport) -> None:
    with edge_client(e14, ANA) as ana:
        report = ana.evaluate(
            e14_candidate(e14_golden), benchmark=BOARD, limit=e14_golden.limit, progress=False
        )
        result = report.candidates.only
        _assert_no_identity_no_write(e14, result)
        submitted = ana.leaderboards.submit(result, paper_url=FIRST_PAPER, authors=[ANA])
        assert submitted.metadata_revision == 1
        assert _get(e14, f"/v1/scores/{submitted.id}")["submitted_by"] == "ana"

        edited = ana.leaderboards.update_submission(
            submitted.id,
            authors=EDITED_AUTHORS,
            paper_url=SECOND_PAPER,
            expected_revision=1,
        )

    assert edited.paper_url == SECOND_PAPER
    assert edited.metadata_revision == 2
    assert list(edited.authors or ()) == PUBLISHED_AUTHORS
    _assert_read_back(e14, str(result.url4), submitted.id)


def _assert_read_back(stack: E14Stack, expression: str, score_id: object) -> None:
    score = _get(stack, f"/v1/scores/{score_id}")
    assert score["paper_url"] == SECOND_PAPER
    assert score["authors"] == PUBLISHED_AUTHORS
    assert score["metadata_revision"] == 2

    (entry,) = _entries_for(stack, expression)
    assert entry["authors"] == PUBLISHED_AUTHORS
    assert entry["paper_url"] == SECOND_PAPER

    events = _get(stack, f"/v1/scores/{score_id}/metadata-history")["events"]
    assert [(event["from_revision"], event["to_revision"]) for event in events] == [(1, 2)]
