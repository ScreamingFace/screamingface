"""The journal pathname remains protected when its data file is rotated."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest
from test_regrade_batch_script import _SCRIPT, _entry, _FakeRegrader, batch

locked_journal = batch.locked_journal


def test_rotation_before_next_entry_prevents_its_replay(tmp_path: Path) -> None:
    path = tmp_path / "journal"
    client = _FakeRegrader({"one": None})

    def entries():
        path.rename(tmp_path / "rotated")
        path.write_bytes(b"")
        yield _entry("one", "spec")

    with pytest.raises(batch.LogError, match="replaced"):
        batch.regrade_all(client, entries(), path)
    assert client.calls == []


def test_real_process_rotation_cannot_start_a_second_operator(tmp_path: Path) -> None:
    worker = """
import sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from regrade_batch_log import locked_journal, BatchAlreadyRunning, LogError
try:
    with locked_journal(Path(sys.argv[2]), 'scope', {}) as journal:
        print('LOCKED', flush=True)
        sys.stdin.readline()
        journal.check_current()
except BatchAlreadyRunning:
    sys.exit(2)
except LogError:
    sys.exit(3)
"""
    path = tmp_path / "journal"
    command = [sys.executable, "-c", worker, str(_SCRIPT.parent), str(path)]
    first = subprocess.Popen(
        command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
    )
    try:
        assert first.stdout is not None
        assert first.stdout.readline().strip() == "LOCKED"
        path.rename(tmp_path / "rotated")
        path.write_bytes(b"")
        second = subprocess.run(command, input="\n", capture_output=True, text=True, timeout=10)
        assert second.returncode == 2, second.stderr
        assert "LOCKED" not in second.stdout
        first.communicate("\n", timeout=10)
        assert first.returncode == 3
        third = subprocess.run(command, input="\n", capture_output=True, text=True, timeout=10)
        assert third.returncode == 0, third.stderr
        assert "LOCKED" in third.stdout
    finally:
        if first.poll() is None:
            first.kill()
        first.communicate()


@pytest.mark.parametrize("target", ["journal", "journal.lock"])
def test_active_operator_detects_removed_or_replaced_path(tmp_path: Path, target: str) -> None:
    path = tmp_path / "journal"
    with locked_journal(path, "scope", {}) as journal:
        (tmp_path / target).unlink()
        with pytest.raises(batch.LogError, match="replaced"):
            journal.check_current()
        (tmp_path / target).write_bytes(b"")
        with pytest.raises(batch.LogError, match="replaced"):
            journal.check_current()
