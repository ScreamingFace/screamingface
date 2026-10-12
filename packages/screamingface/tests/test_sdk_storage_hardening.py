"""Saved results survive transient files, derived-index damage and handled failures."""

import asyncio
import errno
import hashlib
import json
import sqlite3
from dataclasses import replace
from pathlib import Path

import pytest
from test_saved_runs import saved_fixture

import screamingface as sf
from screamingface._core.ports import _ResultArtifact
from screamingface._results import cases
from screamingface._results.store import ResultStore


@pytest.mark.parametrize("transient", [False, True])
def test_listing_keeps_report_when_size_entry_disappears(tmp_path, monkeypatch, transient):
    _, saved = saved_fixture(tmp_path, count=1)
    extra = saved.path.parent / (".pending-download" if transient else "old-export.json")
    extra.write_bytes(b"transient bytes")
    original = Path.stat
    seen = []

    def disappear(path, *args, **kwargs):
        if path == extra:
            seen.append(path)
            path.unlink(missing_ok=True)
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "stat", disappear)
    entries = sf.reports.list(directory=tmp_path)
    assert len(entries) == 1 and entries[0].id == "evaluation"
    assert entries[0].downloaded
    assert entries[0].size_bytes == saved.path.stat().st_size + saved.manifest.stat().st_size
    assert bool(seen) is (not transient)


@pytest.mark.parametrize("damage", ["row", "truncated", "metadata", "missing-row", "legacy"])
@pytest.mark.parametrize("asynchronous", [False, True])
def test_recovery_rebuilds_damaged_index_from_verified_raw(tmp_path, damage, asynchronous):
    original, saved = saved_fixture(tmp_path, count=3)
    raw = saved.path.read_bytes()
    artifact = _ResultArtifact("a" * 64, len(raw), hashlib.sha256(raw).hexdigest())
    saved = ResultStore(tmp_path).record(
        saved.engine_url,
        saved.candidate,
        replace(saved.outcome, artifact=artifact),
        saved.evaluation,
    )
    assert sf.reports.get(saved.key, directory=tmp_path).to_json() == original.to_json()
    index = saved.path.with_suffix(".sqlite3")
    if damage == "truncated":
        index.write_bytes(b"broken sqlite")
    else:
        with sqlite3.connect(index) as db:
            if damage == "row":
                db.execute(
                    "UPDATE cases SET body=json_set(body, '$.output', 'wrong') WHERE position=1"
                )
            elif damage == "metadata":
                db.execute("UPDATE metadata SET body=json_set(body, '$.score', 0)")
            elif damage == "missing-row":
                db.execute("DELETE FROM cases WHERE position=1")
            else:
                db.execute("DROP TABLE case_stats")
    recovered = (
        asyncio.run(sf.reports.get_async(saved.key, directory=tmp_path))
        if asynchronous
        else sf.reports.get(saved.key, directory=tmp_path)
    )
    assert recovered.to_json() == original.to_json()
    assert saved.path.read_bytes() == raw
    assert recovered.candidates[0].cases[1].output == "answer 1"


def test_reused_index_is_bound_to_current_raw_bytes(tmp_path):
    _, saved = saved_fixture(tmp_path, count=2)
    sf.reports.get(saved.key, directory=tmp_path)
    raw = json.loads(saved.path.read_text())
    raw["cases"][0]["output"] = "new raw value"
    saved.path.write_text(json.dumps(raw))
    assert (
        sf.reports.get(saved.key, directory=tmp_path).candidates[0].cases[0].output
        == "new raw value"
    )


def test_valid_index_is_reused_without_redecoding(tmp_path, monkeypatch):
    _, saved = saved_fixture(tmp_path, count=2)
    sf.reports.get(saved.key, directory=tmp_path)

    def fail(*args):
        raise AssertionError("valid index must not be rebuilt")

    monkeypatch.setattr(cases, "_populate", fail)
    assert len(sf.reports.get(saved.key, directory=tmp_path).candidates[0].cases) == 2


def test_listing_tolerates_removal_after_successful_stat(tmp_path, monkeypatch):
    _, saved = saved_fixture(tmp_path, count=1)
    extra = saved.path.parent / "old-export.json"
    extra.write_bytes(b"12345")
    original = Path.stat

    def remove_after_stat(path, *args, **kwargs):
        info = original(path, *args, **kwargs)
        if path == extra:
            path.unlink()
        return info

    monkeypatch.setattr(Path, "stat", remove_after_stat)
    entries = sf.reports.list(directory=tmp_path)
    assert len(entries) == 1 and entries[0].downloaded
    assert entries[0].size_bytes == saved.path.stat().st_size + saved.manifest.stat().st_size + 5


