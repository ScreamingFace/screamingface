"""Damaged membership and overlapping presentation must preserve recovery."""

import json
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest
from test_persistence_followup import pair
from test_saved_runs import saved_fixture

import screamingface as sf
from screamingface._results.store import ResultStore, atomic_json


def change_membership(run, field, value):
    payload = json.loads(run.manifest.read_text())
    payload["evaluation"][field] = value
    run.manifest.write_text(json.dumps(payload))


@pytest.mark.parametrize(
    "field,value",
    [
        ("id", None),
        ("id", "../outside"),
        ("candidates", "model"),
        ("candidates", []),
        ("candidates", ["model", "model"]),
        ("case_count", "invalid"),
        ("case_count", True),
        ("case_count", 100),
        ("benchmark", {}),
    ],
)
def test_invalid_membership_isolated_before_grouping(tmp_path, field, value):
    _, first, second = pair(tmp_path)
    change_membership(second, field, value)
    runs = ResultStore(tmp_path).list()
    assert [run.key for run in runs] == [first.key]
    with pytest.raises(sf.ExecutionError) as error:
        sf.reports.get(second.key, directory=tmp_path)
    assert error.value.code == "result_metadata_invalid"
    with pytest.raises(sf.ExecutionError) as error:
        sf.reports.get(first.key, directory=tmp_path)
    assert error.value.code == "candidates_failed"
    assert error.value.partial_report is not None
    assert error.value.partial_report.candidates[0].name == "model"


def test_unrelated_missing_membership_id_does_not_poison_recovery(tmp_path):
    original, first = saved_fixture(tmp_path, 3)
    unrelated = tmp_path / ("f" * 64) / "run.json"
    unrelated.parent.mkdir()
    payload = json.loads(first.manifest.read_text())
    payload["evaluation"].pop("id")
    unrelated.write_text(json.dumps(payload))
    assert sf.reports.get(first.key, directory=tmp_path).to_json() == original.to_json()


@pytest.mark.asyncio
async def test_invalid_sibling_async_recovery_returns_healthy_partial(tmp_path):
    _, first, second = pair(tmp_path)
    change_membership(second, "case_count", "invalid")
    with pytest.raises(sf.ExecutionError) as error:
        await sf.reports.get_async(first.key, directory=tmp_path)
    assert error.value.code == "candidates_failed"
    assert error.value.partial_report is not None
    assert error.value.partial_report.candidates[0].name == "model"


def test_incomplete_legacy_membership_recovery_is_structured(tmp_path):
    _, run = saved_fixture(tmp_path, 3)
    payload = json.loads(run.manifest.read_text())
    payload["evaluation"].pop("benchmark")
    run.manifest.write_text(json.dumps(payload))
    assert len(ResultStore(tmp_path).list()) == 1
    with pytest.raises(sf.ExecutionError) as error:
        sf.reports.get(run.key, directory=tmp_path)
    assert isinstance(error.value.details, dict)
    failed = error.value.details["failed"]
    assert isinstance(failed, dict)
    assert failed == {"model": "result_metadata_invalid"}


def presentation_report(tmp_path):
    _, saved = saved_fixture(tmp_path, 3)
    marker = tmp_path / "evaluations/evaluation.json"
    atomic_json(marker, {"state": "ready", "owner_pid": 99999999})
    report = sf.reports.get(saved.key, directory=tmp_path)
    return report, marker


def pause_presentation(monkeypatch, paused):
    from screamingface import _report_export
    from screamingface.report import Report

    started, release = threading.Event(), threading.Event()
    original = _report_export.iter_report_json

    def render(self):
        if paused == "render":
            started.set()
            assert release.wait(10)

    def export(value):
        if paused == "export":
            started.set()
            assert release.wait(10)
        yield from original(value)

    monkeypatch.setattr(Report, "_display_notebook", render)
    monkeypatch.setattr(_report_export, "iter_report_json", export)
    return started, release


@pytest.mark.parametrize("paused", ["export", "render"])
def test_render_export_overlap_keeps_remaining_operation_pending(tmp_path, monkeypatch, paused):
    from screamingface._results.recovery_notice import _is_interrupted

    report, marker = presentation_report(tmp_path)
    started, release = pause_presentation(monkeypatch, paused)
    with ThreadPoolExecutor(max_workers=1) as pool:
        operation = (
            report._ipython_display_
            if paused == "render"
            else lambda: report.export(tmp_path / "a.json")
        )
        worker = pool.submit(operation)
        try:
            assert started.wait(5)
            if paused == "export":
                report._ipython_display_()
            else:
                report.export(tmp_path / "b.json")
            pending = json.loads(marker.read_text())
            assert pending["state"] == ("exporting" if paused == "export" else "rendering")
            monkeypatch.setattr(
                "screamingface._results.recovery_notice._owner_alive", lambda _: False
            )
            assert _is_interrupted(pending)
        finally:
            release.set()
            worker.result(timeout=10)
    assert json.loads(marker.read_text())["state"] == "ready"


def test_overlapping_exports_keep_first_export_pending(tmp_path, monkeypatch):
    from screamingface import _report_export

    report, marker = presentation_report(tmp_path)
    started, release = threading.Event(), threading.Event()
    original = _report_export.iter_report_json
    caller = threading.get_ident()

    def export(value):
        if threading.get_ident() != caller:
            started.set()
            assert release.wait(10)
        yield from original(value)

    monkeypatch.setattr(_report_export, "iter_report_json", export)
    with ThreadPoolExecutor(max_workers=1) as pool:
        worker = pool.submit(report.export, tmp_path / "first.json")
        try:
            assert started.wait(5)
            report.export(tmp_path / "second.json")
            assert json.loads(marker.read_text())["state"] == "exporting"
        finally:
            release.set()
            worker.result(timeout=10)
    assert json.loads(marker.read_text())["state"] == "ready"


def test_recovery_into_active_export_preserves_pending_marker(tmp_path):
    from screamingface._results.lifecycle import report_operation

    report, marker = presentation_report(tmp_path)
    saved = ResultStore(tmp_path).list()[0]
    with report_operation(report, "exporting"):
        recovered = sf.reports.get(saved.key, directory=tmp_path, destination=tmp_path)
        assert recovered.to_json() == report.to_json()
        assert json.loads(marker.read_text())["state"] == "exporting"
    assert json.loads(marker.read_text())["state"] == "ready"
