import pytest
from test_activity_logs import record

from screamingface._ui.activity_state import ActivityLog
from screamingface._ui.activity_view import activity_html


@pytest.mark.parametrize(
    ("kind", "state", "expected"),
    [
        ("answering", "started", "Answering"),
        ("answering", "completed", "Answered"),
        ("grading", "completed", "Grading complete"),
        ("aggregation", "completed", "Scores aggregated"),
        ("answering", "failed", "Answering failed"),
        ("grading", "failed", "Grading failed"),
    ],
)
def test_stage_wording_matches_outcome(kind, state, expected):
    log = ActivityLog()
    log.observe(0, record(kind=kind, state=state))
    assert expected in activity_html(log, ("candidate",))


def test_completed_model_call_inherits_past_tense_stage():
    log = ActivityLog()
    log.observe(0, record(id="stage", kind="answering", state="completed"))
    log.observe(0, record(parent_id="stage", state="completed", model_id="phi-4"))
    assert "Call completed: phi-4" in activity_html(log, ("candidate",))
