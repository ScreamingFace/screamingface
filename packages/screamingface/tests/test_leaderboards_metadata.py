"""Paper link, metadata edit and edit log at the SDK seam (E14 A2, OME-1307).

The Scoreboard half is built in parallel; every test fakes it with `httpx.MockTransport` against
contracts K4, K5, K6 and K8.
"""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import httpx
import pytest
from test_leaderboards import (
    SCORE_ID,
    _async_client,
    _candidate_result,
    _score_response,
    _sync_client,
)

import screamingface as sf
from screamingface import _default_client

EVENT_ID = "6f1d0a52-3c1e-4c43-8f0e-0b3f3a5a9c11"
EDITED_AT = "2026-10-07T09:00:00Z"
PAPER = "https://arxiv.org/abs/2610.01234"


def _edited_response(**overrides: object) -> dict[str, object]:
    return {
        **_score_response(),
        "paper_url": PAPER,
        "metadata_updated_at": EDITED_AT,
        **overrides,
    }


def _event(**overrides: object) -> dict[str, object]:
    return {
        "id": EVENT_ID,
        "edited_by": "researcher@example.com",
        "edited_at": EDITED_AT,
        "source": "patch",
        "old_authors": None,
        "new_authors": ["a@x.org", "b@y.org"],
        "old_paper_url": None,
        "new_paper_url": PAPER,
        **overrides,
    }


def _body(request: httpx.Request) -> dict[str, object]:
    return json.loads(request.read())


# --- TDD #19: submit sends paper_url only when given --------------------------------------------


def test_submit_sends_paper_url_only_when_given() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(201, json=_edited_response())

    with _sync_client(handler) as client:
        client.leaderboards.submit(_candidate_result())
        score = client.leaderboards.submit(_candidate_result(), paper_url=PAPER)

    assert "paper_url" not in _body(seen[0])
    assert _body(seen[1])["paper_url"] == PAPER
    assert score.paper_url == PAPER
    assert score.metadata_updated_at == datetime(2026, 10, 7, 9, tzinfo=UTC)


@pytest.mark.parametrize(
    "paper_url",
    ["javascript:alert(1)", "ftp://example.org/p.pdf", "https://x.org/" + "a" * 2048, ""],
)
def test_submit_rejects_a_bad_paper_url_before_http(paper_url: str) -> None:
    client = _sync_client(lambda _: pytest.fail("a bad paper_url reached the Scoreboard"))

    with client, pytest.raises(ValueError, match="paper_url"):
        client.leaderboards.submit(_candidate_result(), paper_url=paper_url)


# WHY these cases: they mirror the Scoreboard's `_validate_paper_url` exactly, so a link the board
# would 422 is refused here before any HTTP.
_REFUSED_LINKS = [
    "https://x.org/a\x00b",
    "https://x.org/a\x1fb",
    "https://x.org/a\x7fb",
    "https://x.org/a\nb",
    "https://x.org/a\tb",
    " https://x.org/",
    "https://x.org/ ",
    "https://x.org/a b",
    "https://x.org/a\u00a0b",
    "https:///path",
    "https://",
    "https://:8080/",
    "http:",
    "https://user:pw@x.org/",
    "https://user@x.org/",
    "https://trusted.example@evil.test/",
    "https://@x.org/",
]


@pytest.mark.parametrize("paper_url", _REFUSED_LINKS)
def test_submit_refuses_a_link_the_board_would_refuse(paper_url: str) -> None:
    client = _sync_client(lambda _: pytest.fail("a bad paper_url reached the Scoreboard"))

    with client, pytest.raises(ValueError, match="paper_url"):
        client.leaderboards.submit(_candidate_result(), paper_url=paper_url)


@pytest.mark.parametrize("paper_url", _REFUSED_LINKS)
def test_edit_refuses_a_link_the_board_would_refuse(paper_url: str) -> None:
    client = _sync_client(lambda _: pytest.fail("a bad paper_url reached the Scoreboard"))

    with client, pytest.raises(ValueError, match="paper_url"):
        client.leaderboards.edit(SCORE_ID, paper_url=paper_url)


