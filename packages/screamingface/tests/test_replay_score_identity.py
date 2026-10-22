"""FEATURE: OME-1613 — a score replay must use the score the caller requested.

INVARIANT: neither a public nor a gated response may substitute another score before execution
or recording. Exercise the public evaluate entry points with otherwise valid score bodies.
"""

from __future__ import annotations

import pytest
from test_replay import GATED_PATH, PUBLIC_PATH, _async_client, _Board, _client, _score
from test_reproduce import SCORE_ID, _AsyncReplayer, _Replayer

from screamingface.errors import LeaderboardError

OTHER_SCORE_ID = "11111111-1111-4111-8111-111111111111"


@pytest.mark.parametrize("private", [False, True], ids=["public", "gated"])
def test_mismatched_score_is_rejected_before_sync_execution(private: bool) -> None:
    body = _score(id=OTHER_SCORE_ID)
    board = _Board(gated=body) if private else _Board(public=body)
    engine = _Replayer()

    with _client(engine, board) as client:
        with pytest.raises(LeaderboardError) as caught:
            client.evaluate(score_id=SCORE_ID, progress=False)

    assert caught.value.code == "invalid_leaderboard"
    assert engine.candidate is None
    assert board.requests == [("GET", PUBLIC_PATH)] + ([("GET", GATED_PATH)] if private else [])
    assert board.posted == []


@pytest.mark.asyncio
@pytest.mark.parametrize("private", [False, True], ids=["public", "gated"])
async def test_mismatched_score_is_rejected_before_async_execution(private: bool) -> None:
    body = _score(id=OTHER_SCORE_ID)
    board = _Board(gated=body) if private else _Board(public=body)
    engine = _AsyncReplayer()

    async with _async_client(engine, board) as client:
        with pytest.raises(LeaderboardError) as caught:
            await client.evaluate(score_id=SCORE_ID, progress=False)

    assert caught.value.code == "invalid_leaderboard"
    assert engine.candidate is None
    assert board.requests == [("GET", PUBLIC_PATH)] + ([("GET", GATED_PATH)] if private else [])
    assert board.posted == []
