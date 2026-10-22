from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any, Literal

import pytest
from test_activity_logs import record
from test_live_candidate_progress import candidate, report_for

from screamingface._ui import activity_widget
from screamingface._ui.activity_state import ActivityLog
from screamingface._ui.activity_view import STYLE
from screamingface._ui.activity_widget import CandidateActivityRow
from screamingface._ui.evaluation_state import _EvaluationProgress
from screamingface._ui.evaluation_widget import _NotebookEvaluationView
from screamingface.events import Log

STEP = CandidateActivityRow._RENDER_STEP_SECONDS


def _row(status: Literal["queued", "running", "stopped", "succeeded"] = "running") -> Any:
    row = _EvaluationProgress(candidates=(candidate("one"),), case_count=1).rows[0]
    if status == "running":
        row.started = True
    elif status != "queued":
        row.terminal_status = status
    return row


def _renders(monkeypatch: Any) -> list[int]:
    calls: list[int] = []
    render = activity_widget.activity_html

    def counted(*args: Any, **kwargs: Any) -> str:
        calls.append(kwargs["candidate"])
        return render(*args, **kwargs)

    monkeypatch.setattr(activity_widget, "activity_html", counted)
    return calls


def _clock(monkeypatch: Any) -> list[float]:
    now = [1_000.0]
    monkeypatch.setattr(activity_widget, "time", SimpleNamespace(time=lambda: now[0]))
    return now


def _loss(dropped: int) -> Log:
    return Log(
        id=f"loss-{dropped}",
        run_id="run",
        sequence=1,
        timestamp=datetime.now(UTC),
        source="/node",
        severity_number=13,
        severity_text="WARN",
        body="loss",
        attributes={
            "sf.telemetry.schema": "screamingface.telemetry.v1",
            "sf.telemetry.loss.scope": "engine_bridge_logs",
            "sf.telemetry.loss.dropped_total": dropped,
        },
    )


def _plain_log() -> Log:
    return Log(
        id="plain",
        run_id="run",
        sequence=1,
        timestamp=datetime.now(UTC),
        source="/node",
        severity_number=9,
        severity_text="INFO",
        body="engine log line",
    )


def _suppressed(invalid: int, rate: int) -> Log:
    counts = {"suppressed.invalid": invalid, "suppressed.oversize": 0, "suppressed.rate": rate}
    return record(state="completed", **counts)


# STORY: as a researcher, I open a row mid-run; the browser shows it at once, so its activity
# must already be there although the busy kernel never saw the click.
def test_refresh_fills_activity_for_a_row_python_believes_closed():
    log = ActivityLog()
    log.observe(0, record(state="completed"))
    panel = CandidateActivityRow(log, ("one",), 0)

    panel.refresh(_row(), elapsed=1.0)

    assert not panel.toggle.value
    assert "Model call" in panel.html.value
    assert "<style>" not in panel.html.value


# INVARIANT: the browser alone decides a row's visibility and chevron, from the click state it
# sets itself without the kernel.
def test_style_lets_the_browser_own_row_visibility_and_chevron():
    style = " ".join(STYLE.split())

    assert ".sf-candidate-row>.sf-candidate-details{display:none!important}" in style
    assert (
        ".sf-candidate-row:has(>.sf-candidate-summary .widget-toggle-button.mod-active)"
        " >.sf-candidate-details{display:flex!important}" in style
    )
    assert (
        ".sf-candidate-row .widget-toggle-button.mod-active .fa-chevron-right{"
        " transform:translateY(-50%) rotate(90deg)}" in style
    )


def test_finished_row_renders_at_most_once_per_step_and_only_on_change(monkeypatch: Any):
    log = ActivityLog()
    panel = CandidateActivityRow(log, ("one", "two"), 0)
    now = _clock(monkeypatch)
    calls = _renders(monkeypatch)
    panel.refresh(_row("stopped"), elapsed=None)

    log.observe(1, record(id="other", state="completed"))
    now[0] += STEP
    panel.refresh(_row("stopped"), elapsed=None)
    assert calls == [0]
    log.observe(0, record(id="first", state="completed"))
    panel.refresh(_row("stopped"), elapsed=None)
    log.observe(0, record(id="second", state="completed"))
    panel.refresh(_row("stopped"), elapsed=None)
    assert calls == [0, 0]
    now[0] += STEP
    panel.refresh(_row("stopped"), elapsed=None)

    assert calls == [0, 0, 0]
    assert panel.html.value.count("Model call") == 2


# INVARIANT: a running operation turns "No recent update" by wall-clock age alone, so a running
# row renders once per step without new activity.
def test_running_row_renders_once_per_step(monkeypatch: Any):
    panel = CandidateActivityRow(ActivityLog(), ("one",), 0)
    now = _clock(monkeypatch)
    calls = _renders(monkeypatch)

    panel.refresh(_row(), elapsed=1.0)
    now[0] += STEP / 2
    panel.refresh(_row(), elapsed=2.0)
    now[0] += STEP
    panel.refresh(_row(), elapsed=3.0)

    assert calls == [0, 0]