@pytest.mark.parametrize(
    "paper_url",
    [
        "HTTPS://Arxiv.org/abs/2610.01234",
        "http://x.org:8080/p?q=1#top",
        "https://x.org/a%20b",
        "https://[::1]/p",
    ],
)
def test_submit_sends_an_accepted_link_exactly_as_given(paper_url: str) -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(201, json=_edited_response())

    with _sync_client(handler) as client:
        client.leaderboards.submit(_candidate_result(), paper_url=paper_url)

    assert _body(seen[0])["paper_url"] == paper_url


def test_submit_rejects_a_non_string_paper_url() -> None:
    client = _sync_client(lambda _: pytest.fail("a bad paper_url reached the Scoreboard"))

    with client, pytest.raises(TypeError, match="paper_url"):
        client.leaderboards.submit(_candidate_result(), paper_url=42)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_async_submit_sends_paper_url_only_when_given() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(201, json=_edited_response())

    async with _async_client(handler) as client:
        await client.leaderboards.submit(_candidate_result())
        await client.leaderboards.submit(_candidate_result(), paper_url=PAPER)

    assert "paper_url" not in _body(seen[0])
    assert _body(seen[1])["paper_url"] == PAPER


def test_an_older_board_without_the_new_fields_decodes_as_none() -> None:
    with _sync_client(lambda _: httpx.Response(200, json=_score_response())) as client:
        score = client.leaderboards.get_score(SCORE_ID)

    assert score.paper_url is None
    assert score.metadata_updated_at is None


def test_the_board_may_send_explicit_nulls_for_the_new_fields() -> None:
    body = _edited_response(paper_url=None, metadata_updated_at=None)
    with _sync_client(lambda _: httpx.Response(200, json=body)) as client:
        score = client.leaderboards.get_score(SCORE_ID)

    assert score.paper_url is None
    assert score.metadata_updated_at is None


def test_the_board_sending_a_malformed_paper_url_is_a_contract_error() -> None:
    body = _edited_response(paper_url=7)
    with (
        _sync_client(lambda _: httpx.Response(200, json=body)) as client,
        pytest.raises(sf.LeaderboardError) as exc_info,
    ):
        client.leaderboards.get_score(SCORE_ID)

    assert exc_info.value.code == "invalid_leaderboard"


# --- TDD #20: edit sends PATCH and decodes the score ---------------------------------------------


def test_edit_sends_patch_and_decodes_score() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=_edited_response())

    with _sync_client(handler) as client:
        score = client.leaderboards.edit(UUID(SCORE_ID), paper_url=PAPER)

    assert seen[0].method == "PATCH"
    assert seen[0].url.path == f"/v1/scores/{SCORE_ID}"
    assert _body(seen[0]) == {"paper_url": PAPER}
    assert isinstance(score, sf.LeaderboardScore)
    assert score.id == UUID(SCORE_ID)
    assert score.paper_url == PAPER
    assert score.metadata_updated_at == datetime(2026, 10, 7, 9, tzinfo=UTC)
    assert score.scoreboard_url == "https://scoreboard.example"


def test_edit_sends_authors_and_paper_url_together_and_accepts_a_string_id() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=_edited_response())

    with _sync_client(handler) as client:
        client.leaderboards.edit(SCORE_ID, authors=["a@x.org", "b@y.org"], paper_url=PAPER)

    assert seen[0].url.path == f"/v1/scores/{SCORE_ID}"
    assert _body(seen[0]) == {"authors": ["a@x.org", "b@y.org"], "paper_url": PAPER}


def test_edit_with_paper_url_none_sends_null_to_clear_the_link() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=_edited_response(paper_url=None))

    with _sync_client(handler) as client:
        score = client.leaderboards.edit(SCORE_ID, paper_url=None)

    assert _body(seen[0]) == {"paper_url": None}
    assert score.paper_url is None


def test_edit_omits_a_field_that_was_not_given() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=_edited_response())

    with _sync_client(handler) as client:
        client.leaderboards.edit(SCORE_ID, authors=["a@x.org"])

    assert _body(seen[0]) == {"authors": ["a@x.org"]}


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({}, "at least one"),
        ({"authors": None}, "authors"),
        ({"authors": []}, "at least one email"),
        ({"authors": ["not-an-email"]}, "valid email"),
        ({"paper_url": "javascript:alert(1)"}, "paper_url"),
    ],
)
def test_edit_refuses_bad_arguments_before_http(kwargs: dict[str, Any], message: str) -> None:
    client = _sync_client(lambda _: pytest.fail("a bad edit reached the Scoreboard"))

    with client, pytest.raises(ValueError, match=message):
        client.leaderboards.edit(SCORE_ID, **kwargs)


