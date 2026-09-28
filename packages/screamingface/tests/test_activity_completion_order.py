from test_activity_logs import record

from screamingface._ui.activity_state import ActivityLog
from screamingface._ui.activity_view import activity_html


def test_nested_judging_precedes_completion_summaries():
    log = ActivityLog()
    log.observe(0, record(id="aggregate", kind="aggregation", observed_at_ms=1000))
    log.observe(0, record(id="grade", kind="grading", scope="case", case_id=1, observed_at_ms=2000))
    log.observe(
        0,
        record(id="judge", model_id="provider/judge", role="judge", case_id=1, observed_at_ms=2000),
    )
    log.observe(
        0,
        record(
            2,
            id="judge",
            model_id="provider/judge",
            role="judge",
            case_id=1,
            state="completed",
            observed_at_ms=3000,
        ),
    )
    log.observe(
        0,
        record(
            2,
            id="grade",
            kind="grading",
            scope="case",
            case_id=1,
            state="completed",
            observed_at_ms=3000,
        ),
    )
    log.observe(
        0, record(2, id="aggregate", kind="aggregation", state="completed", observed_at_ms=4000)
    )
    html = activity_html(log, ("candidate",))
    assert (
        html.index("Graded with provider/judge")
        < html.index("Grading complete")
        < html.index("Scores aggregated")
    )
    assert "Completion observed: 1970-01-01 00:00:04 UTC" in html
    assert "First observed: 1970-01-01 00:00:02 UTC" in html


def test_recording_is_hidden_but_recording_failure_is_visible():
    log = ActivityLog()
    log.observe(0, record(id="saved", kind="answering", action="recording", state="completed"))
    log.observe(
        0,
        record(
            id="failed",
            kind="answering",
            action="recording",
            state="failed",
            failure_code="internal_error",
        ),
    )
    html = activity_html(log, ("candidate",))
    assert "Answer recorded" not in html
    assert "Recording answer failed: internal error" in html


def test_evaluation_completion_requires_verified_result():
    log = ActivityLog()
    assert "Evaluation complete" not in activity_html(log, ("candidate",), finished=True)
    log.observe(
        0, record(id="aggregate", kind="aggregation", state="completed", observed_at_ms=4000)
    )
    html = activity_html(log, ("candidate",), finished=True, completed_at_ms=5000)
    assert html.index("Scores aggregated") < html.index("Evaluation complete")
    assert "Completion observed: 1970-01-01 00:00:05 UTC" in html


def test_concurrent_case_summaries_follow_completion_order_with_equal_timestamps():
    log = ActivityLog()
    for case in (1, 2):
        log.observe(
            0,
            record(
                id=f"grade{case}", kind="grading", scope="case", case_id=case, observed_at_ms=1000
            ),
        )
    for case in (2, 1):
        log.observe(
            0,
            record(
                2,
                id=f"grade{case}",
                kind="grading",
                scope="case",
                case_id=case,
                state="completed",
                observed_at_ms=2000,
            ),
        )
    html = activity_html(log, ("candidate",))
    assert html.index("Case 2: Grading complete") < html.index("Case 1: Grading complete")
    assert len(log.history()) == 4
