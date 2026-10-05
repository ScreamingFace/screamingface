"""Exports preserve file semantics without materializing whole candidates."""

import errno
import json
import os
import stat

import pytest
from test_report_browser import large_report

from screamingface.report import CandidateResult, Report


def test_to_json_uses_case_streaming_without_eager_candidate_dict(monkeypatch):
    report = large_report(30)
    expected = json.dumps(report.to_dict(), ensure_ascii=False, separators=(",", ":"))

    def forbidden(*args, **kwargs):
        raise AssertionError("whole report/candidate materialized")

    monkeypatch.setattr(Report, "to_dict", forbidden)
    monkeypatch.setattr(CandidateResult, "to_dict", forbidden)
    assert report.to_json() == expected


def test_export_preserves_symlink_and_permissions(tmp_path):
    report = large_report(3)
    target = tmp_path / "actual.json"
    target.write_text("old")
    target.chmod(0o640)
    link = tmp_path / "report.json"
    link.symlink_to(target)
    assert report.export(link) == link
    assert link.is_symlink()
    assert target.read_text() == report.to_json()
    assert stat.S_IMODE(target.stat().st_mode) == 0o640


def test_export_fsync_failure_keeps_previous_complete_export(tmp_path, monkeypatch):
    target = tmp_path / "report.json"
    target.write_text("previous complete export")

    def full(_fd):
        raise OSError(errno.ENOSPC, "disk full")

    monkeypatch.setattr(os, "fsync", full)
    with pytest.raises(OSError, match="disk full"):
        large_report(3).export(target)
    assert target.read_text() == "previous complete export"
    assert list(tmp_path.iterdir()) == [target]


def test_export_fsyncs_file_before_replace_and_directory_after(tmp_path, monkeypatch):
    events = []
    original_fsync = os.fsync
    original_replace = os.replace

    def sync(fd):
        events.append("directory" if stat.S_ISDIR(os.fstat(fd).st_mode) else "file")
        original_fsync(fd)

    def replace(source, target):
        events.append("replace")
        original_replace(source, target)

    monkeypatch.setattr(os, "fsync", sync)
    monkeypatch.setattr(os, "replace", replace)
    large_report(3).export(tmp_path / "report.json")
    assert events == ["file", "replace", "directory"]