def test_edit_refuses_a_non_string_paper_url_before_http() -> None:
    client = _sync_client(lambda _: pytest.fail("a bad edit reached the Scoreboard"))

    with client, pytest.raises(TypeError, match="paper_url"):
        client.leaderboards.edit(SCORE_ID, paper_url=42)  # type: ignore[arg-type]


def test_edit_refuses_a_bad_score_id_before_http() -> None:
    client = _sync_client(lambda _: pytest.fail("a bad edit reached the Scoreboard"))

    with client, pytest.raises(ValueError, match="score_id"):
        client.leaderboards.edit("not-a-uuid", paper_url=PAPER)


@pytest.mark.asyncio
async def test_async_edit_sends_patch_and_decodes_score() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=_edited_response())

    async with _async_client(handler) as client:
        score = await client.leaderboards.edit(SCORE_ID, paper_url=PAPER, authors=["a@x.org"])
        cleared = await client.leaderboards.edit(SCORE_ID, paper_url=None)

    assert seen[0].method == "PATCH"
    assert _body(seen[0]) == {"authors": ["a@x.org"], "paper_url": PAPER}
    assert _body(seen[1]) == {"paper_url": None}
    assert score.paper_url == PAPER
    assert cleared.id == UUID(SCORE_ID)


@pytest.mark.asyncio
async def test_async_edit_refuses_bad_arguments_before_http() -> None:
    client = _async_client(lambda _: pytest.fail("a bad edit reached the Scoreboard"))

    async with client:
        with pytest.raises(ValueError, match="at least one"):
            await client.leaderboards.edit(SCORE_ID)
        with pytest.raises(ValueError, match="authors"):
            await client.leaderboards.edit(SCORE_ID, authors=None)


# --- TDD #21: edit maps 403 / 404 / 422 to typed errors ------------------------------------------


@pytest.mark.parametrize(
    ("status", "code", "detail"),
    [
        (403, "score_edit_forbidden", "not_score_owner"),
        (404, "unknown_score", "Score not found"),
        (422, "invalid_score_edit", "paper_url must be http or https"),
    ],
)
def test_edit_maps_403_404_422_to_typed_errors(status: int, code: str, detail: str) -> None:
    client = _sync_client(lambda _: httpx.Response(status, json={"detail": detail}))

    with client, pytest.raises(sf.LeaderboardError) as exc_info:
        client.leaderboards.edit(SCORE_ID, paper_url=PAPER)

    assert exc_info.value.code == code
    assert exc_info.value.status == status
    assert exc_info.value.permanent is True
    if status != 404:
        assert exc_info.value.details == detail


def _coded(code: str, message: str) -> dict[str, object]:
    return {"detail": {"code": code, "message": message}}


def test_edit_403_with_the_real_coded_body_surfaces_the_server_message() -> None:
    body = _coded("not_score_owner", "only the submitter can edit this score")
    client = _sync_client(lambda _: httpx.Response(403, json=body))

    with client, pytest.raises(sf.LeaderboardError) as exc_info:
        client.leaderboards.edit(SCORE_ID, paper_url=PAPER)

    error = exc_info.value
    assert error.code == "score_edit_forbidden"
    assert error.status == 403
    assert error.details == "not_score_owner: only the submitter can edit this score"
    assert "not_score_owner: only the submitter can edit this score" in str(error)


def test_metadata_events_403_with_the_real_coded_body_surfaces_the_server_message() -> None:
    body = _coded("not_score_owner", "only the submitter can read this log")
    client = _sync_client(lambda _: httpx.Response(403, json=body))

    with client, pytest.raises(sf.LeaderboardError) as exc_info:
        client.leaderboards.metadata_events(SCORE_ID)

    assert exc_info.value.code == "score_events_forbidden"
    assert "not_score_owner: only the submitter can read this log" in str(exc_info.value)


