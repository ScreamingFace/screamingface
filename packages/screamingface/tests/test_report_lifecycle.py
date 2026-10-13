"""Damaged membership and overlapping presentation must preserve recovery."""

import asyncio
import json
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest
from test_saved_runs import saved_fixture

import screamingface as sf
from screamingface._results.store import ResultStore, atomic_json


def presentation_report(tmp_path):
    _, saved = saved_fixture(tmp_path, 3)
    marker = tmp_path / "evaluations/evaluation.json"
    assert saved.evaluation is not None
    atomic_json(marker, {**saved.evaluation, "state": "ready", "owner_pid": 99999999})
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


@pytest.mark.parametrize("asynchronous", [False, True])
@pytest.mark.parametrize("failure", [None, "handled", "cancelled"])
@pytest.mark.asyncio
async def test_explicit_recovery_lifecycle_settles_only_handled_results(
    tmp_path, monkeypatch, asynchronous, failure
):
    import asyncio
    import os

    from screamingface import reports

    original, saved = saved_fixture(tmp_path, 3)
    marker = tmp_path / "evaluations/evaluation.json"
    assert saved.evaluation is not None
    atomic_json(marker, {**saved.evaluation, "state": "exporting", "owner_pid": 99999999})
    destination = tmp_path / "copied"
    fetch = reports._fetch

    def observe(run):
        return _observe_recovery(run, marker, failure, fetch)

    async def observe_async(run):
        return observe(run)

    monkeypatch.setattr(reports, "_fetch", observe)
    monkeypatch.setattr(reports, "_fetch_async", observe_async)

    async def recover():
        if asynchronous:
            return await reports.get_async(saved.key, directory=tmp_path, destination=destination)
        return reports.get(saved.key, directory=tmp_path, destination=destination)

    if failure:
        with pytest.raises(asyncio.CancelledError if failure == "cancelled" else sf.ExecutionError):
            await recover()
    else:
        assert (await recover()).to_json() == original.to_json()
    for folder in (tmp_path, destination):
        value = json.loads((folder / "evaluations/evaluation.json").read_text())
        assert value["state"] == ("running" if failure == "cancelled" else "ready")
        assert value["owner_pid"] == os.getpid()


@pytest.mark.parametrize("failure", [None, "handled", "unexpected", "interrupt"])
def test_prepared_evaluation_settles_ready_without_a_decoded_candidate(tmp_path, failure):
    from screamingface._evaluation.runner import _prepared_results

    marker = tmp_path / "evaluations/evaluation.json"
    atomic_json(marker, {"state": "running", "owner_pid": 99999999})

    class Transport:
        def prepare_results(self, evaluation, candidates):
            return marker

        def finish_results(self, candidates):
            self.finished = candidates

    transport = Transport()
    errors = {
        "handled": sf.ExecutionError("failed", code="candidates_failed"),
        "unexpected": RuntimeError("unhandled"),
        "interrupt": KeyboardInterrupt(),
    }

    def evaluate():
        with _prepared_results(transport, None, ("model",)):
            if failure:
                raise errors[failure]

    if failure:
        with pytest.raises(type(errors[failure])):
            evaluate()
    else:
        evaluate()
    assert transport.finished == ("model",)
    assert json.loads(marker.read_text())["state"] == (
        "ready" if failure in (None, "handled") else "running"
    )


def test_optional_marker_failure_preserves_report_and_legacy_history(tmp_path, monkeypatch):
    from screamingface._results import lifecycle

    report, marker = presentation_report(tmp_path)
    marker.write_text("bad JSON")
    with lifecycle.report_operation(report, "exporting"):
        assert report.to_dict()["candidates"]
    marker.write_text(json.dumps({"legacy": "metadata"}))
    lifecycle.mark_report(report, "ready")
    assert json.loads(marker.read_text()) == {"legacy": "metadata"}

    def denied(*args):
        raise OSError("read-only disk")

    atomic_json(marker, {"owner_pid": 99999999, "state": "running"})
    monkeypatch.setattr(lifecycle, "atomic_json", denied)
    with lifecycle.report_operation(report, "exporting"):
        assert report.candidates
    assert json.loads(marker.read_text())["state"] == "running"


def _observe_recovery(run, marker, failure, fetch):
    import asyncio

    assert json.loads(marker.read_text())["state"] == "running"
    if failure == "handled":
        raise sf.ExecutionError("artifact expired", code="result_not_received")
    if failure == "cancelled":
        raise asyncio.CancelledError()
    return fetch(run)


