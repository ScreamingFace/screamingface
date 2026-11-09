"""FEATURE: OME-1613 — module-level edit preserves omitted fields and legacy implementations."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from test_leaderboards import SCORE_ID

import screamingface as sf
from screamingface import _default_client


def test_edit_accepts_a_legacy_implementation(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[tuple[str, str | None]] = []
    result = object()

    class LegacyLeaderboards:
        def edit(self, score_id: str, *, paper_url: str | None) -> object:
            seen.append((score_id, paper_url))
            return result

    monkeypatch.setattr(
        _default_client, "_client", SimpleNamespace(leaderboards=LegacyLeaderboards())
    )

    assert sf.leaderboards.edit(SCORE_ID, paper_url=None) is result
    assert seen == [(SCORE_ID, None)]


@pytest.mark.parametrize(
    "fields",
    [
        {},
        {"authors": None},
        {"paper_url": None},
        {"authors_metadata": None},
        {"paper_metadata": None},
        {"authors_metadata": {}, "paper_metadata": {}},
        {"authors": ["ana@uni.edu"], "paper_url": "https://example.org/paper"},
        {
            "authors_metadata": {"ana@uni.edu": {"full_name": "Ana"}},
            "paper_metadata": {"title": "A"},
        },
    ],
)
def test_edit_forwards_only_supplied_fields(
    monkeypatch: pytest.MonkeyPatch, fields: dict[str, Any]
) -> None:
    seen: list[tuple[str, dict[str, Any]]] = []
    result = object()

    class RecordingLeaderboards:
        def edit(self, score_id: str, **kwargs: Any) -> object:
            seen.append((score_id, kwargs))
            return result

    monkeypatch.setattr(
        _default_client, "_client", SimpleNamespace(leaderboards=RecordingLeaderboards())
    )

    assert sf.leaderboards.edit(SCORE_ID, **fields) is result
    assert seen == [(SCORE_ID, fields)]