@pytest.mark.parametrize(
    "detail",
    [
        {"code": "not_score_owner"},
        {"message": "no code"},
        {"code": 7, "message": "bad code type"},
        {"code": "x", "message": 7},
        {"field": "paper_url", "message": "bad"},
    ],
)
def test_an_error_detail_that_is_not_a_coded_pair_is_left_as_it_came(
    detail: dict[str, object],
) -> None:
    client = _sync_client(lambda _: httpx.Response(422, json={"detail": detail}))

    with client, pytest.raises(sf.LeaderboardError) as exc_info:
        client.leaderboards.edit(SCORE_ID, paper_url=PAPER)

    assert exc_info.value.details == {"detail": detail}
    assert "(" not in str(exc_info.value)


def test_edit_409_is_a_retryable_conflict() -> None:
    client = _sync_client(
        lambda _: httpx.Response(409, json={"detail": "the benchmark's visibility changed; retry"})
    )

    with client, pytest.raises(sf.LeaderboardError) as exc_info:
        client.leaderboards.edit(SCORE_ID, paper_url=PAPER)

    error = exc_info.value
    assert error.code == "score_edit_conflict"
    assert error.status == 409
    assert error.permanent is False
    assert error.hint == "Retry the edit."
    assert "the benchmark's visibility changed; retry" in str(error)


@pytest.mark.asyncio
async def test_async_edit_409_is_a_retryable_conflict() -> None:
    async with _async_client(lambda _: httpx.Response(409, json={"detail": "retry"})) as client:
        with pytest.raises(sf.LeaderboardError) as exc_info:
            await client.leaderboards.edit(SCORE_ID, paper_url=PAPER)

    assert exc_info.value.code == "score_edit_conflict"
    assert exc_info.value.permanent is False
    assert exc_info.value.hint == "Retry the edit."


def test_metadata_events_409_is_not_treated_as_a_retryable_edit_conflict() -> None:
    client = _sync_client(lambda _: httpx.Response(409, json={"detail": "x"}))

    with client, pytest.raises(sf.LeaderboardError) as exc_info:
        client.leaderboards.metadata_events(SCORE_ID)

    assert exc_info.value.code == "scoreboard_contract_error"
    assert exc_info.value.permanent is True
    assert exc_info.value.hint is None


def test_submit_errors_keep_their_shape_after_the_detail_unwrap() -> None:
    string_detail = _sync_client(
        lambda _: httpx.Response(403, json={"detail": "score submission is not open yet"})
    )
    with string_detail, pytest.raises(sf.LeaderboardError) as exc_info:
        string_detail.leaderboards.submit(_candidate_result())
    assert exc_info.value.code == "score_submission_forbidden"
    assert exc_info.value.details == "score submission is not open yet"
    assert str(exc_info.value).endswith("HTTP 403 (score submission is not open yet)")

    field_detail = {"detail": {"field": "paper_url", "message": "must name a host"}}
    mapping_detail = _sync_client(lambda _: httpx.Response(422, json=field_detail))
    with mapping_detail, pytest.raises(sf.LeaderboardError) as exc_info:
        mapping_detail.leaderboards.submit(_candidate_result())
    assert exc_info.value.code == "invalid_score_submission"
    assert exc_info.value.details == field_detail
    assert str(exc_info.value).endswith("HTTP 422")

    conflict = _sync_client(lambda _: httpx.Response(409, json={"detail": "busy"}))
    with conflict, pytest.raises(sf.LeaderboardError) as exc_info:
        conflict.leaderboards.submit(_candidate_result())
    assert exc_info.value.code == "score_submission_conflict"
    assert exc_info.value.permanent is False
    assert exc_info.value.hint == "Retry the submission."


def test_edit_maps_401_to_the_authentication_code() -> None:
    client = _sync_client(lambda _: httpx.Response(401, json={"detail": "authentication required"}))

    with client, pytest.raises(sf.LeaderboardError) as exc_info:
        client.leaderboards.edit(SCORE_ID, paper_url=PAPER)

    assert exc_info.value.code == "scoreboard_authentication_required"
    assert exc_info.value.status == 401


def test_metadata_events_maps_401_to_the_authentication_code() -> None:
    client = _sync_client(lambda _: httpx.Response(401, json={"detail": "authentication required"}))

    with client, pytest.raises(sf.LeaderboardError) as exc_info:
        client.leaderboards.metadata_events(SCORE_ID)

    assert exc_info.value.code == "scoreboard_authentication_required"
    assert exc_info.value.status == 401


