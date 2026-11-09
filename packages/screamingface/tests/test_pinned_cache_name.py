"""The frozen copy is called `pinned_cache` in the Python API (OME-1613 row 2, spec Q12).

FEATURE: OME-1613 — the user-facing name is "pinned cache". The owner chose a hard rename with no
alias (2026-10-21): the field was one week old and the SDK is pre-1.0.
INVARIANT: only the Python name changes. The report's JSON keeps the `frozen_copy_id` key and the
board's wire field keeps its name, so exported reports and the board contract are unchanged.
"""

from __future__ import annotations

import dataclasses
import json
from typing import Any

import pytest
from test_leaderboards import _candidate_result, _score_response
from test_reproduce import COPY, _score

import screamingface as sf
from screamingface._scoreboard.leaderboards import _decode_score


def _captured_result(**overrides: object) -> sf.CandidateResult:
    base = _candidate_result()
    values: dict[str, Any] = {
        name: getattr(base, name)
        for name in (
            "benchmark",
            "run_id",
            "started_at",
            "completed_at",
            "name",
            "kind",
            "url4",
            "models",
            "operations",
            "score",
            "coverage",
            "cases",
            "members",
            "failures",
            "usage",
        )
    }
    values["metrics"] = dict(base.metrics)
    values.update({"pinned_cache": COPY, "capture_status": "complete"})
    values.update(overrides)
    return sf.CandidateResult(**values)


def test_a_candidate_result_names_its_copy_pinned_cache() -> None:
    result = _captured_result()

    assert result.pinned_cache == COPY
    assert not hasattr(result, "frozen_copy_id")


def test_the_old_keyword_is_refused() -> None:
    with pytest.raises(TypeError):
        _captured_result(pinned_cache=None, frozen_copy_id=COPY)


def test_the_report_json_keeps_the_wire_key() -> None:
    exported = json.loads(json.dumps(_captured_result().to_dict(), default=str))

    assert exported["frozen_copy_id"] == COPY
    assert "pinned_cache" not in exported


def test_a_pinned_cache_that_is_not_a_uuid_is_refused() -> None:
    with pytest.raises(ValueError):
        _captured_result(pinned_cache="not-a-uuid")


def test_a_leaderboard_score_names_its_copy_pinned_cache() -> None:
    score = _score(pinned_cache=COPY)

    assert score.pinned_cache == COPY
    assert "frozen_copy_id" not in {field.name for field in dataclasses.fields(score)}


def test_a_leaderboard_score_refuses_the_old_keyword() -> None:
    values = {field.name: getattr(_score(), field.name) for field in dataclasses.fields(_score())}
    values["frozen_copy_id"] = values.pop("pinned_cache")

    with pytest.raises(TypeError):
        sf.LeaderboardScore(**values)


def test_the_board_wire_field_decodes_into_pinned_cache() -> None:
    payload = _score_response()
    payload.update({"frozen_copy_id": COPY, "capture_status": "complete"})

    assert _decode_score(payload).pinned_cache == COPY
