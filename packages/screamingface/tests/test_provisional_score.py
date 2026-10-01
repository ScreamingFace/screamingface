from datetime import UTC, datetime
from types import SimpleNamespace
from typing import cast

import pytest
from test_client_protocol import _candidate

from screamingface._ui.evaluation_state import _CandidateProgress
from screamingface.events import Log
from screamingface.report import CandidateResult


def snapshot(revision=1, score: float | None = 0.0, completed=1, graded=1):
    return Log(
        id=str(revision),
        run_id="run",
        sequence=revision,
        timestamp=datetime.now(UTC),
        source="case",
        severity_number=9,
        severity_text="INFO",
        body="Benchmark progress",
        attributes={
            "sf.progress.schema": "screamingface.benchmark-progress.v1",
            "sf.progress.benchmark": "ifeval",
            "sf.progress.benchmark_revision": "v3",
            "sf.progress.revision": revision,
            "sf.progress.completed": completed,
            "sf.progress.graded": graded,
            "sf.progress.score": score,
        },
    )


def test_partial_zero_is_visible_and_final_result_wins():
    row = _CandidateProgress(_candidate(), 5)
    row.observe(snapshot())
    assert row.score_available
    assert row.score == 0.0
    assert row.qualifier is None
    row.result = cast(CandidateResult, SimpleNamespace(score=0.7, coverage=1.0, failures=()))
    row.observe(snapshot(2, 1.0, 2, 2))
    assert row.score == 0.7
    assert row.qualifier is None


def test_missing_and_old_snapshots_do_not_regress_score():
    row = _CandidateProgress(_candidate(), 5)
    row.observe(snapshot(3, 0.5, 3, 2))
    row.observe(snapshot(1, 1.0))
    assert row.score == 0.5
    assert row.qualifier is None


@pytest.mark.parametrize(
    "score,completed,graded",
    [
        (float("nan"), 1, 1),
        (float("inf"), 1, 1),
        (True, 1, 1),
        (1.0, 6, 1),
        (1.0, 1, 2),
        (1.0, True, 1),
    ],
)
def test_invalid_snapshots_are_ignored(score, completed, graded):
    row = _CandidateProgress(_candidate(), 5)
    row.observe(snapshot(score=score, completed=completed, graded=graded))
    assert not row.score_available


def test_no_gradeable_cases_does_not_invent_zero():
    row = _CandidateProgress(_candidate(), 5)
    row.observe(snapshot(score=None, graded=0))
    assert row.score is None


def test_notebook_score_cell_updates_before_final_result(monkeypatch):
    from screamingface._ui.evaluation_widget import _NotebookEvaluationView

    monkeypatch.setattr(_NotebookEvaluationView, "_show", lambda self: None)
    candidate = _candidate()
    view = _NotebookEvaluationView(
        candidates=(candidate,), benchmark="ifeval", case_count=5, tick=False
    )
    view.observe(candidate, snapshot(score=0.4))
    html = view._activity_rows[0].summary.value
    assert "0.4" in html
    assert "Provisional" not in html
    assert "graded" not in html
    assert "Not scored yet" not in html


def test_candidates_keep_independent_scores():
    first, second = _CandidateProgress(_candidate(), 5), _CandidateProgress(_candidate(), 5)
    first.observe(snapshot(score=0.5))
    assert first.score == 0.5
    assert not second.score_available


def test_wrong_identity_and_regressing_counts_do_not_replace_snapshot():
    from dataclasses import replace

    from screamingface._ui.provisional_score import advance, parse_snapshot

    initial = parse_snapshot(snapshot(3, 0.5, 3, 2), 5)
    assert initial is not None
    assert (
        advance(initial, replace(initial, identity=("other", "ifeval", "v3"), revision=4))
        == initial
    )
    assert advance(initial, replace(initial, completed=2, revision=4)) == initial