@pytest.mark.parametrize("operation", ["exporting", "running"])
def test_recovery_keeps_its_marker_until_all_operations_finish(tmp_path, operation):
    from screamingface._results.lifecycle import evaluation_operation, report_operation
    from screamingface._results.recovery_lifecycle import recovery_operation

    report, marker = presentation_report(tmp_path)
    store = ResultStore(tmp_path)
    selected = store.list()[0]
    with recovery_operation(store, selected, None):
        pending = (
            report_operation(report, operation)
            if operation == "exporting"
            else evaluation_operation({marker}, "running", (sf.ExecutionError,))
        )
        with pending:
            assert json.loads(marker.read_text())["state"] == operation
        assert json.loads(marker.read_text())["state"] == "running"
    assert json.loads(marker.read_text())["state"] == "ready"


@pytest.mark.parametrize("failure", [KeyboardInterrupt, asyncio.CancelledError])
def test_cancelled_presentation_remains_unfinished(tmp_path, failure):
    from screamingface._results.lifecycle import report_operation

    report, marker = presentation_report(tmp_path)
    with pytest.raises(failure), report_operation(report, "rendering"):
        raise failure()
    assert json.loads(marker.read_text())["state"] == "rendering"


@pytest.mark.parametrize("directory_link", [False, True])
def test_marker_symlinks_cannot_redirect_optional_io(tmp_path, directory_link):
    from screamingface._results.lifecycle import copy_evaluation, evaluation_path, mark_evaluation

    store = tmp_path / "store"
    outside = tmp_path / "outside"
    outside.mkdir()
    external = outside / "safe-id.json"
    original = {"owner_pid": 99999999, "state": "running"}
    atomic_json(external, original)
    marker = store / "evaluations/safe-id.json"
    store.mkdir()
    if directory_link:
        marker.parent.symlink_to(outside, target_is_directory=True)
    else:
        marker.parent.mkdir()
        marker.symlink_to(external)
    assert evaluation_path(store, "safe-id") is None
    mark_evaluation(marker, "ready")
    good = tmp_path / "good/evaluations/safe-id.json"
    atomic_json(good, original)
    copy_evaluation(good, marker, "ready")
    copy_evaluation(marker, good, "ready")
    assert json.loads(external.read_text()) == original
    assert json.loads(good.read_text()) == original


@pytest.mark.parametrize("failure", [KeyboardInterrupt, asyncio.CancelledError])
def test_interrupted_export_preserves_unfinished_marker_and_atomic_output(
    tmp_path, monkeypatch, failure
):
    from screamingface import _report_export

    report, marker = presentation_report(tmp_path)
    output = tmp_path / "report.json"
    output.write_text("previous export")

    def interrupted(report):
        yield "{"
        raise failure()

    monkeypatch.setattr(_report_export, "iter_report_json", interrupted)
    with pytest.raises(failure):
        report.export(output)
    assert output.read_text() == "previous export"
    assert json.loads(marker.read_text())["state"] == "exporting"


@pytest.mark.asyncio
async def test_finishing_sync_recovery_preserves_inflight_async_recovery(tmp_path, monkeypatch):
    from screamingface import reports

    report, marker = presentation_report(tmp_path)
    selected = ResultStore(tmp_path).list()[0]
    entered, release = asyncio.Event(), asyncio.Event()
    fetch_async = reports._fetch_async

    async def pause(run):
        entered.set()
        await asyncio.wait_for(release.wait(), 5)
        return await fetch_async(run)

    monkeypatch.setattr(reports, "_fetch_async", pause)
    pending = asyncio.create_task(reports.get_async(selected.key, directory=tmp_path))
    try:
        await asyncio.wait_for(entered.wait(), 5)
        assert reports.get(selected.key, directory=tmp_path).to_json() == report.to_json()
        assert json.loads(marker.read_text())["state"] == "running"
    finally:
        release.set()
        await pending
    assert json.loads(marker.read_text())["state"] == "ready"


def test_cancelled_recovery_survives_overlapping_export_until_explicit_recovery(tmp_path):
    from screamingface._results.lifecycle import report_operation
    from screamingface._results.recovery_lifecycle import recovery_operation

    report, marker = presentation_report(tmp_path)
    store = ResultStore(tmp_path)
    selected = store.list()[0]
    destination = tmp_path / "copied"
    with report_operation(report, "exporting"):
        with (
            pytest.raises(asyncio.CancelledError),
            recovery_operation(store, selected, destination),
        ):
            raise asyncio.CancelledError()
    for folder in (tmp_path, destination):
        assert (
            json.loads((folder / "evaluations/evaluation.json").read_text())["state"] == "running"
        )
    with report_operation(report, "rendering"):
        pass
    assert json.loads(marker.read_text())["state"] == "running"
    with recovery_operation(store, selected, destination):
        pass
    for folder in (tmp_path, destination):
        assert json.loads((folder / "evaluations/evaluation.json").read_text())["state"] == "ready"
