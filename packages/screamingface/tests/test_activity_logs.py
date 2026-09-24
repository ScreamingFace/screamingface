from datetime import UTC, datetime
from typing import Any

import pytest

from screamingface._ui.activity_state import ActivityLog
from screamingface.events import Log


def record(
    revision: Any = 1,
    *,
    run: Any = "run",
    id: Any = "op",
    kind: Any = "model_call",
    state: Any = "running",
    **facts: Any,
):
    attrs = {
        "schema": "screamingface.activity.v1",
        "id": id,
        "revision": revision,
        "kind": kind,
        "state": state,
        "elapsed_ms": 60000,
        "observed_at_ms": 100000,
    }
    attrs.update(facts)
    return Log(
        id=f"{id}-{revision}",
        run_id=run,
        sequence=1,
        timestamp=datetime.now(UTC),
        source="/node",
        severity_number=9,
        severity_text="INFO",
        body="SECRET PROMPT",
        attributes={"sf.activity." + k: v for k, v in attrs.items()},
    )


def test_scopes_revisions_and_terminal_are_independent():
    view = ActivityLog()
    view.observe(0, record())
    view.observe(1, record(run="other"))
    view.observe(0, record(2, state="completed"))
    view.observe(0, record())
    rows = view.rows(detailed=True)
    assert len(rows) == 2
    assert rows[0].record.state == "completed"
    assert rows[1].record.state == "running"
    assert view.retained == 3
    assert "SECRET" not in repr(view)


@pytest.mark.parametrize(
    "facts",
    [
        dict(revision=True),
        dict(kind="grading_check"),
        dict(elapsed_ms=-1),
        dict(state="bogus"),
        dict(model_id="https://secret/path"),
    ],
)
def test_malformed_records_do_not_break_activity(facts):
    view = ActivityLog()
    view.observe(0, record(**facts))
    assert view.invalid == 1
    assert not view.rows(detailed=True)
    view.observe(0, record(2, kind="grading", state="completed"))
    assert len(view.rows(detailed=True)) == 1


def test_rolling_history_and_current_revision_window():
    view = ActivityLog(limit=3)
    for i in range(1, 8):
        view.observe(0, record(i, id=str(i), state="completed"))
    assert view.retained == 3
    assert view.truncated == 4
    assert [r.record.id for r in view.rows(detailed=True)] == ["5", "6", "7"]


def test_compact_view_keeps_stages_failures_and_long_waits():
    view = ActivityLog()
    view.observe(0, record(id="fast", elapsed_ms=2, state="completed"))
    view.observe(0, record(id="stage", kind="grading", state="completed"))
    view.observe(0, record(id="retry", state="retrying"))
    assert [r.record.id for r in view.rows()] == ["stage", "retry"]
    assert len(view.rows(detailed=True)) == 3


def test_run_end_is_not_an_operation_outcome():
    view = ActivityLog()
    view.observe(0, record())
    view.end(0)
    assert view.rows(detailed=True)[0].ended
    assert view.rows(detailed=True)[0].record.state == "running"


def test_loss_snapshots_are_maxima_and_payloads_never_render():
    from screamingface._ui.activity_view import activity_html

    view = ActivityLog()
    for revision in (1, 2):
        view.observe(
            0,
            record(
                revision,
                **{"suppressed.invalid": 2, "suppressed.oversize": 0, "suppressed.rate": 3},
            ),
        )
    html = activity_html(view, ("candidate <one>",))
    assert "5" in html and "suppressed" in html
    assert "SECRET" not in html
    assert "candidate &lt;one&gt;" in html
    assert "Measured" not in html
    assert "outcome not observed" in html


def test_empty_and_terminal_display():
    from screamingface._ui.activity_view import activity_html

    view = ActivityLog()
    assert "No structured activity received yet" in activity_html(view, ("one",))
    view.observe(0, record(state="failed", failure_code="provider_timeout"))
    html = activity_html(view, ("one",))
    assert "provider timeout" in html
    assert "failed" in html
    assert "SECRET" not in html


def test_eviction_prefers_completed_history_to_unresolved_work():
    view = ActivityLog(limit=2)
    view.observe(0, record(id="waiting"))
    view.observe(0, record(id="done", state="completed"))
    view.observe(0, record(id="new", state="completed"))
    assert [row.record.id for row in view.rows(detailed=True)] == ["waiting", "new"]


def test_late_terminal_resolves_even_after_clock_moves_backwards():
    view = ActivityLog()
    view.observe(0, record())
    view.observe(0, record(3, state="completed", observed_at_ms=1))
    assert view.rows(detailed=True)[0].record.state == "completed"
    assert view.gaps == 1


@pytest.mark.parametrize(
    "facts",
    [
        dict(revision=0),
        dict(elapsed_ms=float("inf")),
        dict(attempt=0),
        dict(case_id=-1),
        dict(case_id=True),
        dict(finish_reason="SECRET"),
        dict(failure_code="SECRET"),
        dict(kind="grading", state="retrying"),
        dict(kind="grading", state="refused"),
        {"suppressed.rate": 1},
        dict(run="x" * 129),
    ],
)
def test_invalid_optional_facts_are_rejected_without_keeping_payload(facts):
    view = ActivityLog()
    view.observe(0, record(**facts))
    assert view.invalid == 1
    assert view.retained == 0


def test_byte_eviction_unknown_fields_and_run_end_rendering():
    from screamingface._ui.activity_view import activity_html

    view = ActivityLog(byte_limit=1)
    view.observe(0, record())
    assert view.retained == 0 and view.truncated == 1
    view = ActivityLog()
    view.observe(0, record(**{"prompt": "HIDDEN"}))
    view.end(0)
    html = activity_html(view, ("one",))
    assert "HIDDEN" not in html
    assert "Run ended; operation outcome not observed" in html


def test_categories_do_not_mutate_existing_occurrence():
    view = ActivityLog()
    view.observe(0, record())
    view.observe(0, record(2, kind="grading"))
    assert view.invalid == 1
    assert view.rows(detailed=True)[0].record.kind == "model_call"
    view.observe(0, record(3, state="completed"))
    view.observe(0, record(4, state="running"))
    assert view.rows(detailed=True)[0].record.state == "completed"


def test_unsupported_and_oversize_records_allow_later_activity():
    view = ActivityLog()
    view.observe(0, record(schema="future"))
    view.observe(0, record(model_id="x" * 5000))
    assert view.unsupported == 1 and view.invalid == 1
    view.observe(0, record(2))
    assert view.retained == 1


def test_bridge_loss_is_separate_from_producer_suppression():
    view = ActivityLog()
    base = record()
    for count in (2, 2, 1, 3):
        event = Log(
            id="loss",
            run_id="run",
            sequence=1,
            timestamp=base.timestamp,
            source="/node",
            severity_number=13,
            severity_text="WARN",
            body="HIDDEN",
            attributes={
                "sf.telemetry.schema": "screamingface.telemetry.v1",
                "sf.telemetry.loss.scope": "engine_bridge_logs",
                "sf.telemetry.loss.dropped_total": count,
            },
        )
        view.observe(0, event)
    assert view.bridge_loss == {0: 3}
    assert view.suppressed == {}
