"""`display_name` and `website` within one author's `authors_metadata` entry (OME-2041).

FEATURE: OME-2041 — `submit(authors_metadata=...)` already let a caller put ANY key into one
author's entry, sent through unvalidated. This gives `display_name` and `website` first-class
treatment: `display_name` maps onto the existing `full_name` key, and `website` is validated as
an absolute http(s) link using the same shape rules as `paper_url` (mirroring the Scoreboard's
`validate_paper_url`), rather than being passed through as an arbitrary, unvalidated key.

Payloads are asserted as parsed JSON, field by field — same style as
`test_submission_credit_metadata.py`, which this file complements without modifying.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import httpx
import pytest
from test_leaderboards import SCORE_ID, _candidate_result, _score_response, _sync_client


def _recording(seen: list[dict[str, Any]]) -> Callable[[httpx.Request], httpx.Response]:
    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.read()))
        return httpx.Response(201 if request.method == "POST" else 200, json=_score_response())

    return handler


def test_submit_sends_display_name_as_full_name() -> None:
    seen: list[dict[str, Any]] = []

    with _sync_client(_recording(seen)) as client:
        client.leaderboards.submit(
            _candidate_result(), authors_metadata={"ana@uni.edu": {"display_name": "Ana Silva"}}
        )

    (body,) = seen
    assert body["authors_metadata"] == {"ana@uni.edu": {"full_name": "Ana Silva"}}


def test_edit_sends_display_name_as_full_name() -> None:
    seen: list[dict[str, Any]] = []

    with _sync_client(_recording(seen)) as client:
        client.leaderboards.edit(
            SCORE_ID, authors_metadata={"ana@uni.edu": {"display_name": "Ana Silva"}}
        )

    (body,) = seen
    assert body["authors_metadata"] == {"ana@uni.edu": {"full_name": "Ana Silva"}}


def test_submit_sends_an_accepted_website_exactly_as_given() -> None:
    seen: list[dict[str, Any]] = []
    authors = {"ana@uni.edu": {"website": "https://ana.example/profile"}}

    with _sync_client(_recording(seen)) as client:
        client.leaderboards.submit(_candidate_result(), authors_metadata=authors)

    (body,) = seen
    assert body["authors_metadata"] == authors


def test_submit_sends_website_alongside_display_name_and_other_keys() -> None:
    seen: list[dict[str, Any]] = []
    authors = {
        "ana@uni.edu": {
            "display_name": "Ana Silva",
            "website": "https://ana.example",
            "institution": "Uni",
        }
    }

    with _sync_client(_recording(seen)) as client:
        client.leaderboards.submit(_candidate_result(), authors_metadata=authors)

    (body,) = seen
    assert body["authors_metadata"] == {
        "ana@uni.edu": {
            "full_name": "Ana Silva",
            "website": "https://ana.example",
            "institution": "Uni",
        }
    }


@pytest.mark.parametrize(
    "entry",
    [
        {"display_name": "Ana Silva", "full_name": "Ana S."},
        {"full_name": "Ana S.", "display_name": "Ana Silva"},
    ],
)
def test_submit_refuses_both_display_name_and_full_name(entry: dict[str, str]) -> None:
    seen: list[dict[str, Any]] = []

    with (
        _sync_client(_recording(seen)) as client,
        pytest.raises(ValueError, match="display_name"),
    ):
        client.leaderboards.submit(_candidate_result(), authors_metadata={"ana@uni.edu": entry})

    assert seen == []


def test_edit_refuses_both_display_name_and_full_name() -> None:
    seen: list[dict[str, Any]] = []
    entry = {"display_name": "Ana Silva", "full_name": "Ana S."}

    with (
        _sync_client(_recording(seen)) as client,
        pytest.raises(ValueError, match="full_name"),
    ):
        client.leaderboards.edit(SCORE_ID, authors_metadata={"ana@uni.edu": entry})

    assert seen == []


def test_submit_rejects_a_non_string_website_before_http() -> None:
    client = _sync_client(lambda _: pytest.fail("a bad website reached the Scoreboard"))

    with client, pytest.raises(TypeError, match="website"):
        client.leaderboards.submit(
            _candidate_result(), authors_metadata={"ana@uni.edu": {"website": 42}}
        )


# WHY these cases: the same shape rules as `paper_url` (mirroring the Scoreboard's
# `validate_paper_url`), so a link the board's sibling feature would refuse is refused here too.
_REFUSED_WEBSITES = [
    "",
    "ftp://ana.example/",
    "javascript:alert(1)",
    "https:///path",
    "https://",
    "https://user:pw@ana.example/",
    "https://user@ana.example/",
    "https://ana.example/a\x00b",
    "https://ana.example/a\nb",
    " https://ana.example/",
    "https://ana.example/a b",
    "https://x.example/" + "a" * 2048,
]


@pytest.mark.parametrize("website", _REFUSED_WEBSITES)
def test_submit_rejects_a_bad_website_before_http(website: str) -> None:
    client = _sync_client(lambda _: pytest.fail("a bad website reached the Scoreboard"))

    with client, pytest.raises(ValueError, match="website"):
        client.leaderboards.submit(
            _candidate_result(), authors_metadata={"ana@uni.edu": {"website": website}}
        )


@pytest.mark.parametrize("website", _REFUSED_WEBSITES)
def test_edit_rejects_a_bad_website_before_http(website: str) -> None:
    client = _sync_client(lambda _: pytest.fail("a bad website reached the Scoreboard"))

    with client, pytest.raises(ValueError, match="website"):
        client.leaderboards.edit(SCORE_ID, authors_metadata={"ana@uni.edu": {"website": website}})


@pytest.mark.parametrize(
    "website",
    [
        "HTTPS://Ana.Example/profile",
        "http://ana.example:8080/p?q=1#top",
        "https://ana.example/a%20b",
    ],
)
def test_submit_sends_an_accepted_website_unmodified(website: str) -> None:
    seen: list[dict[str, Any]] = []

    with _sync_client(_recording(seen)) as client:
        client.leaderboards.submit(
            _candidate_result(), authors_metadata={"ana@uni.edu": {"website": website}}
        )

    (body,) = seen
    assert body["authors_metadata"]["ana@uni.edu"]["website"] == website


def test_prior_unknown_key_shape_rules_are_unchanged() -> None:
    """A non-`website`/`display_name` key keeps exactly its old, unvalidated-scalar behavior."""
    seen: list[dict[str, Any]] = []
    authors = {"ana@uni.edu": {"homepage": "not a url and that's fine, it's not a known key"}}

    with _sync_client(_recording(seen)) as client:
        client.leaderboards.submit(_candidate_result(), authors_metadata=authors)

    (body,) = seen
    assert body["authors_metadata"] == authors
