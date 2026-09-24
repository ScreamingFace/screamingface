from test_activity_logs import record

from screamingface._ui.activity_state import ActivityLog
from screamingface._ui.activity_view import activity_html


def test_operation_timestamp_stays_fixed_as_state_updates():
    log = ActivityLog()
    log.observe(0, record(observed_at_ms=3600000))
    log.observe(0, record(2, state="completed", observed_at_ms=3615000))
    html = activity_html(log, ("candidate",))
    assert ">01:00:00</time>" in html
    assert 'title="First observed: 1970-01-01 01:00:00 UTC"' in html
    assert "01:00:15" not in html


def test_timestamp_index_is_evicted_with_operation():
    log = ActivityLog(limit=1)
    log.observe(0, record(id="old", state="completed", observed_at_ms=3600000))
    log.observe(0, record(id="new", state="completed", observed_at_ms=7200000))
    assert len(log._first_observed) == 1
    assert ">02:00:00</time>" in activity_html(log, ("candidate",))


def test_unrepresentable_timestamp_does_not_break_rendering():
    log = ActivityLog()
    log.observe(0, record(observed_at_ms=9007199254740991))
    assert "Time unavailable" in activity_html(log, ("candidate",))
