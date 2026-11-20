"""The batch re-grade script: which entries it finds, and that a second run posts nothing twice.

FEATURE: OME-1958 — after a Benchmark's revision moves, `scripts/regrade_batch.py` re-grades every
row its board still shows at an older revision. These tests fake the Scoreboard's public reads
(`httpx.MockTransport`) and the SDK call (`_FakeRegrader`), so no network and no model runs.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any
from uuid import UUID

import httpx
import pytest

from screamingface.errors import ExecutionError, LeaderboardError, PlanningError

_SCRIPT: Path = Path(__file__).resolve().parents[2] / "scripts" / "regrade_batch.py"
_OLD: str = "145edec84bfc2324"
_NEW: str = "4efebd6cc74c2dca"
_EXISTING: str = "3c9a0000-0000-4000-8000-000000000000"


def _load() -> ModuleType:
    """Import the script by path: `scripts/` is not a package."""

    sys.path.insert(0, str(_SCRIPT.parent))
    spec = importlib.util.spec_from_file_location("regrade_batch", _SCRIPT)
    assert spec is not None and spec.loader is not None
    module: ModuleType = importlib.util.module_from_spec(spec)
    sys.modules["regrade_batch"] = module
    spec.loader.exec_module(module)
    return module


batch: ModuleType = _load()


def _board(request: httpx.Request) -> httpx.Response:
    """A Scoreboard with one public board that moved, one private board, one untouched board."""

    path: str = request.url.path
    routes: dict[str, Any] = {
        "/v1/benchmarks": {
            "benchmarks": [
                {"id": "inspect-mmlu_pro", "revision": _NEW, "visibility": "public"},
                {"id": "private-board", "revision": "p2", "visibility": "private"},
                {"id": "inspect-gsm8k", "revision": "g1", "visibility": "public"},
            ]
        },
        "/v1/leaderboard/inspect-mmlu_pro/revisions": {
            "revisions": [
                {"revision": _NEW, "result_count": 0},
                {"revision": _OLD, "result_count": 2},
                {"revision": "empty-old", "result_count": 0},
            ]
        },
        "/v1/leaderboard/inspect-gsm8k/revisions": {
            "revisions": [{"revision": "g1", "result_count": 5}]
        },
        "/v1/public/scores/by-pinned-cache/copy-a": {"score_id": "a" * 8},
    }
    # WHY assert: a private board is never read; the Scoreboard never re-grades a private score.
    assert "private-board" not in path
    if path == "/v1/leaderboard/inspect-mmlu_pro":
        # WHY assert here: only an older revision with results may be read, never the current.
        assert request.url.params["revision"] == _OLD
        return httpx.Response(
            200,
            json={
                "entries": [
                    {"spec_id": "spec-cached", "pinned_cache": "copy-a"},
                    {"spec_id": "spec-uncached"},
                ]
            },
        )
    return httpx.Response(200, json=routes[path])


def test_finds_every_old_row_of_a_public_board_and_marks_the_one_with_no_pinned_cache() -> None:
    # WHY: the 8 uncached entries on 2026-11-17 need an owner decision, so they must appear in the
    # list, not vanish; the private board and the board that never moved add nothing.
    with httpx.Client(base_url="http://board", transport=httpx.MockTransport(_board)) as http:
        entries: list[Any] = batch.find_entries(http, ["inspect-mmlu_pro"])

    assert entries == [
        batch.Entry("inspect-mmlu_pro", _OLD, "spec-cached", "copy-a", "a" * 8),
        batch.Entry("inspect-mmlu_pro", _OLD, "spec-uncached", None, None),
    ]


@pytest.mark.parametrize("status", [404, 503])
def test_a_failed_board_read_stops_the_run_instead_of_returning_a_short_list(status: int) -> None:
    # WHY: a short list would leave entries off the Latest board with nobody noticing. 404 is a
    # Scoreboard deployed before the revisions route (OME-1708): it must not read as "0 entries".
    def broken(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status) if "revisions" in request.url.path else _board(request)

    with httpx.Client(base_url="http://board", transport=httpx.MockTransport(broken)) as http:
        with pytest.raises(batch.BoardReadError):
            batch.find_entries(http, ["inspect-mmlu_pro"])


class _FakeRegrader:
    """Stands in for `sf.Client`: answers each score id with a new entry or the error given."""

    def __init__(self, answers: dict[str, Exception | None]) -> None:
        self.answers: dict[str, Exception | None] = answers
        self.calls: list[str] = []
        self.leaderboards = SimpleNamespace(_public_score=self._public_score)

    def regrade(self, score_id: str, *, expected_target_revision: str) -> Any:
        """Record the call, then raise the planned error or return a new entry."""

        assert expected_target_revision == _NEW
        self.calls.append(score_id)
        error: Exception | None = self.answers[score_id]
        if error is not None:
            raise error
        return SimpleNamespace(
            id=f"new-{score_id}",
            benchmark_id="inspect-mmlu_pro",
            benchmark_revision=_NEW,
            regraded_from=score_id,
        )

    def _public_score(self, existing_id: UUID) -> Any:
        for source_id, error in self.answers.items():
            if isinstance(error, LeaderboardError) and error.existing_score_id == existing_id:
                return SimpleNamespace(
                    score_id=existing_id,
                    benchmark_id="inspect-mmlu_pro",
                    benchmark_revision=_NEW,
                    regraded_from=source_id,
                )
        raise AssertionError("unexpected existing-score read")


def _entry(score_id: str | None, spec: str) -> Any:
    """One old row of `inspect-mmlu_pro`."""

    return batch.Entry("inspect-mmlu_pro", _OLD, spec, "copy" if score_id else None, score_id)


def _lines(log: Path) -> list[dict[str, Any]]:
    """The log, one dict per line."""

    return [json.loads(line) for line in log.read_text().splitlines()]


def test_each_outcome_is_logged_and_a_second_run_retries_only_the_retryable_one(
    tmp_path: Path,
) -> None:
    # INVARIANT: a re-run after a crash never posts a settled entry twice; the board would refuse
    # it anyway (one re-grade per source per revision), but the log must say so without asking.
    regrader = _FakeRegrader(
        {
            "moved": None,
            "repeat": LeaderboardError(
                "already", code="already_regraded", existing_score_id=UUID(_EXISTING)
            ),
            "cases-changed": PlanningError("no", code="not_regradable", permanent=True),
            "judge-outage": ExecutionError("retry", code="regrade_incomplete", permanent=False),
        }
    )
    entries: list[Any] = [
        _entry("moved", "s1"),
        _entry("repeat", "s2"),
        _entry("cases-changed", "s3"),
        _entry("judge-outage", "s4"),
        _entry(None, "s5"),
    ]
    log: Path = tmp_path / "log.jsonl"

    first: dict[str, int] = batch.regrade_all(regrader, entries, log)

    assert first == {
        "regraded": 1,
        "already_regraded": 1,
        "refused_permanently": 1,
        "refused_retryable": 1,
        "no_pinned_cache": 1,
        "unresolved": 3,
    }
    by_source: dict[object, dict[str, Any]] = {r["source_score_id"]: r for r in _lines(log)}
    assert by_source["moved"]["new_score_id"] == "new-moved"
    assert by_source["repeat"]["new_score_id"] == _EXISTING
    assert by_source["cases-changed"]["code"] == "not_regradable"
    assert by_source[None]["spec_id"] == "s5"

    regrader.calls.clear()
    second: dict[str, int] = batch.regrade_all(regrader, entries, log)

    assert regrader.calls == ["judge-outage"]
    assert second["skipped"] == 4
    assert second["unresolved"] == 3


def test_an_engine_still_on_the_old_revision_is_retried_on_the_next_run(tmp_path: Path) -> None:
    # WHY: the board lists the entry as old, so `already_current` from the Engine means a pod not
    # yet updated in a rolling deploy. Settling it would skip the entry on every scheduled run.
    regrader = _FakeRegrader(
        {"stale-pod": PlanningError("current", code="already_current", permanent=True)}
    )
    log: Path = tmp_path / "log.jsonl"

    first: dict[str, int] = batch.regrade_all(regrader, [_entry("stale-pod", "s1")], log)
    regrader.answers["stale-pod"] = None
    second: dict[str, int] = batch.regrade_all(regrader, [_entry("stale-pod", "s1")], log)

    assert first == {"refused_retryable": 1, "unresolved": 1}
    assert second == {"regraded": 1, "unresolved": 0}


def test_the_start_guard_reads_the_revision_a_board_serves_now() -> None:
    # WHY: a scheduled run must wait until the bump is deployed, read live from the board list.
    with httpx.Client(base_url="http://board", transport=httpx.MockTransport(_board)) as http:
        assert batch.board_revision(http, "inspect-mmlu_pro") == _NEW
        with pytest.raises(batch.BoardReadError):
            batch.board_revision(http, "no-such-board")