def test_queued_row_without_activity_renders_once(monkeypatch: Any):
    panel = CandidateActivityRow(ActivityLog(), ("one",), 0)
    now = _clock(monkeypatch)
    calls = _renders(monkeypatch)

    for _ in range(3):
        panel.refresh(_row("queued"), elapsed=1.0)
        now[0] += STEP

    assert calls == [0]


def test_end_renders_the_run_ended_outcome(monkeypatch: Any):
    log = ActivityLog()
    log.observe(0, record())
    panel = CandidateActivityRow(log, ("one",), 0)
    now = _clock(monkeypatch)
    panel.refresh(_row(), elapsed=1.0)

    log.end(0)
    now[0] += STEP
    panel.refresh(_row("stopped"), elapsed=None)

    assert "Run ended; operation outcome not observed" in panel.html.value


def test_events_that_store_nothing_do_not_render_again(monkeypatch: Any):
    log = ActivityLog()
    log.observe(0, _suppressed(invalid=1, rate=2))
    log.observe(0, _loss(3))
    panel = CandidateActivityRow(log, ("one",), 0)
    now = _clock(monkeypatch)
    panel.refresh(_row("stopped"), elapsed=None)
    calls = _renders(monkeypatch)

    log.observe(0, _suppressed(invalid=1, rate=2))
    log.observe(0, record(2, state="running"))
    log.observe(0, _loss(3))
    log.observe(0, _plain_log())
    now[0] += STEP
    panel.refresh(_row("stopped"), elapsed=None)

    assert calls == []


def test_loss_and_suppression_rises_render(monkeypatch: Any):
    log = ActivityLog()
    log.observe(0, record(state="completed"))
    panel = CandidateActivityRow(log, ("one",), 0)
    now = _clock(monkeypatch)
    panel.refresh(_row("stopped"), elapsed=None)

    log.observe(0, _loss(3))
    now[0] += STEP
    panel.refresh(_row("stopped"), elapsed=None)
    assert "3 Engine bridge Logs dropped" in panel.html.value
    log.observe(0, _suppressed(invalid=1, rate=2))
    now[0] += STEP
    panel.refresh(_row("stopped"), elapsed=None)

    assert "3 producer records suppressed" in panel.html.value


def test_eviction_renders_the_row_that_lost_a_record_and_the_count_on_others(monkeypatch: Any):
    log = ActivityLog(limit=1)
    names = ("one", "two", "three")
    bystander, lost = CandidateActivityRow(log, names, 0), CandidateActivityRow(log, names, 1)
    now = _clock(monkeypatch)
    log.observe(1, record(id="two", state="completed"))
    bystander.refresh(_row("stopped"), elapsed=None)
    lost.refresh(_row("stopped"), elapsed=None)

    log.observe(2, record(id="three", state="completed"))
    now[0] += STEP
    bystander.refresh(_row("stopped"), elapsed=None)
    lost.refresh(_row("stopped"), elapsed=None)

    assert "1 evaluation history entries evicted" in bystander.html.value
    assert "Model call" not in lost.html.value


def test_late_result_renders_evaluation_complete(monkeypatch: Any):
    log = ActivityLog()
    panel = CandidateActivityRow(log, ("one",), 0)
    now = _clock(monkeypatch)
    row = _row("succeeded")
    log.end(0)
    panel.refresh(row, elapsed=None)
    assert "Evaluation complete" not in panel.html.value

    row.result = report_for(candidate("one")).candidates[0]
    now[0] += STEP
    panel.refresh(row, elapsed=None)

    assert "Evaluation complete" in panel.html.value


def test_final_refresh_renders_at_once(monkeypatch: Any):
    monkeypatch.setattr(_NotebookEvaluationView, "_show", lambda self: None)
    _clock(monkeypatch)
    one, two = candidate("one"), candidate("two")
    view = _NotebookEvaluationView((one, two), 1, tick=False)
    view.candidate_failed(one, RuntimeError("one failed"))
    view.observe(two, record(state="bogus"))
    assert "invalid activity records" not in view._activity_rows[0].html.value

    view.abort(RuntimeError("stopped"))

    assert "1 invalid activity records" in view._activity_rows[0].html.value


def test_a_failed_render_is_retried_on_the_next_refresh(monkeypatch: Any):
    log = ActivityLog()
    log.observe(0, record(state="completed"))
    panel = CandidateActivityRow(log, ("one",), 0)
    now = _clock(monkeypatch)
    render = activity_widget.activity_html
    failed = False

    def flaky(*args: Any, **kwargs: Any) -> str:
        nonlocal failed
        if not failed:
            failed = True
            raise RuntimeError("render failed")
        return render(*args, **kwargs)

    monkeypatch.setattr(activity_widget, "activity_html", flaky)
    with pytest.raises(RuntimeError):
        panel.refresh(_row("stopped"), elapsed=None)
    now[0] += STEP
    panel.refresh(_row("stopped"), elapsed=None)

    assert "Model call" in panel.html.value