@pytest.mark.parametrize("receipt", ["missing", "broken", "null"])
def test_invalid_index_receipt_rebuilds_from_raw(tmp_path, receipt):
    original, saved = saved_fixture(tmp_path, count=1)
    sf.reports.get(saved.key, directory=tmp_path)
    path = saved.path.with_suffix(".index.json")
    if receipt == "missing":
        path.unlink(missing_ok=True)
    else:
        path.write_text("null" if receipt == "null" else "broken")
    assert sf.reports.get(saved.key, directory=tmp_path).to_json() == original.to_json()


def test_raw_integrity_failure_is_not_repaired_from_cached_index(tmp_path):
    _, saved = saved_fixture(tmp_path, count=1)
    raw = saved.path.read_bytes()
    saved = ResultStore(tmp_path).record(
        saved.engine_url,
        saved.candidate,
        replace(
            saved.outcome,
            artifact=_ResultArtifact("a" * 64, len(raw), hashlib.sha256(raw).hexdigest()),
        ),
        saved.evaluation,
    )
    sf.reports.get(saved.key, directory=tmp_path)
    saved.path.write_bytes(raw + b" ")
    with pytest.raises(sf.ExecutionError) as error:
        sf.reports.get(saved.key, directory=tmp_path)
    assert isinstance(error.value.details, dict)
    assert error.value.details["failed"] == {"model": "result_integrity_mismatch"}


def test_listing_tolerates_saved_directory_deleted_during_sampling(tmp_path, monkeypatch):
    import shutil

    _, saved = saved_fixture(tmp_path, count=1)
    original = Path.iterdir

    def delete_directory(path):
        if path == saved.path.parent:
            shutil.rmtree(path)
        return original(path)

    monkeypatch.setattr(Path, "iterdir", delete_directory)
    entries = sf.reports.list(directory=tmp_path)
    assert len(entries) == 1 and entries[0].id == "evaluation"
    assert entries[0].size_bytes == 0


@pytest.mark.parametrize("damage", [None, "row", "truncated"])
def test_legacy_read_only_index_is_used_only_after_raw_validation(tmp_path, monkeypatch, damage):
    original, saved = saved_fixture(tmp_path, count=2)
    sf.reports.get(saved.key, directory=tmp_path)
    saved.path.with_suffix(".index.json").unlink(missing_ok=True)
    target = saved.path.with_suffix(".sqlite3")
    if damage == "row":
        with sqlite3.connect(target) as db:
            db.execute("UPDATE cases SET body=json_set(body, '$.output', 'wrong')")
    elif damage == "truncated":
        target.write_bytes(b"broken")
    temporary_file = cases.NamedTemporaryFile

    def read_only(*args, **kwargs):
        if kwargs.get("dir") == saved.path.parent:
            raise PermissionError(errno.EACCES, "read-only saved directory")
        return temporary_file(*args, **kwargs)

    monkeypatch.setattr(cases, "NamedTemporaryFile", read_only)
    if damage is None:
        assert sf.reports.get(saved.key, directory=tmp_path).to_json() == original.to_json()
    else:
        with pytest.raises(sf.ExecutionError) as error:
            sf.reports.get(saved.key, directory=tmp_path)
        assert isinstance(error.value.details, dict)
        assert error.value.details["failed"] == {"model": "result_storage_failed"}
        recovered = sf.reports.get(saved.key, directory=tmp_path, destination=tmp_path / "writable")
        assert recovered.to_json() == original.to_json()


def test_malformed_readonly_candidate_preserves_healthy_sibling(tmp_path, monkeypatch):
    from screamingface._evaluation.model import _compiled_candidate

    _, saved = saved_fixture(tmp_path, count=1, expected=["model", "good"])
    cases.index_result(saved.path)
    saved.path.with_suffix(".index.json").unlink()
    good = _compiled_candidate(
        name="good",
        kind=saved.candidate.kind,
        models=saved.candidate.models,
        url4=saved.candidate.url4,
        operations=saved.candidate.operations,
    )
    sibling = ResultStore(tmp_path).record(
        saved.engine_url, good, replace(saved.outcome, run_id="good"), saved.evaluation
    )
    sibling.persist_inline()
    saved.path.write_text('{"cases":')
    temporary_file = cases.NamedTemporaryFile

    def read_only(*args, **kwargs):
        if kwargs.get("dir") == saved.path.parent:
            raise PermissionError(errno.EACCES, "read-only saved directory")
        return temporary_file(*args, **kwargs)

    monkeypatch.setattr(cases, "NamedTemporaryFile", read_only)
    with pytest.raises(sf.ExecutionError) as error:
        sf.reports.get(saved.key, directory=tmp_path)
    assert error.value.code == "candidates_failed"
    assert error.value.partial_report is not None
    assert [candidate.name for candidate in error.value.partial_report.candidates] == ["good"]
    assert isinstance(error.value.details, dict)
    assert "model" in error.value.details["failed"]
    assert isinstance(error.value.__cause__, sf.ExecutionError)
    assert "Invalid result JSON" in str(error.value.__cause__)
