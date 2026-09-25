from test_activity_logs import record

from screamingface._ui.activity_state import ActivityLog
from screamingface._ui.activity_widget import CandidateActivityRow


def test_inline_pagination_moves_between_pages_and_disables_boundaries():
    log = ActivityLog()
    for i in range(201):
        log.observe(0, record(id=str(i), state="completed"))
    panel = CandidateActivityRow(log, ("candidate",), 0)
    panel.toggle.value = True
    assert panel.page not in panel.details.children
    assert panel.newer.disabled
    assert not panel.older.disabled
    panel.older.click()
    assert panel.page.value == 1
    panel.older.click()
    assert panel.page.value == 2
    assert panel.older.disabled
    assert panel.html.value.count('class="sf-activity__call"') == 1
    panel.newer.click()
    assert panel.page.value == 1
    assert panel.pagination in panel.details.children


def test_single_page_has_no_pagination_controls():
    panel = CandidateActivityRow(ActivityLog(), ("candidate",), 0)
    panel.toggle.value = True
    assert panel.pagination.layout.display == "none"
