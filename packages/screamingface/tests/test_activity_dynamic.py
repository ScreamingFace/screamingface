from test_activity_logs import record

from screamingface._ui.activity_state import ActivityLog
from screamingface._ui.activity_view import activity_html
from screamingface._ui.activity_widget import CandidateActivityRow


def test_one_line_per_operation_keeps_first_seen_order(monkeypatch):
    monkeypatch.setattr("screamingface._ui.activity_view.time.time", lambda: 100)
    log = ActivityLog()
    log.observe(0, record(id="first", model_id="provider/one", state="started"))
    log.observe(0, record(id="second", model_id="provider/two", state="started"))
    log.observe(0, record(2, id="first", model_id="provider/one", state="completed"))
    html = activity_html(log, ("candidate",))
    assert html.count('class="sf-activity__call"') == 2
    assert html.index("provider/one") < html.index("provider/two")
    assert 'aria-label="Completed"' in html
    assert 'aria-label="Running"' in html
    assert len(log.history()) == 3


def test_hide_only_redundant_routine_answering_stages():
    log = ActivityLog()
    log.observe(0, record(id="stage", kind="answering", state="completed"))
    log.observe(0, record(id="model", parent_id="stage", model_id="model", state="completed"))
    log.observe(0, record(id="other", kind="answering", state="failed"))
    html = activity_html(log, ("candidate",))
    assert html.count('class="sf-activity__stage"') == 1
    assert "Answered with model" in html
    assert "failed" in html


def test_unknown_call_stops_spinning(monkeypatch):
    monkeypatch.setattr("screamingface._ui.activity_view.time.time", lambda: 10000)
    log = ActivityLog()
    log.observe(0, record(state="running"))
    html = activity_html(log, ("candidate",))
    assert 'aria-label="Status unknown"' in html
    assert 'class="sf-activity-spinner"' not in html
    assert "No recent update" in html


def test_pagination_counts_visible_operations_not_transitions():
    log = ActivityLog()
    for i in range(51):
        log.observe(0, record(id=str(i), state="started"))
        log.observe(0, record(2, id=str(i), state="completed"))
    panel = CandidateActivityRow(log, ("candidate",), 0)
    panel.toggle.value = True
    assert panel.page.max == 0
    assert panel.html.value.count('class="sf-activity__call"') == 51
    assert panel.html.layout.height == "280px"


def test_completed_loading_and_aggregation_have_concise_labels():
    log = ActivityLog()
    log.observe(0, record(id="load", kind="case_loading", state="completed", loaded_count=100))
    log.observe(0, record(id="aggregate", kind="aggregation", state="completed"))
    html = activity_html(log, ("candidate",))
    assert "Loaded 100 benchmark cases" in html
    assert "Scores aggregated" in html
    assert "Loading benchmark cases completed" not in html


def test_late_parent_uses_explicit_lineage_and_preserves_failed_stage():
    log = ActivityLog()
    log.observe(0, record(id="model", parent_id="stage", model_id="model", state="completed"))
    log.observe(
        0, record(id="stage", kind="answering", state="failed", failure_code="internal_error")
    )
    html = activity_html(log, ("candidate",))
    assert 'aria-label="Failed"' in html
    assert "Answered with model" in html
    assert html.count('class="sf-activity__stage"') == 1


def test_ended_call_is_unknown_and_never_gets_a_completion_check():
    log = ActivityLog()
    log.observe(0, record(state="started"))
    log.end(0)
    html = activity_html(log, ("candidate",))
    assert "Run ended; operation outcome not observed" in html
    assert 'aria-label="Status unknown"' in html
    assert 'aria-label="Completed"' not in html


def test_widget_and_value_are_unchanged_for_an_identical_refresh(monkeypatch):
    monkeypatch.setattr("screamingface._ui.activity_view.time.time", lambda: 100)
    log = ActivityLog()
    log.observe(0, record(state="running"))
    panel = CandidateActivityRow(log, ("candidate",), 0)
    panel.toggle.value = True
    root = panel.html
    updates = []
    panel.html.observe(lambda change: updates.append(change), names="value")
    panel._refresh_activity()
    assert updates == []
    log.observe(0, record(2, state="completed"))
    panel._refresh_activity()
    assert panel.html is root
    assert len(updates) == 1
    assert panel.html.value.count('class="sf-activity__call"') == 1
