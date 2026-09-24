from test_activity_logs import record

from screamingface._ui.activity_state import ActivityLog
from screamingface._ui.activity_view import activity_html
from screamingface._ui.activity_widget import CandidateActivityRow


def test_log_preserves_transitions_but_displays_latest_in_first_seen_order(monkeypatch):
    monkeypatch.setattr("screamingface._ui.activity_view.time.time", lambda: 100)
    log = ActivityLog()
    log.observe(0, record(id="a", kind="answering", case_id="007", state="started"))
    log.observe(0, record(id="b", kind="answering", case_id=42, state="started"))
    log.observe(0, record(2, id="b", kind="answering", case_id=42, state="completed"))
    log.observe(0, record(2, id="a", kind="answering", case_id="007", state="completed"))
    html = activity_html(log, ("candidate",))
    lines = [
        "Case 007: Answered",
        "Case 42: Answered",
    ]
    assert all(line in html for line in lines)
    assert [html.index(line) for line in lines] == sorted(html.index(line) for line in lines)
    assert len(log.rows(detailed=True)) == 2
    assert [r.record.state for r in log.history()] == [
        "started",
        "started",
        "completed",
        "completed",
    ]
    assert html.count('aria-label="Completed"') == 2


def test_resolved_historical_start_is_not_reported_as_unknown(monkeypatch):
    monkeypatch.setattr("screamingface._ui.activity_view.time.time", lambda: 10000)
    log = ActivityLog()
    log.observe(0, record(state="started", model_id="provider/model"))
    log.observe(0, record(2, state="completed", model_id="provider/model"))
    log.end(0)
    html = activity_html(log, ("candidate",))
    assert html.count("provider/model") == 1
    assert 'aria-label="Completed"' in html
    assert "outcome not observed" not in html


def test_timeline_pages_count_operations_while_retaining_events(monkeypatch):
    monkeypatch.setattr("screamingface._ui.activity_view.time.time", lambda: 100)
    log = ActivityLog()
    for i in range(101):
        log.observe(0, record(id=str(i), state="started"))
        log.observe(0, record(2, id=str(i), state="completed"))
    panel = CandidateActivityRow(log, ("candidate",), 0)
    panel.toggle.value = True
    assert panel.page.max == 1
    assert panel.html.value.count('class="sf-activity__call"') == 100
    panel.page.value = 1
    assert panel.html.value.count('class="sf-activity__call"') == 1
    assert len(log.history()) == 202


def test_history_remains_bounded_and_candidate_run_isolated():
    log = ActivityLog(limit=2)
    log.observe(0, record(state="started"))
    log.observe(1, record(state="started", run="other"))
    log.observe(0, record(2, state="completed"))
    assert len(log.history()) == 2
    assert [(r.candidate, r.run, r.record.state) for r in log.history()] == [
        (1, "other", "started"),
        (0, "run", "completed"),
    ]
    assert log.truncated == 1
