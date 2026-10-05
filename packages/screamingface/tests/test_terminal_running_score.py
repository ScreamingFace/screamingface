"""Running scores are never presented as final after a missing-result terminal."""

import pytest
from test_client_protocol import _candidate
from test_provisional_score import snapshot

from screamingface._ui.evaluation_state import _EvaluationProgress
from screamingface.events import Log


@pytest.mark.parametrize("terminal", ["failed", "timed_out", "stopped", "succeeded"])
def test_terminal_without_result_does_not_retain_numeric_score(terminal):
    candidate = _candidate()
    state = _EvaluationProgress(candidates=(candidate,), case_count=5)
    state.observe(candidate, snapshot(score=0.9))
    row = state.rows[0]
    row.terminal_status = terminal
    assert row.score is None
    assert not row.score_available


@pytest.mark.parametrize("exc", [KeyboardInterrupt(), TimeoutError(), ValueError("decode failed")])
def test_abort_after_success_without_result_is_not_finished(exc):
    candidate = _candidate()
    state = _EvaluationProgress(candidates=(candidate,), case_count=5)
    state.begin(candidate)
    state.observe(candidate, snapshot(score=0.9))
    row = state.rows[0]
    row.started = True
    row.terminal_status = "succeeded"
    state.abort(exc)
    assert row.status != "finished"
    assert row.score is None
    assert not row.score_available


def test_ungraded_running_snapshot_is_still_waiting_for_score():
    candidate = _candidate()
    state = _EvaluationProgress(candidates=(candidate,), case_count=5)
    state.observe(candidate, snapshot(score=None, graded=0))
    assert not state.rows[0].score_available


@pytest.mark.parametrize("revision,score,graded", [(0, 0.5, 1), (1, 0.5, 0)])
def test_invalid_snapshot_cannot_supply_score(revision, score, graded):
    candidate = _candidate()
    state = _EvaluationProgress(candidates=(candidate,), case_count=5)
    event = snapshot(score=score, graded=graded)
    attributes = dict(event.attributes)
    attributes["sf.progress.revision"] = revision
    state.observe(
        candidate,
        Log(
            id=event.id,
            run_id=event.run_id,
            sequence=event.sequence,
            timestamp=event.timestamp,
            source=event.source,
            severity_number=9,
            severity_text="INFO",
            body=event.body,
            attributes=attributes,
        ),
    )
    assert state.rows[0].provisional is None
