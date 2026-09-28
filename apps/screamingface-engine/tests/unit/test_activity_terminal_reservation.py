"""A burst must not strand operations whose start was already published."""

import asyncio

import pytest
from test_activity_scope import Clock, Sink, session

from screamingface_engine.activity.contract import ActivityKind
from screamingface_engine.activity.scope import operation
from screamingface_engine.activity.session import activate


@pytest.mark.parametrize("failure", [None, RuntimeError("failed"), asyncio.CancelledError()])
def test_concurrent_burst_preserves_outcomes_for_every_admitted_start(failure):
    sink = Sink()
    with activate(session(Clock())):
        operations = [operation(emit=sink, kind=ActivityKind.MODEL_CALL) for _ in range(160)]
        for op in operations:
            op.__enter__()
        for op in reversed(operations):
            op.__exit__(type(failure) if failure is not None else None, failure, None)
    started = {
        r[1]["sf.activity.id"] for r in sink.records if r[1]["sf.activity.state"] == "started"
    }
    completed = {
        r[1]["sf.activity.id"]
        for r in sink.records
        if r[1]["sf.activity.state"] in {"completed", "failed", "cancelled"}
    }
    assert started
    assert started <= completed


def test_case_grading_burst_also_reserves_terminal_delivery():
    from screamingface_engine.activity.observer import ActivityObserver

    sink = Sink()
    observer = ActivityObserver()
    observer.session = session(Clock())
    for case in range(160):
        observer.case_grading(case, "started", sink)
    for case in reversed(range(160)):
        observer.case_grading(case, "completed", sink)
    starts = {
        r[1]["sf.activity.id"] for r in sink.records if r[1]["sf.activity.state"] == "started"
    }
    ends = {
        r[1]["sf.activity.id"] for r in sink.records if r[1]["sf.activity.state"] == "completed"
    }
    assert starts <= ends
