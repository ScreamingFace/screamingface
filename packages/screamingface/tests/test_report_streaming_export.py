from __future__ import annotations

import errno
import json
import os
import stat
from pathlib import Path

import pytest
from _report_fixtures import (
    candidate,
    large_candidates,
    oracle,
    peak_bytes,
    report,
    track_live_candidate_dicts,
    umask,
)

import screamingface as sf

_UMASK = 0o022


def _names(directory: Path) -> list[str]:
    return sorted(path.name for path in directory.iterdir())


def _numbered(count: int) -> sf.Report:
    return report(*(candidate(f"cand-{index}", start_minute=index) for index in range(count)))


def test_a_crash_mid_export_keeps_the_previous_file_intact(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    value = _numbered(5)
    target = tmp_path / "report.json"
    value.export(target)
    previous = target.read_bytes()
    original = sf.CandidateResult.to_dict
    calls = 0

    def failing(self: sf.CandidateResult) -> dict[str, object]:
        nonlocal calls
        calls += 1
        if calls == 4:
            raise RuntimeError("the fourth Candidate failed")
        return original(self)

    monkeypatch.setattr(sf.CandidateResult, "to_dict", failing)

    with pytest.raises(RuntimeError, match="fourth Candidate"):
        value.export(target)

    assert target.read_bytes() == previous
    assert _names(tmp_path) == ["report.json"]


def test_a_disk_full_error_removes_the_temp_file_and_keeps_the_old_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    value = _numbered(3)
    target = tmp_path / "report.json"
    target.write_bytes(b"previous complete report")

    def full(_fd: int) -> None:
        raise OSError(errno.ENOSPC, "No space left on device")

    monkeypatch.setattr(os, "fsync", full)

    with pytest.raises(OSError, match="No space left"):
        value.export(target)

    assert target.read_bytes() == b"previous complete report"
    assert _names(tmp_path) == ["report.json"]


@pytest.mark.parametrize(
    "value",
    [
        _numbered(1),
        _numbered(11),
        report(
            candidate("opus", text='emoji \U0001f600 "quoted" \\ \x00 שלום'),
            candidate("gpt", text="line separator é"),
        ),
    ],
    ids=["one", "eleven", "escape-heavy"],
)
def test_export_bytes_equal_the_json_document(value: sf.Report, tmp_path: Path) -> None:
    selected = value.export(tmp_path / "report.json")

    assert selected.read_bytes() == oracle(value).encode("utf-8")
    assert json.loads(selected.read_text(encoding="utf-8"))["schema"] == "screamingface.report.v1"


def test_export_builds_no_whole_document_string(tmp_path: Path) -> None:
    candidates = large_candidates(6)
    value = report(*candidates)
    target = tmp_path / "report.json"

    def one_candidate() -> str:
        return json.dumps(candidates[0].to_dict(), ensure_ascii=False, separators=(",", ":"))

    reference_peak = peak_bytes(one_candidate)
    export_peak = peak_bytes(lambda: value.export(target))

    assert target.stat().st_size > 6 * 800_000
    assert export_peak < 2.0 * reference_peak


def test_export_keeps_at_most_one_candidate_dict_alive(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    value = _numbered(6)
    live_before_each_call = track_live_candidate_dicts(monkeypatch)

    value.export(tmp_path / "report.json")

    assert live_before_each_call == [0] * 6


def test_lone_surrogate_export_keeps_the_previous_file_intact(tmp_path: Path) -> None:
    # WHY: the old write_text truncated the target before it raised on the surrogate.
    target = tmp_path / "report.json"
    _numbered(2).export(target)
    previous = target.read_bytes()
    broken = report(candidate("opus", text="lone \ud800 surrogate"))

    with pytest.raises(UnicodeEncodeError):
        broken.export(target)

    assert target.read_bytes() == previous
    assert _names(tmp_path) == ["report.json"]


def test_export_through_a_symlink_replaces_the_target_and_keeps_the_link(tmp_path: Path) -> None:
    data = tmp_path / "data"
    data.mkdir()
    real = data / "out.json"
    real.write_bytes(b"old")
    link = tmp_path / "report.json"
    link.symlink_to(real)
    value = _numbered(2)

    selected = value.export(link)

    assert selected == link
    assert link.is_symlink()
    assert real.read_bytes() == oracle(value).encode("utf-8")
    assert _names(data) == ["out.json"]


def test_a_new_export_gets_the_default_mode_for_the_umask(tmp_path: Path) -> None:
    with umask(_UMASK):
        selected = _numbered(1).export(tmp_path / "report.json")

    assert stat.S_IMODE(selected.stat().st_mode) == 0o666 & ~_UMASK


def test_a_replaced_export_keeps_the_mode_of_the_old_file(tmp_path: Path) -> None:
    target = tmp_path / "report.json"
    target.write_bytes(b"old")
    target.chmod(0o640)

    with umask(_UMASK):
        _numbered(1).export(target)

    assert stat.S_IMODE(target.stat().st_mode) == 0o640
