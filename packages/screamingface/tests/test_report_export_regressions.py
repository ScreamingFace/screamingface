"""Compatibility and failure-boundary regressions for streamed report export."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import BinaryIO

import pytest
from test_report_panel import candidate, report

from screamingface._atomic_file import write_atomic


@pytest.mark.parametrize("stem", ["r" * 220, "😱" * 60])
def test_export_accepts_long_existing_destination_names(tmp_path: Path, stem: str) -> None:
    source = report(candidate("example", 1.0))
    target = tmp_path / f"{stem}.json"
    target.write_bytes(b"old")
    target.chmod(0o640)

    assert source.export(target) == target
    assert target.read_bytes() == source.to_json().encode("utf-8")
    assert target.stat().st_mode & 0o777 == 0o640
    assert list(tmp_path.iterdir()) == [target]


@pytest.mark.parametrize("boundary", ["chmod", "fsync", "replace"])
def test_failures_before_replacement_keep_previous_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, boundary: str
) -> None:
    target = tmp_path / "report.json"
    target.write_bytes(b"old complete report")
    failure = OSError(f"{boundary} failed")

    def fail(*args: object, **kwargs: object) -> None:
        raise failure

    def write(stream: BinaryIO) -> None:
        stream.write(b"new report")

    monkeypatch.setattr(os, boundary, fail)
    with pytest.raises(OSError) as raised:
        write_atomic(target, write)
    assert raised.value is failure
    assert target.read_bytes() == b"old complete report"
    assert list(tmp_path.iterdir()) == [target]


def test_streamed_json_preserves_multiple_candidates_unicode_and_escaping(tmp_path: Path) -> None:
    source = report(candidate('😱 "quote"\n雪', 0.5), candidate("second", None))
    expected = json.dumps(source.to_dict(), ensure_ascii=False, separators=(",", ":"))
    assert source.to_json() == expected
    target = source.export(tmp_path / "nested" / "report.json")
    assert target.read_bytes() == expected.encode("utf-8")


def test_opening_buffered_stream_failure_closes_descriptor_and_removes_temp(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "report.json"
    target.write_bytes(b"old complete report")
    descriptors: list[int] = []
    failure = MemoryError("buffer allocation failed")

    def fail(fd: int, mode: str, buffering: int, *, closefd: bool = True) -> BinaryIO:
        assert not closefd
        descriptors.append(fd)
        raise failure

    def write(stream: BinaryIO) -> None:
        stream.write(b"new")

    monkeypatch.setattr(os, "fdopen", fail)
    with pytest.raises(MemoryError) as raised:
        write_atomic(target, write)
    assert raised.value is failure
    assert target.read_bytes() == b"old complete report"
    assert list(tmp_path.iterdir()) == [target]
    with pytest.raises(OSError):
        os.fstat(descriptors[0])


@pytest.mark.parametrize("replacement_fails", [False, True])
def test_writer_closes_owned_descriptor_once_before_replacement(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, replacement_fails: bool
) -> None:
    from screamingface import _atomic_file

    target = tmp_path / "report.json"
    real_close, real_replace = os.close, os.replace
    closed: list[int] = []

    def close(fd: int) -> None:
        closed.append(fd)
        real_close(fd)

    def replace(source: Path, destination: Path) -> None:
        assert len(closed) == 1
        if replacement_fails:
            raise OSError("replacement failed")
        real_replace(source, destination)

    def write(stream: BinaryIO) -> None:
        stream.write(b"new")

    monkeypatch.setattr(os, "close", close)
    monkeypatch.setattr(os, "replace", replace)
    monkeypatch.setattr(_atomic_file, "_sync_directory", lambda directory: None)
    if replacement_fails:
        with pytest.raises(OSError, match="replacement failed"):
            write_atomic(target, write)
    else:
        write_atomic(target, write)
    assert closed.count(closed[0]) == 1
    with pytest.raises(OSError):
        os.fstat(closed[0])
    assert target.exists() is not replacement_fails


def test_directory_sync_failure_reports_error_after_complete_replacement(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from screamingface import _atomic_file

    target = tmp_path / "report.json"
    target.write_bytes(b"old")

    def fail(directory: Path) -> None:
        raise OSError("directory sync failed")

    def write(stream: BinaryIO) -> None:
        stream.write(b"new complete report")

    monkeypatch.setattr(_atomic_file, "_sync_directory", fail)
    with pytest.raises(OSError, match="directory sync failed"):
        write_atomic(target, write)
    assert target.read_bytes() == b"new complete report"
    assert list(tmp_path.iterdir()) == [target]
