from test_activity_logs import record

from screamingface._ui.activity_state import ActivityLog
from screamingface._ui.activity_view import activity_html


def test_called_hides_router_only_in_display():
    log = ActivityLog()
    log.observe(0, record(model_id="openrouter/anthropic/model", state="completed"))
    html = activity_html(log, ("candidate",))
    assert ">Case not identified: Called anthropic/model</span>" in html
    assert 'title="openrouter/anthropic/model"' in html
    assert 'data-copy="Case not identified: Called openrouter/anthropic/model"' in html


def test_graded_with_requires_success_for_the_same_case():
    log = ActivityLog()
    log.observe(
        0,
        record(
            id="judge",
            model_id="openrouter/openai/judge",
            role="judge",
            case_id=1,
            state="completed",
        ),
    )
    assert "Graded with" not in activity_html(log, ("candidate",))
    log.observe(0, record(id="other", kind="grading", scope="case", case_id=2, state="completed"))
    assert "Graded with" not in activity_html(log, ("candidate",))
    log.observe(0, record(id="grade", kind="grading", scope="case", case_id=1, state="completed"))
    assert ">Case 1: Graded with openai/judge</span>" in activity_html(log, ("candidate",))


def test_running_judge_uses_grading_with(monkeypatch):
    log = ActivityLog()
    log.observe(0, record(model_id="openrouter/openai/judge", role="judge", state="started"))
    monkeypatch.setattr("screamingface._ui.activity_view.time.time", lambda: 100)
    assert ">Case not identified: Grading with openai/judge</span>" in activity_html(
        log, ("candidate",)
    )
