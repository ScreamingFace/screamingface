import pytest
from test_activity_logs import record

from screamingface._ui.activity_state import ActivityLog
from screamingface._ui.activity_view import activity_html


def test_positions_are_explicit_and_independent_of_arrival_and_candidate(monkeypatch):
    monkeypatch.setattr("screamingface._ui.activity_view.time.time", lambda: 100)
    log = ActivityLog()
    for candidate in range(10):
        log.observe(candidate, record(id="second", case_id="007", case_position=2, case_count=100))
        log.observe(candidate, record(id="first", case_id=42, case_position=1, case_count=100))
    for candidate in range(10):
        html = activity_html(log, tuple(str(i) for i in range(10)), candidate=candidate)
        assert "[Case 2/100]" in html
        assert "[Case 1/100]" in html
        assert html.index("[Case 2/100]") < html.index("[Case 1/100]")
        assert "Case 42:" not in html
    assert log.invalid == 0


@pytest.mark.parametrize(
    "facts",
    [
        {"case_position": 0, "case_count": 100},
        {"case_position": 101, "case_count": 100},
        {"case_position": True, "case_count": 100},
        {"case_position": 1},
        {"case_count": 100},
        {"case_position": "1", "case_count": 100},
    ],
)
def test_invalid_case_position_pairs_are_not_displayed(facts):
    log = ActivityLog()
    log.observe(0, record(**facts))
    assert log.invalid == 1
    assert "[Case" not in activity_html(log, ("candidate",))
