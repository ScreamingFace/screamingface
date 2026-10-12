"""Known evaluations survive when every candidate manifest fails decoding."""

import json
from dataclasses import replace

import pytest
from test_persistence_followup import pair

import screamingface as sf
from screamingface._results.store import ResultStore, atomic_json


@pytest.fixture(params=[True, False], ids=["canonical", "legacy"])
def corrupt_group(tmp_path, request):
    _, first, second = pair(tmp_path)
    if request.param:
        atomic_json(tmp_path / "evaluations" / "evaluation.json", first.evaluation)
    for run in (first, second):
        data = json.loads(run.manifest.read_text())
        data["outcome"]["cache_saved_cost_usd"] = "broken"
        atomic_json(run.manifest, data)
        assert run.path.exists()
    assert len(ResultStore(tmp_path).member_manifests("evaluation")[1]) == 2
    return tmp_path, first, second


def test_known_evaluation_is_listed_despite_corrupt_costs(corrupt_group, monkeypatch):
    directory, first, second = corrupt_group

    def forbidden(*args, **kwargs):
        raise AssertionError("Listing decoded raw results")

    monkeypatch.setattr(sf.reports, "_local", forbidden)
    entries = sf.reports.list(directory=directory)
    assert [item.id for item in entries] == ["evaluation"]
    assert set(entries[0].candidates) == {"model", "second"}
    assert not entries[0].downloaded
    assert entries[0].size_bytes >= first.path.stat().st_size + second.path.stat().st_size


@pytest.mark.parametrize("asynchronous", [False, True])
@pytest.mark.asyncio
async def test_all_failed_recovery_has_named_errors(corrupt_group, monkeypatch, asynchronous):
    directory, _, _ = corrupt_group

    def forbidden(*args, **kwargs):
        raise AssertionError("Corrupt metadata reached result fetching")

    monkeypatch.setattr(sf.reports, "_fetch", forbidden)
    monkeypatch.setattr(sf.reports, "_fetch_async", forbidden)
    with pytest.raises(sf.ExecutionError) as caught:
        if asynchronous:
            await sf.reports.get_async("evaluation", directory=directory)
        else:
            sf.reports.get("evaluation", directory=directory)
    assert caught.value.code == "candidates_failed"
    assert isinstance(caught.value.details, dict)
    assert caught.value.details["failed"] == {
        "model": "result_metadata_invalid",
        "second": "result_metadata_invalid",
    }
    assert set(caught.value.details["failure_messages"]) == {"model", "second"}
    assert caught.value.partial_report is None


def test_all_corrupt_discovery_preserves_healthy_unrelated_report(corrupt_group):
    directory, first, _ = corrupt_group
    assert first.evaluation is not None
    context = {**first.evaluation, "id": "unrelated", "candidates": ["model"]}
    other = ResultStore(directory).record(
        first.engine_url, first.candidate, replace(first.outcome, run_id="unrelated"), context
    )
    other.path.write_bytes(first.path.read_bytes())
    assert {entry.id for entry in sf.reports.list(directory=directory)} == {
        "evaluation",
        "unrelated",
    }
    assert sf.reports.get("unrelated", directory=directory).candidates[0].name == "model"


@pytest.mark.parametrize("asynchronous", [False, True])
@pytest.mark.asyncio
async def test_single_corrupt_candidate_returns_named_failure(tmp_path, asynchronous):
    _, first, second = pair(tmp_path)
    sf.reports.delete(second.key, directory=tmp_path)
    assert first.evaluation is not None
    context = {**first.evaluation, "candidates": ["model"]}
    saved = ResultStore(tmp_path).record(first.engine_url, first.candidate, first.outcome, context)
    data = json.loads(saved.manifest.read_text())
    data["outcome"]["root_usage"]["cost_usd"] = "broken"
    atomic_json(saved.manifest, data)
    atomic_json(tmp_path / "evaluations" / "evaluation.json", context)
    assert sf.reports.list(directory=tmp_path)[0].candidates == ("model",)
    with pytest.raises(sf.ExecutionError) as caught:
        if asynchronous:
            await sf.reports.get_async("evaluation", directory=tmp_path)
        else:
            sf.reports.get("evaluation", directory=tmp_path)
    assert caught.value.code == "candidates_failed"
    assert isinstance(caught.value.details, dict)
    assert caught.value.details["failed"] == {"model": "result_metadata_invalid"}
    assert caught.value.partial_report is None


@pytest.mark.parametrize("operation", [sf.reports.list, sf.reports.get])
def test_invalid_canonical_metadata_is_named_even_when_all_candidates_are_corrupt(
    corrupt_group, operation
):
    directory, _, _ = corrupt_group
    manifest = directory / "evaluations" / "evaluation.json"
    atomic_json(manifest, None)
    args = () if operation is sf.reports.list else ("evaluation",)
    with pytest.raises(sf.ExecutionError) as caught:
        operation(*args, directory=directory)
    assert caught.value.code == "result_metadata_invalid"


def test_absent_report_still_raises_key_error(tmp_path):
    assert sf.reports.list(directory=tmp_path) == []
    with pytest.raises(KeyError):
        sf.reports.get("missing", directory=tmp_path)


def test_legacy_all_corrupt_listing_retains_expected_unsaved_names(corrupt_group):
    directory, first, second = corrupt_group
    for run in (first, second):
        data = json.loads(run.manifest.read_text())
        data["evaluation"]["candidates"].append("not-received")
        atomic_json(run.manifest, data)
    (directory / "evaluations" / "evaluation.json").unlink(missing_ok=True)
    entry = sf.reports.list(directory=directory)[0]
    assert set(entry.candidates) == {"model", "second", "not-received"}
    with pytest.raises(sf.ExecutionError) as caught:
        sf.reports.get("evaluation", directory=directory)
    assert isinstance(caught.value.details, dict)
    assert caught.value.details["failed"] == {
        "model": "result_metadata_invalid",
        "second": "result_metadata_invalid",
        "not-received": "result_not_received",
    }


def test_all_corrupt_unreadable_canonical_record_has_storage_error(corrupt_group, monkeypatch):
    directory, first, _ = corrupt_group
    manifest = directory / "evaluations" / "evaluation.json"
    atomic_json(manifest, first.evaluation)
    read_text = type(manifest).read_text

    def unreadable(path, *args, **kwargs):
        if path == manifest:
            raise PermissionError("canonical metadata unreadable")
        return read_text(path, *args, **kwargs)

    monkeypatch.setattr(type(manifest), "read_text", unreadable)
    for operation, args in ((sf.reports.list, ()), (sf.reports.get, ("evaluation",))):
        with pytest.raises(sf.ExecutionError) as caught:
            operation(*args, directory=directory)
        assert caught.value.code == "result_storage_failed"