def test_edit_404_names_the_score() -> None:
    client = _sync_client(lambda _: httpx.Response(404, json={"detail": "Score not found"}))

    with client, pytest.raises(sf.LeaderboardError, match=SCORE_ID):
        client.leaderboards.edit(SCORE_ID, paper_url=PAPER)


def test_edit_unknown_status_falls_back_to_the_contract_error_code() -> None:
    client = _sync_client(lambda _: httpx.Response(503))

    with client, pytest.raises(sf.LeaderboardError) as exc_info:
        client.leaderboards.edit(SCORE_ID, paper_url=PAPER)

    assert exc_info.value.code == "scoreboard_contract_error"
    assert exc_info.value.permanent is False


@pytest.mark.asyncio
async def test_async_edit_maps_typed_errors() -> None:
    async with _async_client(
        lambda _: httpx.Response(403, json={"detail": "not_score_owner"})
    ) as client:
        with pytest.raises(sf.LeaderboardError) as exc_info:
            await client.leaderboards.edit(SCORE_ID, paper_url=PAPER)

    assert exc_info.value.code == "score_edit_forbidden"


# --- TDD #22: metadata_events decodes the list ---------------------------------------------------


def test_metadata_events_decodes_list() -> None:
    seen: list[httpx.Request] = []
    rows = [
        _event(),
        _event(
            id="0d6a7a0e-8a54-4b43-9d3a-1a1a1a1a1a1a",
            source="resubmit",
            old_authors=["a@x.org", "b@y.org"],
            new_authors=None,
            old_paper_url=PAPER,
            new_paper_url=None,
        ),
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=rows)

    with _sync_client(handler) as client:
        events = client.leaderboards.metadata_events(UUID(SCORE_ID))

    assert seen[0].method == "GET"
    assert seen[0].url.path == f"/v1/scores/{SCORE_ID}/metadata-events"
    assert isinstance(events, tuple)
    assert events[0] == sf.ScoreMetadataEvent(
        id=UUID(EVENT_ID),
        edited_by="researcher@example.com",
        edited_at=datetime(2026, 10, 7, 9, tzinfo=UTC),
        source="patch",
        old_authors=None,
        new_authors=("a@x.org", "b@y.org"),
        old_paper_url=None,
        new_paper_url=PAPER,
    )
    assert events[1].source == "resubmit"
    assert events[1].old_authors == ("a@x.org", "b@y.org")
    assert events[1].new_authors is None
    assert events[1].old_paper_url == PAPER
    assert events[1].new_paper_url is None


def test_metadata_events_of_a_score_with_no_edits_is_empty() -> None:
    with _sync_client(lambda _: httpx.Response(200, json=[])) as client:
        assert client.leaderboards.metadata_events(SCORE_ID) == ()


@pytest.mark.parametrize(
    ("status", "code"),
    [
        (403, "score_events_forbidden"),
        (404, "unknown_score"),
    ],
)
def test_metadata_events_maps_errors(status: int, code: str) -> None:
    client = _sync_client(lambda _: httpx.Response(status, json={"detail": "no"}))

    with client, pytest.raises(sf.LeaderboardError) as exc_info:
        client.leaderboards.metadata_events(SCORE_ID)

    assert exc_info.value.code == code
    assert exc_info.value.status == status


@pytest.mark.parametrize(
    "payload",
    [
        {"events": []},
        [{**_event(), "source": "admin"}],
        [{**_event(), "edited_at": "2026-10-07T09:00:00"}],
        [{**_event(), "old_authors": []}],
        [{**_event(), "new_paper_url": 3}],
        ["not-an-object"],
    ],
)
def test_metadata_events_rejects_a_malformed_board_response(payload: object) -> None:
    client = _sync_client(lambda _: httpx.Response(200, json=payload))

    with client, pytest.raises(sf.LeaderboardError) as exc_info:
        client.leaderboards.metadata_events(SCORE_ID)

    assert exc_info.value.code == "invalid_leaderboard"


@pytest.mark.asyncio
async def test_async_metadata_events_decodes_list() -> None:
    async with _async_client(lambda _: httpx.Response(200, json=[_event()])) as client:
        events = await client.leaderboards.metadata_events(SCORE_ID)

    assert [event.id for event in events] == [UUID(EVENT_ID)]


