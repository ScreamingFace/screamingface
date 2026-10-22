import pytest

from screamingface_engine.activity.observer import ActivityObserver
from screamingface_engine.benchmarks.case_grading_report import report_case_grading
from screamingface_engine.observations import RunObservations


@pytest.mark.parametrize("enabled", [True, False])
def test_case_grading_records_pair_and_releases_pending_cases(monkeypatch, enabled):
    records = []

    def emit(body, attributes=None, **kwargs):
        records.append(dict(attributes or {}))

    monkeypatch.setattr(
        "screamingface_engine.benchmarks.case_grading_report.current_log_sink", lambda: emit
    )
    observer = ActivityObserver(enabled=enabled)
    with RunObservations((lambda: observer,)).bind():
        report_case_grading("007", "started")
        report_case_grading("007", "started")
        report_case_grading("007", "completed")
        report_case_grading(7, "started")
        report_case_grading(7, "failed")
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
    from url4 import CodeCall, CodeInput
    from url4.core.errors import ResolutionError
    from url4.peer.server import Url4Node

    records = []
    monkeypatch.setattr(
        "screamingface_engine.benchmarks.case_grading_report.current_log_sink",
        lambda: lambda body, attrs, **kwargs: records.append(dict(attrs)),
    )
    for registration in BUILTIN_REGISTRATIONS:
        node = Url4Node("grading-entries")
        registration.benchmark.install(node, tmp_path)
        run = RunObservations((ActivityObserver,))
        with run.bind():
            # WHY (spec 2026-10-20 R1): a Benchmark's check runs in process inside its
            # case-evaluation code, which reads the Case identity from the `case` source.
            entries = [
                (path, handler)
                for path, handler in node._code.items()
                if path.rsplit("/", 1)[-1] == "case-evaluation"
            ]
            assert entries
            for path, handler in entries:
                records.clear()
                call = CodeCall(
                    path,
                    {},
                    (
                        CodeInput(1, "case", '{"id": 42, "case_id": "42"}', 0.0),
                        CodeInput(2, "attempt_1", "malformed input", 0.0),
                        CodeInput(3, "reasoning", "malformed input", 0.0),
                    ),
                )
                try:
                    result = handler(call)
                    if inspect.isawaitable(result):
                        await result
                except (ResolutionError, ValueError):
                    pass
                assert len(records) == 1
                assert records[0]["sf.activity.case_id"] == 42
                assert records[0]["sf.activity.state"] == "started"
        await run.aclose()


def test_case_envelope_reports_failure_without_changing_result(monkeypatch):
    import json
    from typing import cast

    from screamingface_engine.benchmarks.case_evaluation import case_evaluation_code
    from screamingface_engine.benchmarks.contract import encode_candidate_invocation
    from url4 import CodeCall, CodeInput
    from url4.core.errors import ResolutionError

    signals = []
    monkeypatch.setattr(
        "screamingface_engine.benchmarks.case_evaluation.report_case_grading",
        lambda *args: signals.append(args),
    )
    invocation = encode_candidate_invocation("answer", "stop", None)
    call = CodeCall(
        "/case-evaluation",
        {},
        (
            CodeInput(1, "case", '{"id": "007", "case_id": "7"}', 0.0),
            CodeInput(2, "attempt_1", invocation, 0.0),
        ),
    )

    def failing(case_id, rows):
        raise ResolutionError("grader failed", code="failed", permanent=True)

    # WHY (spec 2026-10-20 R1): the envelope is built by the case-evaluation code; a grading
    # failure is kept as that Attempt's collected-error outcome.
    for build, state in [(lambda case_id, rows: {"score": 0}, "completed"), (failing, "failed")]:
        handler = case_evaluation_code(
            label="example",
            check=lambda case_id, invocation, others: {},
            build_case_grade=build,
            observe_grading=False,
        )
        result = json.loads(cast(str, handler(call)))
        assert result["candidate_invocation"] == invocation
        if state == "completed":
            assert result["grading"] == [{"score": 0}]
        else:
            assert result["grading"][0]["error"]["code"] == "failed"
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
            report_case_grading(7, "started")
        assert not calls
        report_case_grading(7, "started")
    assert len(calls) == 1
