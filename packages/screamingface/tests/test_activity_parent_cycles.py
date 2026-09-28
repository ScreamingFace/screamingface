"""Untrusted ancestry cannot establish stage ownership through a cycle."""

import pytest
from test_activity_logs import record

from screamingface._ui.activity_groups import groups
from screamingface._ui.activity_state import ActivityLog
from screamingface._ui.activity_view import visible_operations


@pytest.mark.parametrize("back_edge", ["model", "stage", "outer"])
def test_cycles_through_stages_stay_unidentified_and_visible(back_edge):
    log = ActivityLog()
    log.observe(0, record(id="stage", kind="answering", parent_id="outer", state="completed"))
    log.observe(0, record(id="outer", kind="grading", parent_id=back_edge, state="completed"))
    log.observe(
        0, record(id="model", parent_id="stage", model_id="provider/model", state="completed")
    )
    grouped = groups(log, 0)
    assert grouped[-1].label == "Activity not identified"
    assert [r.record.id for r in grouped[-1].calls] == ["model"]
    assert "stage" in [r.record.id for r, _ in visible_operations(log, 0)]


def test_valid_stage_chain_keeps_nearest_stage():
    log = ActivityLog()
    log.observe(0, record(id="outer", kind="grading"))
    log.observe(0, record(id="stage", kind="answering", parent_id="outer"))
    log.observe(0, record(id="model", parent_id="stage"))
    assert [(g.label, [r.record.id for r in g.calls]) for g in groups(log, 0)] == [
        ("Grading", []),
        ("Answering", ["model"]),
    ]
