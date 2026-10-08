"""Record one exact reproduction on the board (E14 B5, design §6, §7).

FEATURE: OME-1307 — `Leaderboards._record_reproduction` posts the numbers of an exact replay to
`POST /v1/scores/{id}/reproductions`. It is internal: `reproduce` calls it and turns any error into
`record_error`, so this seam raises the Client's typed `LeaderboardError` and never returns a
half-recorded state.
STORY: as someone who reproduced a score, the board stores my replay once, and a refusal tells me
why in the board's own words.

The board half (B4) is faked with `httpx.MockTransport` against the B4 route (`frozen_copy_id`).
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
from test_leaderboards import SCORE_ID, _async_client, _sync_client

import screamingface as sf
from screamingface._scoreboard.leaderboards import _client_info

COPY = "0b1f6d3a-5c0e-4a8e-9a3f-2f6f8f4c7d11"
RUN_ID = "replay-run-1"
CLIENT = {"name": "screamingface", "version": "0.2.0", "platform": "darwin"}
RECORDED = {
    "id": "7c2e5b1a-0d44-4a60-9c3e-1d2f3a4b5c6d",
    "score_id": SCORE_ID,
    "reproduced_by": "reader@example.com",
    "reproduced_at": "2026-10-07T09:00:00Z",
    "run_id": RUN_ID,
    "frozen_copy_id": COPY,
    "client_version": "0.2.0",
}


def _arguments() -> dict[str, Any]:
    return {
        "run_id": RUN_ID,
        "score": 0.5,
        "total_questions": 2,
        "frozen_copy_id": COPY,
        "client": CLIENT,
    }


def test_the_record_posts_the_numbers_of_the_replay() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(201, json=RECORDED)

    with _sync_client(handler) as client:
        client.leaderboards._record_reproduction(SCORE_ID, **_arguments())

    assert (seen[0].method, seen[0].url.path) == ("POST", f"/v1/scores/{SCORE_ID}/reproductions")
    assert json.loads(seen[0].read()) == {
        "run_id": RUN_ID,
        "score": 0.5,
        "total_questions": 2,
        "frozen_copy_id": COPY,
        "client": CLIENT,
    }


def test_a_repeated_run_id_answers_200_and_is_not_an_error() -> None:
    # The board answers 200 with the first row for the same run_id.
    with _sync_client(lambda _: httpx.Response(200, json=RECORDED)) as client:
        client.leaderboards._record_reproduction(SCORE_ID, **_arguments())


@pytest.mark.parametrize(
    ("status", "body", "code", "text"),
    [
        (401, {"detail": "no identity"}, "scoreboard_authentication_required", "no identity"),
        (403, {"detail": "untrusted peer"}, "reproduction_forbidden", "untrusted peer"),
        (
            409,
            {"detail": {"code": "not_reproducible", "message": "not complete"}},
            "reproduction_conflict",
            "not_reproducible: not complete",
        ),
        (
            409,
            {"detail": {"code": "run_id_conflict", "message": "send a new run_id"}},
            "reproduction_conflict",
            "run_id_conflict: send a new run_id",
        ),
        (
            409,
            {"detail": "the board changed visibility; retry"},
            "reproduction_conflict",
            "the board changed visibility; retry",
        ),
        (
            422,
            {"detail": {"code": "not_exact", "message": "numbers differ"}},
            "invalid_reproduction",
            "not_exact: numbers differ",
        ),
    ],
)
def test_a_board_refusal_is_a_typed_error_that_keeps_its_words(
    status: int, body: dict[str, object], code: str, text: str
) -> None:
    with _sync_client(lambda _: httpx.Response(status, json=body)) as client:
        with pytest.raises(sf.LeaderboardError) as raised:
            client.leaderboards._record_reproduction(SCORE_ID, **_arguments())

    assert raised.value.code == code
    assert raised.value.status == status
    assert text in str(raised.value)


def test_a_missing_score_is_unknown_score() -> None:
    with _sync_client(lambda _: httpx.Response(404, json={"detail": "Score not found"})) as client:
        with pytest.raises(sf.LeaderboardError) as raised:
            client.leaderboards._record_reproduction(SCORE_ID, **_arguments())

    assert raised.value.code == "unknown_score"


def test_an_unreachable_board_is_a_typed_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down", request=request)

    with _sync_client(handler) as client:
        with pytest.raises(sf.LeaderboardError) as raised:
            client.leaderboards._record_reproduction(SCORE_ID, **_arguments())

    assert raised.value.code == "scoreboard_unreachable"


def test_the_client_info_names_this_client() -> None:
    info = _client_info()

    assert info["name"] == "screamingface"
    assert set(info) == {"name", "version", "platform"}


@pytest.mark.asyncio
async def test_the_async_record_posts_and_maps_errors_the_same_way() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if len(seen) == 1:
            return httpx.Response(201, json=RECORDED)
        return httpx.Response(422, json={"detail": {"code": "not_exact", "message": "differs"}})

    async with _async_client(handler) as client:
        await client.leaderboards._record_reproduction(SCORE_ID, **_arguments())
        with pytest.raises(sf.LeaderboardError) as raised:
            await client.leaderboards._record_reproduction(SCORE_ID, **_arguments())

    assert json.loads(seen[0].read())["run_id"] == RUN_ID
    assert raised.value.code == "invalid_reproduction"
    assert "not_exact: differs" in str(raised.value)
