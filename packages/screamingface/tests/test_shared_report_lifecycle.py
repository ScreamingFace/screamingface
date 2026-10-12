"""Shared stores preserve unfinished owners across notebook processes."""

import json
import os
import subprocess
import sys
from contextlib import contextmanager

import pytest
from test_report_lifecycle import presentation_report

import screamingface as sf
from screamingface._results import recovery_notice
from screamingface._results.lifecycle import report_operation
from screamingface._results.store import ResultStore, atomic_json

_CHILD = """
import sys
from pathlib import Path
from test_active_evaluation_lifecycle import PersistenceTransport
from screamingface._evaluation.runner import _prepared_results
folder=Path(sys.argv[1])
marker=folder/'evaluations/evaluation.json'
with _prepared_results(PersistenceTransport(marker), None, ('model',)):
    print('ACTIVE', flush=True)
    sys.stdin.readline()
"""


def active_owner(folder):
    return _owner_with_code(folder, _CHILD)


@contextmanager
def _owner_with_code(folder, code):
    env = {**os.environ, "PYTHONPATH": os.pathsep.join(sys.path)}
    process = subprocess.Popen(
        [sys.executable, "-u", "-c", code, str(folder)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
    )
    try:
        assert process.stdout is not None
        assert process.stdout.readline().strip() == "ACTIVE"
        yield process
    finally:
        if process.poll() is None:
            process.kill()
        process.communicate(timeout=10)


def _notice_count(monkeypatch, folder):
    notices = []
    monkeypatch.setattr(recovery_notice, "running_in_notebook", lambda: True)
    monkeypatch.setattr(recovery_notice, "display_notebook_notice", notices.append)
    monkeypatch.setattr(recovery_notice, "_shown", set())
    recovery_notice.show_recoverable_results(ResultStore(folder), "http://127.0.0.1:1")
    return len(notices)


@pytest.mark.parametrize("operation", ["recovery", "export", "display"])
def test_other_process_candidate_access_preserves_active_owner_and_death_notice(
    tmp_path, monkeypatch, operation
):
    report, marker = presentation_report(tmp_path)
    monkeypatch.setattr(type(report), "_display_notebook", lambda self: None)
    with active_owner(tmp_path) as owner:
        if operation == "recovery":
            assert sf.reports.get("evaluation", directory=tmp_path).to_json() == report.to_json()
        elif operation == "export":
            report.export(tmp_path / "report.json")
        else:
            report._ipython_display_()
        assert owner.poll() is None
        value = json.loads(marker.read_text())
        assert (value["state"], value["owner_pid"]) == ("running", owner.pid)
        owner.kill()
        owner.wait(timeout=10)
        assert _notice_count(monkeypatch, tmp_path) == 1
    sf.reports.get("evaluation", directory=tmp_path)
    assert json.loads(marker.read_text())["state"] == "ready"


@pytest.mark.parametrize("presentation", ["exporting", "rendering"])
def test_foreign_evaluation_settlement_preserves_other_process_presentation(tmp_path, presentation):
    report, marker = presentation_report(tmp_path)
    with active_owner(tmp_path) as owner, report_operation(report, presentation):
        assert owner.stdin is not None
        owner.stdin.write("finish\n")
        owner.stdin.flush()
        assert owner.wait(timeout=10) == 0
        value = json.loads(marker.read_text())
        assert (value["state"], value["owner_pid"]) == (presentation, os.getpid())
    assert json.loads(marker.read_text())["state"] == "ready"


@pytest.mark.parametrize("asynchronous", [False, True])
@pytest.mark.parametrize("lookup", ["evaluation", "saved_key"])
@pytest.mark.asyncio
async def test_all_corrupt_selection_settles_handled_failure(tmp_path, asynchronous, lookup):
    _, marker = presentation_report(tmp_path)
    saved = ResultStore(tmp_path).list()[0]
    atomic_json(
        marker, {**json.loads(marker.read_text()), "state": "running", "owner_pid": 99999999}
    )
    manifest = json.loads(saved.manifest.read_text())
    manifest["outcome"]["cache_saved_cost_usd"] = "bad"
    atomic_json(saved.manifest, manifest)
    report_id = saved.key if lookup == "saved_key" else "evaluation"
    with pytest.raises(sf.ExecutionError) as error:
        if asynchronous:
            await sf.reports.get_async(report_id, directory=tmp_path)
        else:
            sf.reports.get(report_id, directory=tmp_path)
    expected_code = "result_metadata_invalid" if lookup == "saved_key" else "candidates_failed"
    assert error.value.code == expected_code
    if lookup == "evaluation":
        assert isinstance(error.value.details, dict)
        assert error.value.details["failed"] == {saved.candidate.name: "result_metadata_invalid"}
    value = json.loads(marker.read_text())
    assert value["state"] == ("running" if lookup == "saved_key" else "ready")
    assert value["owner_pid"] == os.getpid()


def test_marker_lock_symlink_cannot_redirect_io(tmp_path):
    from screamingface._results.lifecycle import mark_evaluation

    _, marker = presentation_report(tmp_path)
    previous = json.loads(marker.read_text())
    external = tmp_path / "external"
    external.write_text("untouched")
    lock = marker.with_suffix(".json.lock")
    lock.unlink(missing_ok=True)
    lock.symlink_to(external)
    mark_evaluation(marker, "exporting")
    assert json.loads(marker.read_text()) == previous
    assert external.read_text() == "untouched"


def test_explicit_recovery_resolves_foreign_cancelled_operation_without_resurrection(tmp_path):
    presentation_report(tmp_path)
    code = """
import sys
import screamingface as sf
from screamingface._results.lifecycle import report_operation
report = sf.reports.get('evaluation', directory=sys.argv[1])
try:
    with report_operation(report, 'rendering'):
        raise KeyboardInterrupt()
except KeyboardInterrupt:
    pass
print('ACTIVE', flush=True)
sys.stdin.readline()
with report_operation(report, 'rendering'):
    pass
"""
    with _owner_with_code(tmp_path, code) as owner:
        marker = tmp_path / "evaluations/evaluation.json"
        assert json.loads(marker.read_text())["state"] == "rendering"
        sf.reports.get("evaluation", directory=tmp_path)
        assert json.loads(marker.read_text())["state"] == "ready"
        assert owner.stdin is not None
        owner.stdin.write("finish\n")
        owner.stdin.flush()
        assert owner.wait(timeout=10) == 0
        assert json.loads(marker.read_text())["state"] == "ready"


def test_dead_foreign_owner_is_discoverable_while_local_presentation_stays_active(
    tmp_path, monkeypatch
):
    report, marker = presentation_report(tmp_path)
    with active_owner(tmp_path) as owner, report_operation(report, "exporting"):
        owner.kill()
        owner.wait(timeout=10)
        assert json.loads(marker.read_text())["owner_pid"] == os.getpid()
        assert _notice_count(monkeypatch, tmp_path) == 1
    sf.reports.get("evaluation", directory=tmp_path)
    assert json.loads(marker.read_text())["state"] == "ready"


@pytest.mark.parametrize("operation", ["export", "display"])
def test_presentation_preserves_older_dead_owner_until_explicit_recovery(
    tmp_path, monkeypatch, operation
):
    report, marker = presentation_report(tmp_path)
    value = json.loads(marker.read_text())
    value.pop("lifecycle_operations", None)
    value.pop("lifecycle_interruptions", None)
    atomic_json(marker, {**value, "state": "running", "owner_pid": 99999999})
    monkeypatch.setattr(type(report), "_display_notebook", lambda self: None)
    if operation == "export":
        report.export(tmp_path / "report.json")
    else:
        report._ipython_display_()
    assert json.loads(marker.read_text())["state"] == "running"
    assert _notice_count(monkeypatch, tmp_path) == 1
    sf.reports.get("evaluation", directory=tmp_path)
    assert json.loads(marker.read_text())["state"] == "ready"
