import pytest

from screamingface_engine.activity.observer import ActivityObserver
from screamingface_engine.benchmarks.grading_activity import grading_activity
from screamingface_engine.observations import RunObservations


@pytest.mark.parametrize("enabled", [True, False])
def test_case_grading_records_pair_and_releases_pending_cases(monkeypatch, enabled):
    records = []

    def emit(body, attributes=None, **kwargs):
        records.append(dict(attributes or {}))

    monkeypatch.setattr(
        "screamingface_engine.benchmarks.grading_activity.current_log_sink", lambda: emit
    )
    observer = ActivityObserver(enabled=enabled)
    with RunObservations((lambda: observer,)).bind():
        grading_activity("007", "started")
        grading_activity("007", "started")
        grading_activity("007", "completed")
        grading_activity(7, "started")
        grading_activity(7, "failed")
    assert not observer._calls
    assert not observer._grading
    if not enabled:
        assert not records
        return
    assert [r["sf.activity.revision"] for r in records] == [1, 2, 1, 2]
    assert records[0]["sf.activity.id"] == records[1]["sf.activity.id"]
    assert records[3]["sf.activity.id"] != records[0]["sf.activity.id"]
    assert all(
        r["sf.activity.scope"] == "case" and r["sf.activity.kind"] == "grading" for r in records
    )


@pytest.mark.asyncio
async def test_shipped_grading_entries_report_explicit_case_before_work(monkeypatch, tmp_path):
    import inspect

    from screamingface_engine.benchmarks.builtins import BUILTIN_REGISTRATIONS
    from url4.core.errors import ResolutionError
    from url4.peer.server import Request, Url4Node

    records = []
    monkeypatch.setattr(
        "screamingface_engine.benchmarks.grading_activity.current_log_sink",
        lambda: lambda body, attrs, **kwargs: records.append(dict(attrs)),
    )
    for registration in BUILTIN_REGISTRATIONS:
        node = Url4Node("grading-entries")
        registration.benchmark.install(node, tmp_path)
        run = RunObservations((ActivityObserver,))
        with run.bind():
            entries = [
                (route, handler)
                for route, handler in node._endpoints.items()
                if route.rsplit("/", 1)[-1] in {"check", "tasks", "rubric-tasks"}
            ]
            assert entries
            for route, handler in entries:
                records.clear()
                try:
                    result = handler(Request(route, "malformed input", "42", {}))
                    if inspect.isawaitable(result):
                        await result
                except ResolutionError:
                    pass
                assert len(records) == 1
                assert records[0]["sf.activity.case_id"] == 42
                assert records[0]["sf.activity.state"] == "started"
        await run.aclose()


def test_case_envelope_reports_failure_without_changing_result(monkeypatch):
    import json

    from screamingface_engine.benchmarks.case_execution import _case_execution
    from screamingface_engine.benchmarks.contract import encode_candidate_invocation
    from url4.peer.server import Request

    signals = []
    monkeypatch.setattr(
        "screamingface_engine.benchmarks.case_execution.grading_activity",
        lambda *args: signals.append(args),
    )
    invocation = encode_candidate_invocation("answer", "stop", None)
    for grading, state in [
        ([{"score": 0}], "completed"),
        ([{"error": {"code": "failed"}}], "failed"),
    ]:
        payload = {"case_id": "007", "candidate_invocation": invocation, "grading": grading}
        result = json.loads(
            _case_execution(Request("/benchmarks/case-execution", json.dumps(payload), "", {}))
        )
        assert result["grading"] == grading
        assert signals[-1] == ("007", state)


@pytest.mark.asyncio
async def test_case_phase_bounds_pending_cases_and_cleans_up(monkeypatch):
    from screamingface_engine.activity import case_grading

    monkeypatch.setattr(case_grading, "MAX_PENDING_CASES", 2)
    observer = ActivityObserver()
    records = []

    def sink(body, attributes=None, **kwargs):
        records.append(dict(attributes or {}))

    observer.case_grading("unstarted", "completed", sink)
    for case in ("a", "b", "c"):
        observer.case_grading(case, "started", sink)
    assert len(observer._grading) == 2
    assert len(records) == 2
    observer.case_grading("a", "completed", sink)
    observer.case_grading("c", "started", sink)
    assert len(observer._grading) == 2
    assert records[-2]["sf.activity.suppressed.rate"] == 1
    await observer.aclose()
    observer.case_grading("d", "started", sink)
    assert not observer._grading
    assert len(records) == 4


def test_case_phase_excludes_candidate_checks_and_contains_observer_faults(monkeypatch):
    from screamingface_engine.candidate_scope import candidate_invocation_scope

    calls = []

    class Broken(ActivityObserver):
        def case_grading(self, case_id, state, emit):
            calls.append((case_id, state, emit))
            raise RuntimeError("observer failure")

    with RunObservations((Broken,)).bind():
        with candidate_invocation_scope():
            grading_activity(7, "started")
        assert not calls
        grading_activity(7, "started")
    assert len(calls) == 1
