"""Imported recording and judge facts render without inferring roles from stage order."""

from test_activity_logs import record

from screamingface._ui.activity_state import ActivityLog
from screamingface._ui.activity_view import activity_html


def test_recording_and_judge_calls_use_existing_case_identity(monkeypatch):
    monkeypatch.setattr("screamingface._ui.activity_view.time.time", lambda: 100)
    log = ActivityLog()
    log.observe(0, record(id="answer", case_id=42, case_position=1, case_count=2))
    log.observe(
        0, record(id="saved", kind="answering", state="completed", case_id="42", action="recording")
    )
    log.observe(
        0,
        record(id="judge", case_id=42, role="judge", state="completed", model_id="provider/judge"),
    )
    html = activity_html(log, ("candidate",))
    assert "Answer recorded" not in html
    assert "[Case 1/2] Called judge provider/judge" in html
    assert "Graded" not in html
    assert log.invalid == 0


def test_judge_cannot_borrow_another_candidates_case_number():
    log = ActivityLog()
    log.observe(0, record(id="answer", case_id=42, case_position=1, case_count=2))
    log.observe(
        1,
        record(id="judge", case_id=42, role="judge", state="completed", model_id="provider/judge"),
    )
    html = activity_html(log, ("first", "second"), candidate=1)
    assert "[Case 1/2]" not in html
    assert "Case 42:" in html


def test_unknown_role_and_action_cannot_render_private_text():
    log = ActivityLog()
    log.observe(0, record(id="bad-role", role="PRIVATE PROMPT"))
    log.observe(0, record(id="bad-action", action="PRIVATE PROMPT"))
    assert log.invalid == 2
    assert "PRIVATE PROMPT" not in activity_html(log, ("candidate",))
