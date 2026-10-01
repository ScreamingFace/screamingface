"""Remediating runtime logs already on disk (OME-1048).

FEATURE: local runtime log hygiene — the history written before OME-990, not just the live file.
STORY: as a researcher who ran the stack before OME-990, I want my old prompt-bearing logs
private and, when I choose, gone.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from screamingface._runtime import cli, runtime_logging
from screamingface._runtime.config import RuntimeConfig

posix_only = pytest.mark.skipif(os.name == "nt", reason="POSIX file modes")


def _plant_world_readable_logs(path: Path, backups: range) -> list[Path]:
    planted = [path, *(path.with_name(f"{path.name}.{index}") for index in backups)]
    for candidate in planted:
        candidate.write_text(f"leaked ?q=a prompt from before OME-990 in {candidate.name}\n")
        candidate.chmod(0o644)
    return planted


@posix_only
def test_every_log_path_is_private_after_a_start(tmp_path: Path) -> None:
    # INVARIANT (OME-1048): a backup written 0644 by the pre-OME-990 code is renamed, never
    # reopened, by `_rotate` — so without remediation it stays world-readable until five more
    # 10 MiB rotations push it out. Every start must tighten the whole log set.
    path = tmp_path / "runtime.log"
    _plant_world_readable_logs(path, range(1, runtime_logging.LOG_BACKUPS + 1))

    with runtime_logging.capture_runtime_log(path, foreground=False):
        pass

    paths = cli._log_paths(path)
    assert len(paths) == runtime_logging.LOG_BACKUPS + 1
    assert {candidate: candidate.stat().st_mode & 0o777 for candidate in paths} == {
        candidate: 0o600 for candidate in paths
    }


@posix_only
def test_a_gappy_backup_set_is_tightened_without_error(tmp_path: Path) -> None:
    # Boundary: rotation history is not guaranteed contiguous (a user may have deleted one).
    path = tmp_path / "runtime.log"
    for index in (2, 5):
        backup = path.with_name(f"runtime.log.{index}")
        backup.write_text("old\n")
        backup.chmod(0o644)

    runtime_logging.RuntimeLog(path).close()

    assert [candidate.stat().st_mode & 0o777 for candidate in cli._log_paths(path)] == [0o600] * 3


@posix_only
def test_tightening_leaves_the_backup_content_untouched(tmp_path: Path) -> None:
    # WHY: (a) is chmod-only. Destroying history on start is option (b), which the owner
    # explicitly rejected — a user may want those logs for debugging.
    path = tmp_path / "runtime.log"
    planted = _plant_world_readable_logs(path, range(1, 3))
    before = {candidate: candidate.read_text() for candidate in planted[1:]}

    runtime_logging.RuntimeLog(path).close()

    assert {candidate: candidate.read_text() for candidate in planted[1:]} == before


def test_logs_purge_removes_the_backups_and_empties_the_live_log(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    config = RuntimeConfig(data_dir=tmp_path)
    planted = _plant_world_readable_logs(config.log_path, range(1, runtime_logging.LOG_BACKUPS + 1))

    cli.main(["logs", "--purge", "--data-dir", str(tmp_path)])

    assert [candidate.exists() for candidate in planted[1:]] == [False] * len(planted[1:])
    assert config.log_path.read_text() == ""
    assert cli._log_paths(config.log_path) == (config.log_path,)
    out = capsys.readouterr().out
    # It reports what it did and does not tail the (now empty) log.
    assert f"purged {len(planted)} runtime log file(s)" in out
    assert "leaked" not in out
    if os.name != "nt":
        assert config.log_path.stat().st_mode & 0o777 == 0o600


def test_a_running_writer_keeps_logging_after_a_purge(tmp_path: Path) -> None:
    # WHY truncate the live file rather than unlink it: a running stack holds it open for
    # append. Unlinking would leave the process writing into an invisible inode, so
    # `screamingface logs` would go blind until the next restart.
    config = RuntimeConfig(data_dir=tmp_path)
    log = runtime_logging.RuntimeLog(config.log_path)
    log.write("a prompt written before the purge\n")

    runtime_logging.purge_runtime_log(config.log_path)
    log.write("written after the purge\n")
    log.close()

    content = config.log_path.read_text()
    assert "before the purge" not in content
    assert "written after the purge" in content


def test_logs_purge_with_no_log_says_there_is_nothing_to_purge(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    config = RuntimeConfig(data_dir=tmp_path)

    cli.main(["logs", "--purge", "--data-dir", str(tmp_path)])

    assert "no runtime log to purge" in capsys.readouterr().out
    assert not config.log_path.exists()


def test_logs_purge_clears_backups_even_when_the_live_log_is_gone(tmp_path: Path) -> None:
    # Boundary: a user deleted runtime.log by hand but the prompt-bearing backups remain.
    config = RuntimeConfig(data_dir=tmp_path)
    backup = config.log_path.with_name("runtime.log.3")
    backup.write_text("old prompt\n")

    assert runtime_logging.purge_runtime_log(config.log_path) == 1
    assert not backup.exists()
    assert not config.log_path.exists()
