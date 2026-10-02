"""Durable case access must not materialize a whole candidate (OME-1448)."""

import json
from dataclasses import fields, replace

import pytest
from test_report_browser import large_report


def test_index_roundtrip_and_identity(tmp_path):
    from screamingface._results.cases import index_result

    source = large_report(60).candidates[0]
    path = tmp_path / "result.json"
    path.write_text(json.dumps({"cases": [c.to_dict() for c in source.cases], "score": 1.0}))
    metadata, cases = index_result(path)
    assert metadata == {"score": 1.0}
    assert len(cases) == 60
    assert cases[-1] == source.cases[-1]
    assert cases[20:23] == source.cases[20:23]
    assert cases.by_id(59) == source.cases[59]
    with pytest.raises(IndexError):
        _ = cases[60]
    with pytest.raises(KeyError):
        cases.by_id("59")
    rebuilt = with_cases(source, cases)
    assert rebuilt.cases._items is cases
    assert rebuilt.to_dict() == source.to_dict()
    # Reopening must not need the original download or a live kernel.
    path.unlink()
    assert cases[59].output == "answer 59"


def test_index_rejects_duplicate_ids_and_truncated_json(tmp_path):
    from screamingface._results.cases import index_result
    from screamingface.errors import ExecutionError

    case = large_report(1).candidates[0].cases[0].to_dict()
    path = tmp_path / "result.json"
    path.write_text(json.dumps({"cases": [case, case]}))
    with pytest.raises(ExecutionError, match="duplicate"):
        index_result(path)
    assert not path.with_suffix(".sqlite3").exists()
    path.write_text('{"cases":[')
    with pytest.raises(ExecutionError, match="JSON"):
        index_result(path)


def test_lazy_report_export_matches_eager_bytes(tmp_path):
    from screamingface._results.cases import index_result

    source = large_report(60)
    path = tmp_path / "result.json"
    path.write_text(json.dumps({"cases": [c.to_dict() for c in source.candidates[0].cases]}))
    _, cases = index_result(path)
    report = replace(source, candidates=[with_cases(source.candidates[0], cases)])
    assert report.export(tmp_path / "report.json").read_text() == source.to_json()


def with_cases(source, cases):
    from screamingface.report import CandidateResult

    values = {f.name: getattr(source, f.name) for f in fields(source) if not f.name.startswith("_")}
    values.update(cases=cases, metrics=source.metrics)
    return CandidateResult(**values)


def test_disk_and_memory_case_sequences_compare_by_value(tmp_path):
    from screamingface._results.cases import index_result

    source = large_report(3).candidates[0]
    path = tmp_path / "result.json"
    path.write_text(json.dumps({"cases": [c.to_dict() for c in source.cases]}))
    _, cases = index_result(path)
    rebuilt = with_cases(source, cases)
    assert rebuilt.cases == source.cases
    assert source.cases == rebuilt.cases
    assert rebuilt.cases == tuple(source.cases)
    assert "DiskCases" in repr(rebuilt.cases)


def test_fractional_and_large_integer_metadata_matches_standard_json(tmp_path):
    from screamingface._results.cases import index_result

    source = large_report(1).candidates[0].cases[0].to_dict()
    source["metadata"] = {"large": 2**80, "fractional": 0.12345678901234568}
    path = tmp_path / "result.json"
    path.write_text(json.dumps({"cases": [source]}))
    _, cases = index_result(path)
    assert cases[0].to_dict() == source
