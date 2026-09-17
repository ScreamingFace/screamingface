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
    assert panel.html.value.count("<tr>") == 101
    panel.page.value = 2
    assert panel.html.value.count("<tr>") == 2
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
    assert "Grading" in view._activity_rows[0].html.value
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
