from test_activity_logs import record

from screamingface._ui.activity_state import ActivityLog
from screamingface._ui.activity_view import activity_html
from screamingface._ui.activity_widget import CandidateActivityRow


def test_log_preserves_interleaved_transitions_in_received_order(monkeypatch):
    monkeypatch.setattr("screamingface._ui.activity_view.time.time", lambda: 100)
    log = ActivityLog()
    log.observe(0, record(id="a", kind="answering", case_id="007", state="started"))
    log.observe(0, record(id="b", kind="answering", case_id=42, state="started"))
    log.observe(0, record(2, id="b", kind="answering", case_id=42, state="completed"))
    log.observe(0, record(2, id="a", kind="answering", case_id="007", state="completed"))
    html = activity_html(log, ("candidate",))
    lines = [
        "Case 007: Answering started",
        "Case 42: Answering started",
        "Case 42: Answering completed",
        "Case 007: Answering completed",
    ]
    assert all(line in html for line in lines)
    assert [html.index(line) for line in lines] == sorted(html.index(line) for line in lines)
    assert len(log.rows(detailed=True)) == 2


def test_resolved_historical_start_is_not_reported_as_unknown(monkeypatch):
    monkeypatch.setattr("screamingface._ui.activity_view.time.time", lambda: 10000)
    log = ActivityLog()
    log.observe(0, record(state="started", model_id="provider/model"))
    log.observe(0, record(2, state="completed", model_id="provider/model"))
    log.end(0)
    html = activity_html(log, ("candidate",))
    assert "provider/model started" in html
    assert "provider/model completed" in html
    assert "outcome not observed" not in html


def test_timeline_pages_count_events_not_operations(monkeypatch):
    monkeypatch.setattr("screamingface._ui.activity_view.time.time", lambda: 100)
    log = ActivityLog()
    for i in range(51):
        log.observe(0, record(id=str(i), state="started"))
        log.observe(0, record(2, id=str(i), state="completed"))
    panel = CandidateActivityRow(log, ("candidate",), 0)
    panel.toggle.value = True
    assert panel.page.max == 1
    assert panel.html.value.count('class="sf-activity__call"') == 100
    panel.page.value = 1
    assert panel.html.value.count('class="sf-activity__call"') == 2


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
