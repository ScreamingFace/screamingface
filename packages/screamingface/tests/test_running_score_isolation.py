"""Interleaved real evaluation rows retain their own score and terminal state."""

from test_client_protocol import _candidate
from test_provisional_score import snapshot

from screamingface._evaluation.model import _compiled_candidate
from screamingface._ui.evaluation_state import _EvaluationProgress


def test_interleaved_candidates_in_one_evaluation_keep_independent_scores():
    first = _candidate()
    second = _compiled_candidate(
        name="second",
        kind="model",
        models=("provider/second",),
        url4="(@)!'second'",
        operations=first.operations,
    )
    state = _EvaluationProgress(candidates=(first, second), case_count=5)
    state.begin(first)
    state.begin(second)
    state.observe(first, snapshot(1, 0.5))
    assert state.rows[0].score == 0.5
    assert state.rows[1].score is None
    state.observe(second, snapshot(1, 0.9))
    state.observe(first, snapshot(2, 0.6, 2, 2))
    assert [r.score for r in state.rows] == [0.6, 0.9]
    state.rows[0].terminal_status = "failed"
    state.observe(second, snapshot(2, 0.8, 2, 2))
    assert [r.score for r in state.rows] == [None, 0.8]
