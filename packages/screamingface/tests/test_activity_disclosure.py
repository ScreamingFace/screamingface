from test_activity_logs import record

from screamingface._ui.activity_state import ActivityLog
from screamingface._ui.activity_widget import CandidateActivityRow


def test_disclosure_covers_summary_but_not_log_interaction():
    log = ActivityLog()
    log.observe(0, record(state="completed"))
    panel = CandidateActivityRow(log, ("one", "two"), 0)
    other = CandidateActivityRow(log, ("one", "two"), 1)
    summary, details = panel.widget.children
    assert panel.toggle in summary.children
    assert panel.summary in summary.children
    assert panel.toggle.layout.width == "100%"
    assert panel.toggle.layout.height == "100%"
    assert panel.html in details.children
    panel.toggle.value = True
    assert panel.details.layout.display == ""
    assert other.details.layout.display == "none"
    panel._refresh_activity()
    assert panel.toggle.value
    assert "Hide activity for one" == panel.toggle.tooltip
