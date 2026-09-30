"""`publish_cache_version` sends the publish request and types its answers (E14, PB-21, C10).

FEATURE: OME-1307 (E14) publish and takedown. The SDK half of contract C10 for the owner's
`POST /v1/results/{result_id}/publish`. One `httpx.MockTransport` fakes the Scoreboard (D7 X-20).
The portal button and the "Published"/"Withdrawn" markers are SB-publish work (OD-12).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any
from uuid import UUID

import httpx
import pytest

import screamingface as sf
from screamingface import _default_client

SCOREBOARD_URL = "https://scoreboard.example"
RESULT_ID = UUID("3f0c5d0e-6f0b-4d75-a1f1-0c6f0b7d2a10")
VERSION_ID = "9b2c5f52-3c0a-4a37-8a54-6c3f1c1c5b11"
RELEASE_URL = (
    f"https://github.com/ScreamingFace/screamingface-cache-versions/releases/tag/cv-{VERSION_ID}"
)


class _Scoreboard:
    def __init__(self, reply: httpx.Response | Exception) -> None:
        self.requests: list[httpx.Request] = []
        self._reply = reply

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if isinstance(self._reply, Exception):
            raise self._reply
        return self._reply


def _sync_client(handler: Callable[[httpx.Request], httpx.Response]) -> sf.Client:
    return sf.Client(
        engine_url="https://engine.example",
        scoreboard_url=SCOREBOARD_URL,
        scoreboard_transport=httpx.MockTransport(handler),
    )


def _async_client(handler: Callable[[httpx.Request], httpx.Response]) -> sf.AsyncClient:
    return sf.AsyncClient(
        engine_url="https://engine.example",
        scoreboard_url=SCOREBOARD_URL,
        scoreboard_transport=httpx.MockTransport(handler),
    )


def test_pb21_publish_sends_post_and_decodes_requested() -> None:
    board = _Scoreboard(httpx.Response(202, json={"state": "requested"}))

    with _sync_client(board) as client:
        value = client.leaderboards.publish_cache_version(RESULT_ID)

    request = board.requests[0]
    assert (request.method, request.url.path) == ("POST", f"/v1/results/{RESULT_ID}/publish")
    assert request.content == b""
    assert value == sf.CacheVersionPublication(RESULT_ID, "requested", None)


@pytest.mark.asyncio
async def test_pb21_publish_sends_post_and_decodes_requested_async() -> None:
    board = _Scoreboard(httpx.Response(202, json={"state": "requested"}))
    client = _async_client(board)

    try:
        value = await client.leaderboards.publish_cache_version(RESULT_ID)
    finally:
        await client.aclose()

    assert board.requests[0].url.path == f"/v1/results/{RESULT_ID}/publish"
    assert value == sf.CacheVersionPublication(RESULT_ID, "requested", None)


def test_pb21_a_result_id_given_as_text_is_accepted() -> None:
    board = _Scoreboard(httpx.Response(202, json={"state": "requested"}))

    with _sync_client(board) as client:
        value = client.leaderboards.publish_cache_version(str(RESULT_ID))

    assert value.result_id == RESULT_ID


def test_pb21_published_noop_returns_the_release_url() -> None:
    board = _Scoreboard(
        httpx.Response(200, json={"state": "published", "release_url": RELEASE_URL})
    )

    with _sync_client(board) as client:
        value = client.leaderboards.publish_cache_version(RESULT_ID)

    assert value == sf.CacheVersionPublication(RESULT_ID, "published", RELEASE_URL)


@pytest.mark.asyncio
async def test_pb21_published_noop_returns_the_release_url_async() -> None:
    board = _Scoreboard(
        httpx.Response(200, json={"state": "published", "release_url": RELEASE_URL})
    )
    client = _async_client(board)

    try:
        value = await client.leaderboards.publish_cache_version(RESULT_ID)
    finally:
        await client.aclose()

    assert value == sf.CacheVersionPublication(RESULT_ID, "published", RELEASE_URL)


def test_pb21_a_null_release_url_stays_none() -> None:
    board = _Scoreboard(httpx.Response(200, json={"state": "published", "release_url": None}))

    with _sync_client(board) as client:
        value = client.leaderboards.publish_cache_version(RESULT_ID)

    assert value.release_url is None


_ERRORS = [
    (403, {"detail": {"code": "not_result_owner", "message": "not yours"}}, "not_result_owner"),
    (404, {"detail": "no such result"}, "unknown_result"),
    (
        409,
        {"detail": {"code": "not_publishable", "message": "private", "reason": "private_board"}},
        "not_publishable",
    ),
    (409, {"detail": {"code": "withdrawn", "message": "withdrawn"}}, "withdrawn"),
    (503, {"detail": {"code": "publish_unavailable", "message": "off"}}, "publish_unavailable"),
    (403, {}, "not_result_owner"),
    (409, {}, "not_publishable"),
    (503, {}, "publish_unavailable"),
    (401, {}, "scoreboard_contract_error"),
]


@pytest.mark.parametrize(("status", "body", "code"), _ERRORS)
def test_pb21_publish_errors_are_typed(status: int, body: dict[str, Any], code: str) -> None:
    board = _Scoreboard(httpx.Response(status, json=body))

    with _sync_client(board) as client, pytest.raises(sf.LeaderboardError) as caught:
        client.leaderboards.publish_cache_version(RESULT_ID)

    assert caught.value.code == code
    assert caught.value.status == status
    assert len(board.requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(("status", "body", "code"), _ERRORS)
async def test_pb21_publish_errors_are_typed_async(
    status: int, body: dict[str, Any], code: str
) -> None:
    board = _Scoreboard(httpx.Response(status, json=body))
    client = _async_client(board)

    try:
        with pytest.raises(sf.LeaderboardError) as caught:
            await client.leaderboards.publish_cache_version(RESULT_ID)
    finally:
        await client.aclose()

    assert caught.value.code == code


@pytest.mark.parametrize("reason", ["private_board", "not_redistributable", "no_cache_version"])
def test_pb21_not_publishable_keeps_its_reason(reason: str) -> None:
    body = {"detail": {"code": "not_publishable", "message": "no", "reason": reason}}
    board = _Scoreboard(httpx.Response(409, json=body))

    with _sync_client(board) as client, pytest.raises(sf.LeaderboardError) as caught:
        client.leaderboards.publish_cache_version(RESULT_ID)

    assert isinstance(caught.value.details, dict)
    assert caught.value.details["detail"]["reason"] == reason


def test_pb21_a_coded_409_is_permanent_and_a_503_is_retryable() -> None:
    conflict = _Scoreboard(httpx.Response(409, json={"detail": {"code": "withdrawn"}}))
    down = _Scoreboard(httpx.Response(503, json={}))

    with _sync_client(conflict) as client, pytest.raises(sf.LeaderboardError) as refused:
        client.leaderboards.publish_cache_version(RESULT_ID)
    with _sync_client(down) as client, pytest.raises(sf.LeaderboardError) as unavailable:
        client.leaderboards.publish_cache_version(RESULT_ID)

    assert refused.value.permanent is True
    assert unavailable.value.permanent is False


@pytest.mark.parametrize(
    "body",
    [
        {"state": "private"},
        {"state": "failed"},
        {"state": None},
        {},
        {"state": "requested", "release_url": 5},
        ["requested"],
    ],
)
def test_pb21_a_state_other_than_requested_or_published_is_invalid(body: object) -> None:
    board = _Scoreboard(httpx.Response(200, json=body))

    with _sync_client(board) as client, pytest.raises(sf.LeaderboardError) as caught:
        client.leaderboards.publish_cache_version(RESULT_ID)

    assert caught.value.code == "invalid_leaderboard"


def test_pb21_an_unreachable_scoreboard_is_a_leaderboard_error() -> None:
    board = _Scoreboard(httpx.ConnectError("refused"))

    with _sync_client(board) as client, pytest.raises(sf.LeaderboardError) as caught:
        client.leaderboards.publish_cache_version(RESULT_ID)

    assert caught.value.code == "scoreboard_unreachable"


@pytest.mark.parametrize("bad", ["not-a-uuid", "", 5, None])
def test_pb21_invalid_result_id_raises_before_any_call(bad: object) -> None:
    board = _Scoreboard(httpx.Response(202, json={"state": "requested"}))

    with _sync_client(board) as client, pytest.raises((TypeError, ValueError)):
        client.leaderboards.publish_cache_version(bad)  # type: ignore[arg-type]

    assert board.requests == []


@pytest.mark.asyncio
@pytest.mark.parametrize("bad", ["not-a-uuid", 5])
async def test_pb21_invalid_result_id_raises_before_any_call_async(bad: object) -> None:
    board = _Scoreboard(httpx.Response(202, json={"state": "requested"}))
    client = _async_client(board)

    try:
        with pytest.raises((TypeError, ValueError)):
            await client.leaderboards.publish_cache_version(bad)  # type: ignore[arg-type]
    finally:
        await client.aclose()

    assert board.requests == []


def test_pb21_facade_passes_through(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[UUID | str] = []
    expected = sf.CacheVersionPublication(RESULT_ID, "requested", None)

    class _Leaderboards:
        def publish_cache_version(self, result_id: UUID | str) -> sf.CacheVersionPublication:
            seen.append(result_id)
            return expected

    class _Client:
        leaderboards = _Leaderboards()

    monkeypatch.setattr(_default_client, "_client", _Client())

    assert sf.leaderboards.publish_cache_version(RESULT_ID) is expected
    assert seen == [RESULT_ID]


@pytest.mark.parametrize(
    ("state", "message"),
    [("private", "state"), ("requested", None)],
)
def test_pb21_publication_value_validates_its_fields(state: str, message: str | None) -> None:
    if message is None:
        assert sf.CacheVersionPublication(RESULT_ID, state).release_url is None  # type: ignore[arg-type]
        return
    with pytest.raises(ValueError, match=message):
        sf.CacheVersionPublication(RESULT_ID, state)  # type: ignore[arg-type]


def test_pb21_publication_value_refuses_a_result_id_that_is_not_a_uuid() -> None:
    with pytest.raises(TypeError):
        sf.CacheVersionPublication("3f0c5d0e", "requested")  # type: ignore[arg-type]
