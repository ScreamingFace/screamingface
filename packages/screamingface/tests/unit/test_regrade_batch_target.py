"""A batch settles only evidence for its exact source and target transition."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from test_regrade_batch_script import _NEW, _OLD, _board, _entry, batch

from screamingface.errors import LeaderboardError


class _Client:
    def __init__(self, *, existing: bool = False, **changes: Any) -> None:
        self.result = SimpleNamespace(
            **{
                "id": "new-score",
                "score_id": "new-score",
                "benchmark_id": "inspect-mmlu_pro",
                "benchmark_revision": _NEW,
                "regraded_from": "source",
                **changes,
            }
        )
        self.existing = existing
        self.targets: list[str | None] = []
        self.reads: list[str] = []
        self.leaderboards = SimpleNamespace(_public_score=self.read)

    def read(self, score_id: str) -> Any:
        self.reads.append(str(score_id))
        return self.result

    def regrade(self, score_id: str, *, expected_target_revision: str | None = None) -> Any:
        assert score_id == "source"
        self.targets.append(expected_target_revision)
        if self.existing:
            error = LeaderboardError("already", code="already_regraded")
            error.existing_score_id = self.result.score_id
            raise error
        return self.result


@pytest.mark.parametrize("existing", [False, True])
def test_batch_pins_target_and_checks_existing_result(tmp_path: Path, existing: bool) -> None:
    client = _Client(existing=existing)
    counts = batch.regrade_all(client, [_entry("source", "spec")], tmp_path / "log")
    assert client.targets == [_NEW]
    assert counts["unresolved"] == 0
    assert counts["already_regraded" if existing else "regraded"] == 1
    assert client.reads == (["new-score"] if existing else [])


@pytest.mark.parametrize("existing", [False, True])
@pytest.mark.parametrize(
    "changes",
    [
        {"benchmark_revision": "future-target"},
        {"benchmark_revision": None},
        {"benchmark_id": "other-board"},
        {"regraded_from": "other-source"},
        {"regraded_from": None},
        {"id": None, "score_id": None},
    ],
)
def test_wrong_or_missing_result_evidence_stays_unresolved(
    tmp_path: Path, existing: bool, changes: dict[str, Any]
) -> None:
    client = _Client(existing=existing, **changes)
    counts = batch.regrade_all(client, [_entry("source", "spec")], tmp_path / "log")
    assert counts == {"refused_retryable": 1, "unresolved": 1}
    assert batch.exit_status(counts) == 1


def test_failed_existing_score_read_cannot_settle_the_entry(tmp_path: Path) -> None:
    client = _Client(existing=True)

    def missing(score_id: str) -> Any:
        raise LeaderboardError("not found", code="unknown_score", permanent=True)

    client.leaderboards._public_score = missing
    counts = batch.regrade_all(client, [_entry("source", "spec")], tmp_path / "log")
    assert counts == {"refused_retryable": 1, "unresolved": 1}


def test_a_resolved_score_cannot_hide_an_uncached_spec_with_the_same_id(tmp_path: Path) -> None:
    client = _Client()
    counts = batch.regrade_all(
        client, [_entry("source", "cached-spec"), _entry(None, "source")], tmp_path / "log"
    )
    assert counts == {"regraded": 1, "no_pinned_cache": 1, "unresolved": 1}


@pytest.mark.parametrize("missing", [True, False])
def test_source_requires_explicit_metadata_even_when_empty(missing: bool) -> None:
    def board(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/revisions"):
            revisions = [] if missing else [{"revision": _OLD, "result_count": 0}]
            return httpx.Response(200, json={"revisions": revisions})
        if request.url.path == "/v1/leaderboard/inspect-mmlu_pro":
            return httpx.Response(200, json={"entries": []})
        return _board(request)

    with httpx.Client(base_url="http://board", transport=httpx.MockTransport(board)) as http:
        if missing:
            with pytest.raises(batch.BoardReadError, match="source"):
                batch.find_entries(http, ["inspect-mmlu_pro"])
        else:
            assert batch.find_entries(http, ["inspect-mmlu_pro"]) == []
