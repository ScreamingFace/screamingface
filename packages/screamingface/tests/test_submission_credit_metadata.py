"""`authors_metadata` and `paper_metadata` on submit, edit and read (OME-1613 row 6, S9).

FEATURE: OME-1613 S9 / OME-1596 — a submitter attaches metadata about the credited authors (keyed
by author email: `full_name`, `institution`, any other key) and about the paper (`title`, `url`,
`citation`, any other key), and edits them later.
INVARIANT: the board owns keys, bounds and matching. The SDK checks only the shapes the board's
validator types (flat objects of text, finite numbers or booleans), so a typo fails before the
request. Edit: an omitted field is unchanged, `None` clears it, an object replaces it whole.

Payloads are asserted as parsed JSON, field by field.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import httpx
import pytest
from test_leaderboards import (
    SCORE_ID,
    _async_client,
    _candidate_result,
    _score_response,
    _sync_client,
)

AUTHORS = {"ana@uni.edu": {"full_name": "Ana Silva", "institution": "Uni", "orcid": "0000"}}
PAPER = {"title": "A paper", "url": "https://example.org/paper", "citation": "Silva 2026", "n": 3}


def _recording(seen: list[dict[str, Any]]) -> Callable[[httpx.Request], httpx.Response]:
    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.read()))
        return httpx.Response(201 if request.method == "POST" else 200, json=_score_response())

    return handler


def test_submit_sends_both_objects_as_given() -> None:
    seen: list[dict[str, Any]] = []

    with _sync_client(_recording(seen)) as client:
        client.leaderboards.submit(
            _candidate_result(), authors_metadata=AUTHORS, paper_metadata=PAPER
        )

    (body,) = seen
    assert body["authors_metadata"] == AUTHORS
    assert body["paper_metadata"] == PAPER


def test_submit_omits_both_when_not_given() -> None:
    seen: list[dict[str, Any]] = []

    with _sync_client(_recording(seen)) as client:
        client.leaderboards.submit(_candidate_result())

    (body,) = seen
    assert "authors_metadata" not in body
    assert "paper_metadata" not in body


def test_edit_replaces_clears_or_leaves_each_object() -> None:
    seen: list[dict[str, Any]] = []

    with _sync_client(_recording(seen)) as client:
        client.leaderboards.edit(SCORE_ID, authors_metadata=AUTHORS)
        client.leaderboards.edit(SCORE_ID, paper_metadata=None)
        client.leaderboards.edit(SCORE_ID, paper_metadata={})

    assert seen == [
        {"authors_metadata": AUTHORS},
        {"paper_metadata": None},
        {"paper_metadata": {}},
    ]


def test_edit_with_nothing_to_change_is_refused() -> None:
    seen: list[dict[str, Any]] = []

    with _sync_client(_recording(seen)) as client, pytest.raises(ValueError):
        client.leaderboards.edit(SCORE_ID)

    assert seen == []


@pytest.mark.parametrize(
    ("field", "value", "error"),
    [
        ("authors_metadata", ["ana@uni.edu"], TypeError),
        ("authors_metadata", {7: {"full_name": "Ana"}}, TypeError),
        ("authors_metadata", {"ana@uni.edu": "Ana Silva"}, TypeError),
        ("authors_metadata", {"ana@uni.edu": {"full_name": None}}, TypeError),
        ("authors_metadata", {"ana@uni.edu": {"tags": ["a"]}}, TypeError),
        ("paper_metadata", "https://example.org/paper", TypeError),
        ("paper_metadata", {"title": {"en": "A paper"}}, TypeError),
        ("paper_metadata", {1: "x"}, TypeError),
        ("paper_metadata", {"year": None}, TypeError),
    ],
)
def test_a_shape_the_board_never_accepts_fails_before_any_request(
    field: str, value: object, error: type[Exception]
) -> None:
    seen: list[dict[str, Any]] = []
    arguments: dict[str, Any] = {field: value}

    with _sync_client(_recording(seen)) as client:
        with pytest.raises(error):
            client.leaderboards.submit(_candidate_result(), **arguments)
        with pytest.raises(error):
            client.leaderboards.edit(SCORE_ID, **arguments)

    assert seen == []


@pytest.mark.parametrize("value", ["text", 3, 2.5, True])
def test_every_scalar_the_board_accepts_is_sent(value: object) -> None:
    seen: list[dict[str, Any]] = []

    with _sync_client(_recording(seen)) as client:
        client.leaderboards.edit(SCORE_ID, paper_metadata={"x": value})

    assert seen == [{"paper_metadata": {"x": value}}]


def test_a_score_reads_both_objects_back() -> None:
    payload = {**_score_response(), "authors_metadata": AUTHORS, "paper_metadata": PAPER}

    with _sync_client(lambda _: httpx.Response(200, json=payload)) as client:
        score = client.leaderboards.get_score(SCORE_ID)

    assert score.authors_metadata == AUTHORS
    assert score.paper_metadata == PAPER


def test_a_score_without_them_reads_none() -> None:
    with _sync_client(lambda _: httpx.Response(200, json=_score_response())) as client:
        score = client.leaderboards.get_score(SCORE_ID)

    assert (score.authors_metadata, score.paper_metadata) == (None, None)


def test_the_read_objects_cannot_be_changed() -> None:
    payload = {**_score_response(), "authors_metadata": AUTHORS, "paper_metadata": PAPER}

    with _sync_client(lambda _: httpx.Response(200, json=payload)) as client:
        score = client.leaderboards.get_score(SCORE_ID)

    assert score.paper_metadata is not None and score.authors_metadata is not None
    with pytest.raises(TypeError):
        score.paper_metadata["title"] = "changed"  # type: ignore[index]
    with pytest.raises(TypeError):
        score.authors_metadata["ana@uni.edu"]["full_name"] = "x"  # type: ignore[index]


@pytest.mark.asyncio
async def test_the_async_submit_and_edit_send_the_same_objects() -> None:
    seen: list[dict[str, Any]] = []

    async with _async_client(_recording(seen)) as client:
        await client.leaderboards.submit(
            _candidate_result(), authors_metadata=AUTHORS, paper_metadata=PAPER
        )
        await client.leaderboards.edit(SCORE_ID, paper_metadata=None)

    assert (seen[0]["authors_metadata"], seen[0]["paper_metadata"]) == (AUTHORS, PAPER)
    assert seen[1] == {"paper_metadata": None}
