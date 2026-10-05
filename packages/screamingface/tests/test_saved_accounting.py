"""Derived accounting facts survive reopening without reading saved case bodies."""

import json
from dataclasses import fields

import pytest
from test_report_browser import large_report
from test_saved_runs import saved_fixture

import screamingface as sf
from screamingface._results import cases
from screamingface._ui.report_browser import ReportBrowser


def test_reopening_saved_report_reuses_accounting_without_decoding_all_cases(tmp_path, monkeypatch):
    _, saved = saved_fixture(tmp_path, count=60)
    first = sf.reports.get(saved.key, directory=tmp_path)
    browser = ReportBrowser(first)
    expected = browser._accounting_contexts[id(first.candidates[0])]
    assert saved.path.with_suffix(".accounting.json").exists()
    original = cases._decode
    calls = []

    def observe(body):
        calls.append(body)
        return original(body)

    monkeypatch.setattr(cases, "_decode", observe)
    second = sf.reports.get(saved.key, directory=tmp_path)
    assert calls == []
    reopened = ReportBrowser(second)
    assert reopened._accounting_contexts[id(second.candidates[0])] == expected
    assert len(calls) == 25


@pytest.mark.parametrize("content", ["broken", '{"version": 0}', '{"version": 1}'])
def test_invalid_accounting_cache_is_rebuilt(tmp_path, content):
    from screamingface._results.accounting import saved_accounting_context

    _, saved = saved_fixture(tmp_path, count=2)
    report = sf.reports.get(saved.key, directory=tmp_path)
    expected = saved_accounting_context(report.candidates[0])
    path = saved.path.with_suffix(".accounting.json")
    path.write_text(content)
    assert saved_accounting_context(report.candidates[0]) == expected
    assert json.loads(path.read_text())["version"] == 1


def test_candidate_metadata_change_invalidates_accounting_cache(tmp_path):
    from screamingface import Usage
    from screamingface._results.accounting import saved_accounting_context

    _, saved = saved_fixture(tmp_path, count=2)
    candidate = sf.reports.get(saved.key, directory=tmp_path).candidates[0]
    saved_accounting_context(candidate)
    from screamingface.report import CandidateResult

    values = {field.name: getattr(candidate, field.name) for field in fields(candidate)}
    values.pop("_metric_items")
    values.update(
        metrics=candidate.metrics, usage=Usage(cost_usd="1.25"), run_cost_status="complete"
    )
    changed = CandidateResult(**values)
    assert saved_accounting_context(changed).unattributed_cost_usd == changed.usage.cost_usd


def test_unwritable_optional_cache_preserves_accounting(tmp_path, monkeypatch):
    from screamingface._results import accounting

    _, saved = saved_fixture(tmp_path, count=2)
    candidate = sf.reports.get(saved.key, directory=tmp_path).candidates[0]
    saved.path.with_suffix(".accounting.json").unlink()

    def fail(*args):
        raise PermissionError("read-only report directory")

    monkeypatch.setattr(accounting, "atomic_json", fail)
    assert accounting.saved_accounting_context(candidate).consistent


def test_in_memory_accounting_does_not_create_cache(tmp_path, monkeypatch):
    from screamingface._results.accounting import saved_accounting_context

    monkeypatch.chdir(tmp_path)
    assert saved_accounting_context(large_report(2).candidates[0]).consistent
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize(
    "field,value",
    [
        ("operation_models", []),
        ("judge_models", {"judge": 1}),
        ("consistent", "true"),
        ("unattributed_cost_usd", "NaN"),
        ("unattributed_cost_usd", "-1"),
        ("unattributed_cost_usd", "not a number"),
    ],
)
def test_malformed_context_values_are_rebuilt(tmp_path, field, value):
    from screamingface._results.accounting import _digest, saved_accounting_context

    _, saved = saved_fixture(tmp_path, count=2)
    candidate = sf.reports.get(saved.key, directory=tmp_path).candidates[0]
    expected = saved_accounting_context(candidate)
    path = saved.path.with_suffix(".accounting.json")
    payload = json.loads(path.read_text())
    payload["context"][field] = value
    payload["digest"] = _digest(payload["context"])
    path.write_text(json.dumps(payload))
    assert saved_accounting_context(candidate) == expected


def test_old_case_index_is_upgraded_without_losing_failures(tmp_path):
    import sqlite3

    from screamingface._results.cases import index_result

    _, saved = saved_fixture(tmp_path, count=2)
    payload = json.loads(saved.path.read_text())
    payload["cases"][1].update(status="failed", grade=None)
    payload["cases"][1]["failures"] = [
        {
            "stage": "grading",
            "code": "judge_failed",
            "message": "Retained diagnostic",
            "retryable": True,
            "case_id": 1,
            "metadata": {"detail": "preserve"},
        }
    ]
    saved.path.write_text(json.dumps(payload))
    _, indexed = index_result(saved.path)
    expected = list(indexed.failures())
    assert expected[0].code == "judge_failed"
    with sqlite3.connect(indexed.path) as db:
        db.execute("DROP TABLE case_stats")
        db.execute("DROP TABLE case_failures")
    # An unwritable index still has a lossless legacy failure-reading fallback.
    assert list(indexed.failures()) == expected
    _, upgraded = index_result(saved.path)
    assert upgraded.gradeable == 1
    assert list(upgraded.failures()) == expected
    assert upgraded.by_id(1).failures == indexed.by_id(1).failures


def test_read_only_old_index_keeps_derived_coverage(tmp_path, monkeypatch, caplog):
    import sqlite3

    from screamingface._results.cases import _save_stats

    def fail(*args):
        raise sqlite3.OperationalError("read-only")

    monkeypatch.setattr(sqlite3, "connect", fail)
    _save_stats(tmp_path / "old.sqlite3", 2)
    assert "using derived count" in caplog.text
