import ipywidgets as widgets
from test_activity_logs import record
from test_live_candidate_progress import candidate

from screamingface._ui.activity_state import ActivityLog
from screamingface._ui.activity_widget import CandidateActivityRow


def test_row_expansion_shows_all_calls_without_discarding_events():
    log = ActivityLog()
    log.observe(0, record(state="completed", elapsed_ms=20))
    panel = CandidateActivityRow(log, ("candidate",), 0)
    assert isinstance(panel.widget, widgets.VBox)
    assert panel.details.layout.display == "none"
    panel.toggle.value = True
    assert "Model call" in panel.html.value
    assert log.retained == 1
    assert panel.html.tabbable
    assert panel.details.layout.display == ""
    panel.toggle.value = False
    assert panel.details.layout.display == "none"


def test_pages_bound_rendering_and_expansion_controls_stay_stable():
    log = ActivityLog()
    for i in range(201):
        log.observe(0, record(id=str(i), state="completed"))
    panel = CandidateActivityRow(log, ("candidate",), 0)
    root = panel.html
    panel.toggle.value = True
    assert panel.html.value.count('class="sf-activity__call"') == 100
    panel.page.value = 2
    assert panel.html.value.count('class="sf-activity__call"') == 1
    panel._refresh_activity()
    assert panel.html is root
    assert panel.toggle.value


def test_evaluation_host_delivers_activity_under_its_row_before_report(monkeypatch):
    from screamingface._ui.evaluation_widget import _NotebookEvaluationView

    monkeypatch.setattr(_NotebookEvaluationView, "_show", lambda self: None)
    selected = candidate("one")
    view = _NotebookEvaluationView((selected,), 1, tick=False)
    view.observe(selected, record(kind="grading", state="completed"))
    assert not hasattr(view, "_tabs")
    view._activity_rows[0].toggle.value = True
    assert "Graded" in view._activity_rows[0].html.value
    assert not view._progress.complete
    view.close()


def test_widget_keeps_processing_updates_beyond_six_hours(monkeypatch):
    from test_live_candidate_progress import candidate

    from screamingface._ui.evaluation_widget import _NotebookEvaluationView

    monkeypatch.setattr(_NotebookEvaluationView, "_show", lambda self: None)
    now = [0.0]
    view = _NotebookEvaluationView((candidate("one"),), 1, tick=False, clock=lambda: now[0])
    now[0] = 3 * 24 * 60 * 60
    refreshed = []

    def refresh():
        refreshed.append(True)
        view._done.set()

    monkeypatch.setattr(view, "_refresh", refresh)
    view._dirty.set()
    view._tick_loop()
    assert refreshed == [True]


def test_expanded_activity_is_flat_log_output_not_a_table():
    log = ActivityLog()
    log.observe(0, record(kind="answering", id="stage", state="completed"))
    log.observe(0, record(parent_id="stage", model_id="provider/model", state="completed"))
    panel = CandidateActivityRow(log, ("candidate",), 0)
    panel.toggle.value = True
    html = panel.html.value
    assert "<table" not in html
    assert "<th" not in html
    assert 'class="sf-activity__call"' in html
    assert "Completed provider/model call" in html
    assert "provider/model" in html
    assert "completed" in html


def test_activity_has_contained_scroll_box_and_no_report_headings():
    log = ActivityLog()
    log.observe(0, record(kind="grading", state="completed"))
    panel = CandidateActivityRow(log, ("candidate",), 0)
    panel.toggle.value = True
    assert 'class="sf-activity-console"' in panel.html.value
    assert "height:280px" in panel.html.value
    assert panel.html.layout.overflow == "auto"
    assert panel.html.layout.height == "280px"
    assert "<h4" not in panel.html.value
    assert "<small" not in panel.html.value


def test_flat_model_lines_identify_case_stage_and_model_without_routine_noise():
    from screamingface._ui.activity_view import activity_html

    log = ActivityLog()
    log.observe(0, record(kind="answering", id="stage", state="completed"))
    for case_id, model in [(42, "provider/one"), ("007", "provider/two")]:
        log.observe(
            0,
            record(
                id=model,
                parent_id="stage",
                model_id=model,
                case_id=case_id,
                state="completed",
                finish_reason="stop",
            ),
        )
    html = activity_html(log, ("candidate",))
    assert "Case 42: Completed provider/one call" in html
    assert "Case 007: Completed provider/two call" in html
    assert "finish reason" not in html
    assert "Measured" not in html
    assert "60s" not in html
    assert "padding:0 0 0 16px" not in html
    assert " — " not in html and " · " not in html


def test_missing_case_is_not_inferred_from_sibling_and_failures_remain_visible():
    from screamingface._ui.activity_view import activity_html

    log = ActivityLog()
    log.observe(0, record(kind="grading", id="stage", state="completed"))
    log.observe(
        0,
        record(
            id="known", parent_id="stage", model_id="provider/one", case_id="007", state="completed"
        ),
    )
    log.observe(
        0,
        record(
            id="unknown",
            parent_id="stage",
            model_id="provider/two",
            state="failed",
            failure_code="provider_timeout",
        ),
    )
    html = activity_html(log, ("candidate",))
    assert "Case not identified: provider/two call failed: provider timeout" in html
    assert "Case 007: provider/two call" not in html


def test_retry_attempt_and_nonroutine_finish_reason_are_explained(monkeypatch):
    from screamingface._ui.activity_view import activity_html

    monkeypatch.setattr("screamingface._ui.activity_view.time.time", lambda: 100)
    log = ActivityLog()
    log.observe(
        0, record(id="retry", model_id="provider/one", case_id=42, state="retrying", attempt=2)
    )
    log.observe(
        0,
        record(
            id="limited",
            model_id="provider/two",
            case_id=43,
            state="completed",
            finish_reason="length",
        ),
    )
    html = activity_html(log, ("candidate",))
    assert "Retrying provider/one call: attempt 2" in html
    assert "token limit reached" in html
    assert 'aria-label="Completed"' in html
