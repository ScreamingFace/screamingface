from html.parser import HTMLParser

from test_activity_logs import record

from screamingface._ui.activity_state import ActivityLog
from screamingface._ui.activity_view import activity_html


class ActivityMarkup(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.buttons = []
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        if tag == "button":
            self.buttons.append(dict(attrs))


def test_copy_control_is_accessible_and_scoped_to_displayed_candidate():
    log = ActivityLog()
    log.observe(0, record(state="completed", model_id="provider/visible"))
    log.observe(1, record(state="completed", model_id="provider/other"))
    html = activity_html(log, ("one", "two"))
    buttons = ActivityMarkup(html).buttons
    assert len(buttons) == 1
    assert buttons[0]["type"] == "button"
    assert buttons[0]["aria-label"] == "Copy displayed logs"
    assert "provider/visible" in html
    assert "provider/other" not in html
    assert "SECRET PROMPT" not in html
    assert "sf-activity-content" in html


def test_empty_activity_still_has_copy_and_honest_empty_message():
    html = activity_html(ActivityLog(), ("candidate",), finished=True)
    assert len(ActivityMarkup(html).buttons) == 1
    assert "No structured activity received for this run." in html
