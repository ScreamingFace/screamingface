from test_activity_logs import record

from screamingface._ui.activity_groups import active_cases, stage_status
from screamingface._ui.activity_state import ActivityLog


def test_active_stage_shows_explicit_selected_case():
    log = ActivityLog()
    log.observe(0, record(kind="answering", case_position=3, case_count=5))
    assert stage_status(log, 0, now_ms=110000) == "Answering"
    assert active_cases(log, 0, now_ms=110000) == "3 / 5"


def test_concurrent_case_statuses_remain_distinct_and_candidate_scoped():
    log = ActivityLog()
    for candidate, operation, position in [(0, "one", 1), (0, "two", 2), (1, "other", 3)]:
        log.observe(
            candidate, record(id=operation, kind="answering", case_position=position, case_count=5)
        )
    assert stage_status(log, 0, now_ms=110000) == "Answering"
    assert stage_status(log, 1, now_ms=110000) == "Answering"
    assert active_cases(log, 0, now_ms=110000) == "1 / 5, 2 / 5"
    assert active_cases(log, 1, now_ms=110000) == "3 / 5"


def test_missing_numbering_stays_stage_only():
    log = ActivityLog()
    log.observe(0, record(kind="grading", case_id="42"))
    assert stage_status(log, 0, now_ms=110000) == "Grading"
    assert active_cases(log, 0, now_ms=110000) is None


def test_completed_or_stale_case_is_not_presented_as_active():
    log = ActivityLog()
    log.observe(0, record(kind="answering", case_position=3, case_count=5))
    assert stage_status(log, 0, now_ms=400000) == "Waiting"
    assert active_cases(log, 0, now_ms=400000) is None
    log.observe(0, record(2, kind="answering", state="completed", case_position=3, case_count=5))
    assert stage_status(log, 0, now_ms=110000) == "Waiting"
    assert active_cases(log, 0, now_ms=110000) is None


def test_cases_cell_displays_active_position_without_mutating_completion_count():
    from test_live_candidate_progress import candidate

    from screamingface._ui.evaluation_state import _CandidateProgress
    from screamingface._ui.evaluation_view import _case_progress_html

    row = _CandidateProgress(
        candidate("test"), total_cases=5, completed_cases=2, started=True, active_cases="3 / 5"
    )
    assert ">3 / 5<" in _case_progress_html(row)
    assert row.completed_cases == 2
    row.terminal_status = "stopped"
    assert ">2 / 5<" in _case_progress_html(row)
