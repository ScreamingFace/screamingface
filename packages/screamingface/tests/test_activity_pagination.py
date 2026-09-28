from test_activity_logs import record

from screamingface._ui.activity_state import ActivityLog
from screamingface._ui.activity_widget import CandidateActivityRow


def test_all_retained_logs_share_one_scroll_panel_without_pagination():
    log = ActivityLog()
    for i in range(201):
        log.observe(0, record(id=str(i), state="completed"))
    panel = CandidateActivityRow(log, ("candidate",), 0)
    panel.toggle.value = True
    assert panel.details.children == (panel.html,)
    assert panel.html.value.count('class="sf-activity__call"') == 201
    assert "Copy" in panel.html.value
    assert panel.html.layout.overflow == "auto"
    assert not hasattr(panel, "page")
