"""Child lifecycle facts must not finish a candidate or reset its timer."""

import json

import pytest
from test_engine_contract import frame
from test_live_candidate_progress import candidate

from screamingface._engine.contract import _RunState
from screamingface._ui.evaluation_state import _EvaluationProgress


@pytest.mark.parametrize("early_child", [False, True])
@pytest.mark.parametrize("child_same_expression", [False, True])
def test_decoded_child_lifecycle_does_not_finish_candidate(early_child, child_same_expression):
    item = candidate("opus")
    decoder = _RunState(item.url4)
    progress = _EvaluationProgress(candidates=(item,), case_count=2)
    sequence = 0

    def accept(kind, data, source="/root", elapsed=1.0):
        nonlocal sequence
        sequence += 1
        accepted = decoder.accept(
            json.dumps(
                {
                    **json.loads(frame(kind, data, sequence=sequence, source=source)),
                    "time": f"2026-07-25T16:00:{sequence:02d}Z",
                }
            )
        )
        if accepted.event is not None:
            progress.observe(item, accepted.event, elapsed_seconds=elapsed)
        return accepted

    if early_child:
        accept("ai.url4.started", {"url4": "()!'early child'"}, "/early")
        accept("ai.url4.terminated", {"status": "succeeded", "error": None}, "/early")
        assert progress.rows[0].status == "running"
        assert progress.rows[0].root_identity is None
    accept("ai.url4.started", {"url4": item.url4}, elapsed=2.0)
    accept(
        "ai.url4.started",
        {"url4": item.url4 if child_same_expression else "()!'child'"},
        "/child",
        elapsed=9.0,
    )
    child = accept("ai.url4.terminated", {"status": "succeeded", "error": None}, "/child")
    row = progress.rows[0]
    assert child.outcome is None
    assert (row.result, row.status, row.terminal_duration_seconds, row.started_elapsed_seconds) == (
        None,
        "running",
        None,
        2.0,
    )

    accept("ai.url4.result", {"body": "{}", "media_type": "application/json"})
    root = accept("ai.url4.terminated", {"status": "succeeded", "error": None})
    assert root.outcome is not None
    assert row.status == "finished"
    assert row.terminal_duration_seconds == 4.0
