"""Crash recovery must retain uncertainty and prevent overlapping operators."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest
from test_regrade_batch_script import _entry, _FakeRegrader, batch

Journal = sys.modules["regrade_batch_log"].Journal
entry_key = batch.entry_key
locked_journal = batch.locked_journal


def test_valid_unterminated_unresolved_record_survives_recovery(tmp_path: Path) -> None:
    path = tmp_path / "journal"
    batch.regrade_all(_FakeRegrader({}), [_entry(None, "uncached")], path)
    saved = path.read_bytes()
    path.write_bytes(saved.rstrip(b"\n"))
    assert batch.regrade_all(_FakeRegrader({}), [], path)["unresolved"] == 1
    assert path.read_bytes() == saved


def test_complete_invalid_tail_is_preserved_for_inspection(tmp_path: Path) -> None:
    path = tmp_path / "journal"
    path.write_bytes(b'{"outcome":"regraded"}')
    with pytest.raises(batch.LogError):
        batch.regrade_all(_FakeRegrader({}), [], path)
    assert path.read_bytes() == b'{"outcome":"regraded"}'


def test_score_and_spec_identity_namespaces_cannot_collide() -> None:
    common = {"benchmark_id": "board", "revision": "revision", "spec_id": "same"}
    assert entry_key({**common, "source_score_id": None}) != entry_key(
        {**common, "source_score_id": "same"}
    )


def test_delimiters_are_escaped_and_resolution_round_trips(tmp_path: Path) -> None:
    path = tmp_path / "journal"
    batch.regrade_all(_FakeRegrader({}), [_entry(None, "fusion/a=b%")], path)
    record = json.loads(path.read_text())
    key = record["entry_key"]
    assert "=" not in key
    assert key != entry_key({**record, "spec_id": "fusion%2Fa=b%"})
    args = batch._arguments(["--resolve", key + "=fresh run x=y"])
    resolutions = dict(value.split("=", 1) for value in args.resolve)
    assert (
        batch.regrade_all(_FakeRegrader({}), [], path, resolutions=resolutions)["unresolved"] == 0
    )


def test_ambiguous_legacy_keys_require_inspection(tmp_path: Path) -> None:
    path = tmp_path / "journal"
    batch.regrade_all(_FakeRegrader({}), [_entry(None, "uncached")], path)
    record = json.loads(path.read_text())
    record["entry_key"] = f"{record['benchmark_id']}/{record['revision']}/{record['spec_id']}"
    path.write_text(json.dumps(record) + "\n")
    saved = path.read_bytes()
    with pytest.raises(batch.LogError):
        batch.regrade_all(_FakeRegrader({}), [], path)
    assert path.read_bytes() == saved


def test_rotation_cannot_open_a_second_journal(tmp_path: Path) -> None:
    path = tmp_path / "journal"
    with locked_journal(path, "scope", batch.TRANSITIONS):
        path.rename(tmp_path / "rotated")
        with pytest.raises(batch.BatchAlreadyRunning):
            with locked_journal(path, "scope", batch.TRANSITIONS):
                pytest.fail("rotation bypassed the operator lock")


def test_replacement_before_append_is_detected(tmp_path: Path) -> None:
    path = tmp_path / "journal"
    batch.regrade_all(_FakeRegrader({}), [_entry(None, "s")], path)
    with locked_journal(path, "https://leaderboard.screamingface.ai", batch.TRANSITIONS) as journal:
        record = next(iter(journal.records.values()))
        path.rename(tmp_path / "rotated")
        path.write_bytes(b"")
        with pytest.raises(batch.LogError, match="replaced"):
            journal.append(record)
        assert path.read_bytes() == b""


def test_resolution_group_resumes_after_one_durable_append(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "journal"
    batch.regrade_all(_FakeRegrader({}), [_entry(None, "one"), _entry(None, "two")], path)
    keys = [json.loads(line)["entry_key"] for line in path.read_text().splitlines()]
    decisions = {key: "owner linked a fresh run" for key in keys}
    real_append = Journal.append

    def interrupted(self: Any, record: dict[str, Any]) -> None:
        real_append(self, record)
        raise OSError("simulated crash")

    with monkeypatch.context() as patch:
        patch.setattr(Journal, "append", interrupted)
        with pytest.raises(OSError):
            batch.regrade_all(_FakeRegrader({}), [], path, resolutions=decisions)
    assert batch.regrade_all(_FakeRegrader({}), [], path, resolutions=decisions)["unresolved"] == 0
    saved = path.read_bytes()
    assert batch.regrade_all(_FakeRegrader({}), [], path, resolutions=decisions)["unresolved"] == 0
    assert path.read_bytes() == saved
    with pytest.raises(batch.LogError):
        batch.regrade_all(_FakeRegrader({}), [], path, resolutions={keys[0]: "conflicting note"})
    assert path.read_bytes() == saved
