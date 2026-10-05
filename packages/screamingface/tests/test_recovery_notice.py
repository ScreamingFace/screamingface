"""Recovery is announced on reopening an interrupted evaluation, not on healthy runs."""

import json
import logging
import os
from dataclasses import replace
from pathlib import Path

import pytest
from test_report_browser import large_report
from test_saved_runs import outcome
from test_transport_artifact_fetch import _candidate

from screamingface._results import evaluation
from screamingface._results.store import ResultStore, atomic_json
from screamingface._ui.notice_view import client_notice_html


def _saved(tmp_path, state="running", pid=99999999):
    store = ResultStore(tmp_path)
    context = {"id": "evaluation-id", "state": state, "owner_pid": pid, "candidates": ["model"]}
    atomic_json(tmp_path / "evaluations/evaluation-id.json", context)
    run = store.record("http://localhost", _candidate(), outcome(), context)
    return store, run


def _observe(monkeypatch):
    from screamingface._results import recovery_notice

    seen = []
    monkeypatch.setattr(recovery_notice, "running_in_notebook", lambda: True)
    monkeypatch.setattr(recovery_notice, "display_notebook_notice", seen.append)
    monkeypatch.setattr(recovery_notice, "_owner_alive", lambda pid: pid == os.getpid())
    monkeypatch.setattr(recovery_notice, "_shown", set())
    return recovery_notice, seen


def test_prepare_records_owner_without_showing_a_banner(tmp_path, monkeypatch):
    from screamingface._evaluation.model import _compiled_evaluation
    from screamingface.discovery import BenchmarkInfo

    notice, seen = _observe(monkeypatch)
    candidate = _candidate()
    resource = _compiled_evaluation(
        benchmark=BenchmarkInfo("fixture", "revision", 3),
        case_count=3,
        limit=None,
        candidates=[candidate],
        required_models=candidate.models,
    )
    contexts = evaluation.prepare(ResultStore(tmp_path), resource, (candidate,))
    context = next(iter(contexts.values()))
    assert context["state"] == "running"
    assert context["owner_pid"] == os.getpid()
    notice.show_recoverable_results(ResultStore(tmp_path), "http://localhost")
    assert seen == []


@pytest.mark.parametrize("state", ["running", "exporting"])
def test_dead_owner_with_completed_ticket_shows_one_shared_notice(tmp_path, monkeypatch, state):
    notice, seen = _observe(monkeypatch)
    store, _ = _saved(tmp_path, state)
    notice.show_recoverable_results(store, "http://localhost")
    notice.show_recoverable_results(store, "http://localhost")
    assert len(seen) == 1
    assert "import screamingface as sf; sf.reports.get('evaluation-id'" in seen[0].body
    assert repr(str(tmp_path)) in seen[0].body
    assert "sf-notice--info" in client_notice_html(seen[0])
    assert "role='status'" in client_notice_html(seen[0])


@pytest.mark.parametrize(
    "state,pid", [("ready", 99999999), ("running", os.getpid())], ids=["ready", "active-owner"]
)
def test_healthy_or_active_evaluation_stays_quiet(tmp_path, monkeypatch, state, pid):
    notice, seen = _observe(monkeypatch)
    store, _ = _saved(tmp_path, state, pid)
    notice.show_recoverable_results(store, "http://localhost")
    assert seen == []


def test_no_notice_for_legacy_metadata_or_different_engine(tmp_path, monkeypatch):
    notice, seen = _observe(monkeypatch)
    store, _ = _saved(tmp_path)
    notice.show_recoverable_results(store, "http://different-engine")
    atomic_json(tmp_path / "evaluations/evaluation-id.json", {"id": "evaluation-id"})
    notice.show_recoverable_results(store, "http://localhost")
    assert seen == []


def test_notice_escapes_copy_and_does_not_claim_all_results_exist():
    from screamingface._results.recovery_notice import recovery_notice

    value = recovery_notice("id", Path("/saved/o'brien/<results>"))
    assert "completed results" in value.body
    assert "<results>" not in client_notice_html(value)
    assert "&lt;results&gt;" in client_notice_html(value)


def test_broken_display_does_not_interrupt_client_startup(tmp_path, monkeypatch, caplog):
    notice, _ = _observe(monkeypatch)
    store, _ = _saved(tmp_path)
    monkeypatch.setattr(
        notice, "display_notebook_notice", lambda _: (_ for _ in ()).throw(RuntimeError())
    )
    with caplog.at_level(logging.WARNING):
        notice.show_recoverable_results(store, "http://localhost")
    assert "sf.reports.get" in caplog.text


