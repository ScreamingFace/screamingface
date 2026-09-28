from test_activity_logs import record

from screamingface._ui.activity_groups import groups, stage_status
from screamingface._ui.activity_state import ActivityLog


def test_calls_follow_parent_activity_not_arrival_order():
    log = ActivityLog()
    log.observe(0, record(id="answer", kind="answering"))
    log.observe(0, record(id="grade", kind="grading"))
    log.observe(0, record(id="a", parent_id="answer", model_id="model/a"))
    log.observe(0, record(id="b", parent_id="grade", model_id="model/b"))
    selected = groups(log, 0)
    assert [(g.label, [c.record.id for c in g.calls]) for g in selected] == [
        ("Answering", ["a"]),
        ("Grading", ["b"]),
    ]
    assert stage_status(log, 0, now_ms=110000) == "Running"


def test_missing_cross_run_and_cyclic_parents_stay_unassigned():
    log = ActivityLog()
    log.observe(0, record(id="stage", kind="grading", run="other"))
    log.observe(0, record(id="a", parent_id="stage"))
    log.observe(0, record(id="b", parent_id="c"))
    log.observe(0, record(id="c", parent_id="b"))
    assert [c.record.id for c in groups(log, 0)[-1].calls] == ["a", "b", "c"]
    assert groups(log, 0)[-1].label == "Activity not identified"
    assert groups(log, 1) == []


def test_nested_calls_resolve_nearest_stage_and_late_parent():
    log = ActivityLog()
    log.observe(0, record(id="child", parent_id="model"))
    log.observe(0, record(id="model", parent_id="phase"))
    log.observe(0, record(id="phase", kind="grading"))
    assert [c.record.id for c in groups(log, 0)[0].calls] == ["child", "model"]
    assert stage_status(log, 0, now_ms=400000) == "Waiting"
    log.observe(0, record(2, id="phase", kind="grading", state="completed"))
    assert stage_status(log, 0, now_ms=110000) == "Waiting"


def test_candidate_row_shows_stage_without_changing_authoritative_status():
    from test_live_candidate_progress import candidate

    from screamingface._ui.evaluation_state import _EvaluationProgress
    from screamingface._ui.evaluation_view import _candidate_row_html

    row = _EvaluationProgress(candidates=(candidate("one"),), case_count=1).rows[0]
    row.started = True
    row.stage = "Answering, Grading"
    html = _candidate_row_html(row, None)
    assert "Answering, Grading" in html
    assert ">Running" not in html
    assert row.status == "running"
