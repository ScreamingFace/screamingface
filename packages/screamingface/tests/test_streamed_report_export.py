"""Report export remains byte-identical and preserves the last complete file."""

import json

import pytest
from test_report_panel import candidate, report

from screamingface.report import CandidateResult, Report


def test_serializer_does_not_build_whole_report_or_candidate_dicts(monkeypatch):
    source = report(candidate("example", 1.0))
    expected = json.dumps(source.to_dict(), ensure_ascii=False, separators=(",", ":"))

    def forbidden(*args, **kwargs):
        raise AssertionError("whole report/candidate materialized")

    monkeypatch.setattr(Report, "to_dict", forbidden)
    monkeypatch.setattr(CandidateResult, "to_dict", forbidden)
    assert source.to_json() == expected


def test_export_uses_the_streaming_serializer_and_preserves_previous_file(tmp_path, monkeypatch):
    from screamingface import _report_export

    target = tmp_path / "report.json"
    target.write_bytes(b"previous complete report")

    def broken(source):
        yield '{"partial":'
        raise OSError("disk full")

    monkeypatch.setattr(_report_export, "iter_report_json", broken)
    with pytest.raises(OSError, match="disk full"):
        report(candidate("example", 1.0)).export(target)
    assert target.read_bytes() == b"previous complete report"
    assert list(tmp_path.iterdir()) == [target]


def test_export_bytes_equal_original_json_and_keeps_output_symlink(tmp_path):
    source = report(candidate("example", 1.0))
    expected = json.dumps(source.to_dict(), ensure_ascii=False, separators=(",", ":")).encode()
    target = tmp_path / "target.json"
    target.write_bytes(b"old")
    target.chmod(0o640)
    link = tmp_path / "report.json"
    link.symlink_to(target)
    assert source.export(link) == link
    assert link.is_symlink()
    assert target.read_bytes() == expected
    assert target.stat().st_mode & 0o777 == 0o640