@pytest.mark.parametrize("name", ["Url4CloudTransport", "AsyncUrl4CloudTransport"])
def test_new_transport_detects_interrupted_evaluation(tmp_path, monkeypatch, name):
    from screamingface._engine import transport

    notice, seen = _observe(monkeypatch)
    _saved(tmp_path)
    monkeypatch.setenv("SCREAMINGFACE_RESULTS_DIR", str(tmp_path))
    client = getattr(transport, name)("http://localhost")
    assert len(seen) == 1
    assert client._result_store is not None


@pytest.mark.parametrize("name", ["Url4CloudTransport", "AsyncUrl4CloudTransport"])
def test_persistence_opt_out_is_quiet(tmp_path, monkeypatch, name):
    from screamingface._engine import transport

    notice, seen = _observe(monkeypatch)
    _saved(tmp_path)
    monkeypatch.setenv("SCREAMINGFACE_RESULTS_DIR", str(tmp_path))
    client = getattr(transport, name)("http://localhost", save_results=False)
    assert client._result_store is None
    assert seen == []


def test_report_lifecycle_marks_ready_and_export_in_progress(tmp_path):
    from test_disk_results import with_cases

    from screamingface._results.cases import index_result
    from screamingface._results.lifecycle import mark_report

    store, run = _saved(tmp_path)
    source = large_report(3)
    run.path.write_text(json.dumps({"cases": [c.to_dict() for c in source.candidates[0].cases]}))
    _, cases = index_result(run.path)
    report = replace(source, candidates=[with_cases(source.candidates[0], cases)])
    mark_report(report, "ready")
    path = tmp_path / "evaluations/evaluation-id.json"
    assert json.loads(path.read_text())["state"] == "ready"
    mark_report(report, "exporting")
    assert json.loads(path.read_text())["state"] == "exporting"
    report.export(tmp_path / "report.json")
    assert json.loads(path.read_text())["state"] == "ready"


def test_bad_metadata_is_best_effort(tmp_path, monkeypatch):
    notice, seen = _observe(monkeypatch)
    store, _ = _saved(tmp_path)
    (tmp_path / "evaluations/evaluation-id.json").write_text("broken")
    notice.show_recoverable_results(store, "http://localhost")
    assert seen == []


def test_owner_probe(tmp_path):
    from screamingface._results.recovery_notice import _owner_alive

    assert _owner_alive(os.getpid())
    assert not _owner_alive(99999999)


def test_notebook_rendering_tracks_abrupt_death_but_clears_handled_errors(monkeypatch):
    from screamingface._results import lifecycle
    from screamingface.report import Report

    states = []
    monkeypatch.setattr(lifecycle, "mark_report", lambda report, state: states.append(state))

    def fail(report):
        raise RuntimeError("renderer failed")

    monkeypatch.setattr(Report, "_display_notebook", fail, raising=False)
    with pytest.raises(RuntimeError, match="renderer failed"):
        large_report(3)._ipython_display_()
    assert states == ["rendering", "ready"]


def test_actual_dead_process_is_discovered(tmp_path, monkeypatch):
    import subprocess
    import sys

    from screamingface._results import recovery_notice

    script = (
        "import os,sys; from pathlib import Path; "
        f"sys.path.insert(0, {str(Path(__file__).parent)!r}); "
        "from test_recovery_notice import _saved; "
        "_saved(Path(sys.argv[1]), pid=os.getpid()); os._exit(73)"
    )
    result = subprocess.run([sys.executable, "-c", script, str(tmp_path)], timeout=30)
    assert result.returncode == 73
    seen = []
    monkeypatch.setattr(recovery_notice, "running_in_notebook", lambda: True)
    monkeypatch.setattr(recovery_notice, "display_notebook_notice", seen.append)
    monkeypatch.setattr(recovery_notice, "_shown", set())
    recovery_notice.show_recoverable_results(ResultStore(tmp_path), "http://localhost")
    assert len(seen) == 1


def test_headless_does_not_scan_history(tmp_path, monkeypatch):
    from screamingface._results import recovery_notice

    monkeypatch.setattr(recovery_notice, "running_in_notebook", lambda: False)
    monkeypatch.setattr(ResultStore, "list", lambda _: pytest.fail("unneeded startup scan"))
    recovery_notice.show_recoverable_results(ResultStore(tmp_path), "http://localhost")


def test_liveness_permission_error_is_conservative(monkeypatch):
    from screamingface._results.recovery_notice import _owner_alive

    def denied(pid, sig):
        raise PermissionError()

    monkeypatch.setattr(os, "kill", denied)
    assert _owner_alive(99999999)


@pytest.mark.parametrize("report_id", [None, "", "../outside", "/outside"])
def test_lifecycle_path_cannot_escape_store(tmp_path, report_id):
    from screamingface._results.lifecycle import evaluation_path

    assert evaluation_path(tmp_path, report_id) is None
