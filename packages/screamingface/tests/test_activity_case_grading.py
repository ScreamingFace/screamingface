from test_activity_logs import record

from screamingface._ui.activity_state import ActivityLog
from screamingface._ui.activity_view import activity_html


def test_case_grading_reuses_explicit_number_and_updates_one_line():
    log = ActivityLog()
    log.observe(
        0,
        record(
            id="answer",
            kind="answering",
            state="completed",
            case_id=42,
            case_position=2,
            case_count=5,
        ),
    )
    log.observe(0, record(id="internal", kind="grading", state="completed"))
    log.observe(0, record(id="phase", kind="grading", scope="case", case_id="42", state="started"))
    assert "[Case 2/5] Grading" in activity_html(log, ("candidate",))
    log.observe(
        0, record(2, id="phase", kind="grading", scope="case", case_id="42", state="completed")
    )
    log.observe(0, record(id="phase", kind="grading", scope="case", case_id="42", state="started"))
    html = activity_html(log, ("candidate",))
    assert html.count("[Case 2/5] Grading complete") == 1
    assert ">Grading complete<" not in html
    assert len(log.history()) == 4


def test_case_grading_does_not_borrow_number_from_other_candidate_or_id():
    log = ActivityLog()
    log.observe(0, record(id="a", kind="answering", case_id="007", case_position=1, case_count=5))
    log.observe(1, record(id="a", kind="answering", case_id=7, case_position=2, case_count=5))
    log.observe(0, record(id="p", kind="grading", scope="case", case_id=7, state="failed"))
    html = activity_html(log, ("one", "two"))
    assert "Case 7: Grading failed" in html
    assert "[Case 2/5]" not in html


def test_phase_numbering_is_run_local_and_missing_start_still_finishes():
    log = ActivityLog()
    log.observe(
        0, record(run="old", id="a", kind="answering", case_id=42, case_position=2, case_count=5)
    )
    log.observe(
        0, record(2, run="new", id="p", kind="grading", scope="case", case_id=42, state="completed")
    )
    html = activity_html(log, ("candidate",))
    assert "Case 42: Grading complete" in html
    assert "[Case 2/5] Grading complete" not in html


def test_phase_summary_keeps_endpoint_failures_and_model_calls():
    log = ActivityLog()
    log.observe(0, record(id="p", kind="grading", scope="case", case_id=42, state="started"))
    log.observe(0, record(id="error", kind="grading", state="failed"))
    log.observe(
        0, record(id="call", kind="model_call", model_id="provider/judge", state="completed")
    )
    html = activity_html(log, ("candidate",))
    assert "Grading failed" in html
    assert "provider/judge" in html
