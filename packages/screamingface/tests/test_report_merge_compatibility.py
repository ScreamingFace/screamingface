"""Upstream cache accounting and refusal labels survive durable report recovery."""

import json
from dataclasses import replace

from test_saved_runs import saved_fixture

import screamingface as sf
from screamingface._results.store import ResultStore
from screamingface._ui.report_view import report_overview_html


def test_recovery_and_streamed_export_preserve_upstream_fields(tmp_path):
    _, original = saved_fixture(tmp_path, 3)
    assert original.evaluation is not None
    context = dict(original.evaluation)
    context["benchmark"] = {**context["benchmark"], "inverted_grade": True}
    payload = json.loads(original.path.read_text())
    payload["inverted_grade"] = True
    saved = ResultStore(tmp_path).record(
        original.engine_url,
        original.candidate,
        replace(original.outcome, cache_hits=2, result_body=json.dumps(payload)),
        context,
    )
    saved.persist_inline()

    report = sf.reports.get(saved.key, directory=tmp_path)
    assert report.benchmark.inverted_grade is True
    assert report.candidates[0].cache_hits == 2
    target = tmp_path / "report.json"
    report.export(target)
    exported = json.loads(target.read_text())
    assert exported["benchmark"]["inverted_grade"] is True
    assert exported["candidates"][0]["cache_hits"] == 2
    overview = report_overview_html(report)
    assert "Inverted grade:" in overview
    # INVARIANT: the live browser owns the single Download action in its cases header.
    assert "download=" not in overview
