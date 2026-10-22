"""The module-level `sf.leaderboards.submit` / `.edit` take the metadata fields too (OME-1613).

FEATURE: OME-1613 S9 — review (Dmitry, #1519): the README calls
`sf.leaderboards.edit(..., authors_metadata=..., paper_metadata=...)`, so the module-level wrappers
must accept and forward both fields. `edit` keeps "omitted" distinct from an explicit `None`.
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
from test_leaderboards import SCORE_ID, _candidate_result, _score_response, _sync_client

import screamingface as sf
from screamingface import _default_client

AUTHORS = {"ana@uni.edu": {"full_name": "Ana Silva"}}
PAPER = {"title": "A paper", "url": "https://example.org/paper"}


@pytest.fixture
def seen(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    bodies: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        bodies.append(json.loads(request.read()))
        return httpx.Response(201 if request.method == "POST" else 200, json=_score_response())

    # WHY `_client`, not `default_client`: `sf.leaderboards` imports `default_client` by name, so
    # only the cached instance reaches it. Patching the function let a real client reach the
    # production board once (review fix run, 2026-10-22).
    monkeypatch.setattr(_default_client, "_client", _sync_client(handler))
    return bodies


def test_module_submit_forwards_both_objects(seen: list[dict[str, Any]]) -> None:
    sf.leaderboards.submit(_candidate_result(), authors_metadata=AUTHORS, paper_metadata=PAPER)

    (body,) = seen
    assert (body["authors_metadata"], body["paper_metadata"]) == (AUTHORS, PAPER)


def test_module_submit_without_them_sends_neither(seen: list[dict[str, Any]]) -> None:
    sf.leaderboards.submit(_candidate_result())

    (body,) = seen
    assert "authors_metadata" not in body
    assert "paper_metadata" not in body


def test_module_edit_keeps_omitted_distinct_from_none(seen: list[dict[str, Any]]) -> None:
    sf.leaderboards.edit(SCORE_ID, authors_metadata=AUTHORS)
    sf.leaderboards.edit(SCORE_ID, paper_metadata=None)

    assert seen == [{"authors_metadata": AUTHORS}, {"paper_metadata": None}]
