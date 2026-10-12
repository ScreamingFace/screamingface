"""Saved Candidate operations cannot settle their still-running Evaluation."""

import asyncio
import json

import pytest
from test_report_lifecycle import presentation_report

import screamingface as sf
from screamingface._evaluation.runner import _prepared_results
from screamingface._results.lifecycle import mark_evaluation, report_operation


class PersistenceTransport:
    def __init__(self, marker):
        self.marker = marker
        self.finished = None

    def prepare_results(self, evaluation, candidates):
        mark_evaluation(self.marker, "running")
        return self.marker

    def finish_results(self, candidates):
        self.finished = candidates


def _failure(selected):
    return {
        "handled": sf.ExecutionError("Candidates failed", code="candidates_failed"),
        "other_execution": sf.ExecutionError("Result unavailable", code="result_not_received"),
        "unexpected": RuntimeError("unexpected failure"),
        "interrupt": KeyboardInterrupt(),
        "cancelled": asyncio.CancelledError(),
    }.get(selected)


@pytest.mark.parametrize("operation", ["recovery", "export", "display"])
@pytest.mark.parametrize(
    "failure", [None, "handled", "other_execution", "unexpected", "interrupt", "cancelled"]
)
def test_saved_candidate_operation_cannot_settle_active_evaluation(
    tmp_path, monkeypatch, operation, failure
):
    report, marker = presentation_report(tmp_path)
    transport = PersistenceTransport(marker)
    candidates = ("model",)
    error = _failure(failure)
    monkeypatch.setattr(type(report), "_display_notebook", lambda self: None)

    def evaluate():
        with _prepared_results(transport, None, candidates):
            assert json.loads(marker.read_text())["state"] == "running"
            if operation == "recovery":
                assert (
                    sf.reports.get("evaluation", directory=tmp_path).to_json() == report.to_json()
                )
            elif operation == "export":
                report.export(tmp_path / "report.json")
            else:
                report._ipython_display_()
            # INVARIANT: saved Candidate access cannot finish ongoing evaluation work.
            assert json.loads(marker.read_text())["state"] == "running"
            if error is not None:
                raise error

    if error is None:
        evaluate()
    else:
        with pytest.raises(type(error)):
            evaluate()
    assert transport.finished == candidates
    assert json.loads(marker.read_text())["state"] == (
        "ready" if failure in (None, "handled") else "running"
    )


@pytest.mark.parametrize("presentation", ["exporting", "rendering"])
def test_evaluation_settlement_preserves_surviving_presentation(tmp_path, presentation):
    report, marker = presentation_report(tmp_path)
    transport = PersistenceTransport(marker)
    with report_operation(report, presentation):
        with _prepared_results(transport, None, ("model",)):
            assert json.loads(marker.read_text())["state"] == "running"
        assert transport.finished == ("model",)
        assert json.loads(marker.read_text())["state"] == presentation
    assert json.loads(marker.read_text())["state"] == "ready"


@pytest.mark.parametrize("operation", ["recovery", "export", "display"])
def test_successful_evaluation_cannot_hide_interrupted_candidate_operation(
    tmp_path, monkeypatch, operation
):
    from screamingface import _report_export, reports

    report, marker = presentation_report(tmp_path)
    transport = PersistenceTransport(marker)

    def interrupt(*args):
        raise asyncio.CancelledError()

    with _prepared_results(transport, None, ("model",)):
        with monkeypatch.context() as patch:
            patch.setattr(reports, "_fetch", interrupt)
            patch.setattr(_report_export, "iter_report_json", interrupt)
            patch.setattr(type(report), "_display_notebook", interrupt)
            with pytest.raises(asyncio.CancelledError):
                if operation == "recovery":
                    sf.reports.get("evaluation", directory=tmp_path)
                elif operation == "export":
                    report.export(tmp_path / "report.json")
                else:
                    report._ipython_display_()
        assert json.loads(marker.read_text())["state"] == "running"
    expected = {"recovery": "running", "export": "exporting", "display": "rendering"}
    assert json.loads(marker.read_text())["state"] == expected[operation]
    assert transport.finished == ("model",)
    sf.reports.get("evaluation", directory=tmp_path)
    assert json.loads(marker.read_text())["state"] == "ready"
