import pytest
from test_activity_logs import record

from screamingface._ui.activity_state import ActivityLog
from screamingface._ui.activity_view import activity_html


@pytest.mark.parametrize("stage", ["answering", "grading"])
def test_call_wording_updates_one_line_without_inventing_role(monkeypatch, stage):
    monkeypatch.setattr("screamingface._ui.activity_view.time.time", lambda: 100)
    log = ActivityLog()
    log.observe(0, record(id="stage", kind=stage, state="started"))
    for revision, state, wording in [
        (1, "started", "Calling provider/model"),
        (2, "retrying", "Retrying provider/model call"),
        (3, "completed", "Called provider/model"),
    ]:
        log.observe(
            0,
            record(
                revision,
                parent_id="stage",
                state=state,
                model_id="provider/model",
                observed_at_ms=100000 + revision * 1000,
                case_position=1,
                case_count=2,
            ),
        )
        html = activity_html(log, ("candidate",))
        assert f"[Case 1/2] {wording}" in html
        assert html.count('class="sf-activity__call"') == 1
        assert ">00:01:41</time>" in html
    assert 'aria-label="Completed"' in html


def test_failed_call_keeps_safe_failure_detail():
    log = ActivityLog()
    log.observe(0, record(state="failed", model_id="provider/model", failure_code="internal_error"))
    assert "provider/model call failed: internal error" in activity_html(log, ("candidate",))