def test_score_metadata_event_validates_its_fields() -> None:
    valid: dict[str, Any] = {
        "id": UUID(EVENT_ID),
        "edited_by": "researcher@example.com",
        "edited_at": datetime(2026, 10, 7, 9, tzinfo=UTC),
        "source": "patch",
        "old_authors": None,
        "new_authors": ("a@x.org",),
        "old_paper_url": None,
        "new_paper_url": PAPER,
    }
    assert sf.ScoreMetadataEvent(**valid).new_authors == ("a@x.org",)

    with pytest.raises(TypeError, match="id"):
        sf.ScoreMetadataEvent(**{**valid, "id": EVENT_ID})
    with pytest.raises(ValueError, match="edited_by"):
        sf.ScoreMetadataEvent(**{**valid, "edited_by": " "})
    with pytest.raises(ValueError, match="timezone-aware"):
        sf.ScoreMetadataEvent(**{**valid, "edited_at": datetime(2026, 10, 7, 9)})
    with pytest.raises(ValueError, match="source"):
        sf.ScoreMetadataEvent(**{**valid, "source": "admin"})
    with pytest.raises(ValueError, match="must not be empty"):
        sf.ScoreMetadataEvent(**{**valid, "new_authors": ()})
    with pytest.raises(ValueError, match="new_paper_url"):
        sf.ScoreMetadataEvent(**{**valid, "new_paper_url": " "})


def test_leaderboard_score_validates_the_new_fields() -> None:
    score = replace(
        _decoded_score(),
        paper_url=PAPER,
        metadata_updated_at=datetime(2026, 10, 7, 9, tzinfo=UTC),
    )
    assert score.paper_url == PAPER

    with pytest.raises(ValueError, match="timezone-aware"):
        replace(_decoded_score(), metadata_updated_at=datetime(2026, 10, 7, 9))
    with pytest.raises(ValueError, match="paper_url"):
        replace(_decoded_score(), paper_url=" ")


def _decoded_score() -> sf.LeaderboardScore:
    with _sync_client(lambda _: httpx.Response(200, json=_score_response())) as client:
        return client.leaderboards.get_score(SCORE_ID)


# --- module-level wrappers -----------------------------------------------------------------------


def test_module_wrappers_reach_the_default_client(monkeypatch: Any) -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url.path.endswith("/metadata-events"):
            return httpx.Response(200, json=[_event()])
        return httpx.Response(200, json=_edited_response())

    client = _sync_client(handler)
    monkeypatch.setattr(_default_client, "_client", client)

    assert sf.leaderboards.edit(SCORE_ID, paper_url=PAPER).paper_url == PAPER
    assert sf.leaderboards.edit(SCORE_ID, authors=["a@x.org"], paper_url=None).id == UUID(SCORE_ID)
    assert sf.leaderboards.edit(SCORE_ID, authors=["a@x.org"]).id == UUID(SCORE_ID)
    assert len(sf.leaderboards.metadata_events(SCORE_ID)) == 1
    assert [request.method for request in seen] == ["PATCH", "PATCH", "PATCH", "GET"]
    assert _body(seen[0]) == {"paper_url": PAPER}
    assert _body(seen[1]) == {"authors": ["a@x.org"], "paper_url": None}
    assert _body(seen[2]) == {"authors": ["a@x.org"]}
    assert {"edit", "metadata_events"} <= set(sf.leaderboards.__all__)

    client.close()
    monkeypatch.setattr(_default_client, "_client", None)


def test_module_submit_forwards_paper_url_only_when_given(monkeypatch: Any) -> None:
    calls: list[dict[str, object]] = []

    class Leaderboards:
        # Mirrors a Leaderboards that predates `paper_url`: an unexpected kwarg would raise.
        def submit(self, candidate_result: object, **fields: object) -> str:
            calls.append(fields)
            return "submitted"

    class FakeClient:
        leaderboards = Leaderboards()

    monkeypatch.setattr(_default_client, "_client", FakeClient())
    candidate = _candidate_result()

    assert sf.leaderboards.submit(candidate) == "submitted"
    assert sf.leaderboards.submit(candidate, paper_url=PAPER) == "submitted"
    assert calls == [{"authors": None}, {"authors": None, "paper_url": PAPER}]

    monkeypatch.setattr(_default_client, "_client", None)
