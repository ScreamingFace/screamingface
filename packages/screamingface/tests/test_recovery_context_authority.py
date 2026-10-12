"""A damaged first manifest cannot become the authority for healthy siblings."""

import asyncio
import json
from copy import deepcopy

import pytest
from test_persistence_followup import pair

import screamingface as sf
from screamingface._results.store import ResultStore, atomic_json


@pytest.mark.parametrize("asynchronous", [False, True])
@pytest.mark.parametrize("lookup", ["evaluation", "damaged", "healthy"])
@pytest.mark.parametrize("field", ["case_count", "benchmark", "candidates"])
def test_canonical_membership_preserves_healthy_sibling(tmp_path, asynchronous, lookup, field):
    _, first, _ = pair(tmp_path)
    canonical = deepcopy(first.evaluation)
    assert canonical is not None
    atomic_json(tmp_path / "evaluations" / f"{canonical['id']}.json", canonical)
    damaged, healthy = ResultStore(tmp_path).list()
    data = json.loads(damaged.manifest.read_text())
    if field == "case_count":
        data["evaluation"][field] = 1
    elif field == "benchmark":
        data["evaluation"][field]["case_count"] += 1
    else:
        data["evaluation"][field] = [damaged.candidate.name]
    atomic_json(damaged.manifest, data)
    key = {"evaluation": canonical["id"], "damaged": damaged.key, "healthy": healthy.key}[lookup]
    _assert_healthy_partial(tmp_path, key, asynchronous, damaged, healthy)


@pytest.mark.parametrize("asynchronous", [False, True])
@pytest.mark.parametrize("lookup", ["evaluation", "damaged", "healthy"])
@pytest.mark.parametrize("field", ["case_count", "candidates"])
def test_legacy_membership_prefers_a_locally_validated_sibling(
    tmp_path, asynchronous, lookup, field
):
    _, first, _ = pair(tmp_path)
    assert first.evaluation is not None
    damaged, healthy = ResultStore(tmp_path).list()
    data = json.loads(damaged.manifest.read_text())
    data["evaluation"][field] = 1 if field == "case_count" else [damaged.candidate.name]
    atomic_json(damaged.manifest, data)
    key = {"evaluation": first.evaluation["id"], "damaged": damaged.key, "healthy": healthy.key}[
        lookup
    ]
    _assert_healthy_partial(tmp_path, key, asynchronous, damaged, healthy)


@pytest.mark.parametrize("asynchronous", [False, True])
def test_unreadable_evaluation_manifest_has_named_storage_error(
    tmp_path, monkeypatch, asynchronous
):
    _, first, _ = pair(tmp_path)
    assert first.evaluation is not None
    manifest = tmp_path / "evaluations" / f"{first.evaluation['id']}.json"
    atomic_json(manifest, first.evaluation)
    read_text = type(manifest).read_text

    def unreadable(path, *args, **kwargs):
        if path == manifest:
            raise PermissionError("evaluation manifest is unreadable")
        return read_text(path, *args, **kwargs)

    monkeypatch.setattr(type(manifest), "read_text", unreadable)
    with pytest.raises(sf.ExecutionError) as caught:
        if asynchronous:
            asyncio.run(sf.reports.get_async(first.evaluation["id"], directory=tmp_path))
        else:
            sf.reports.get(first.evaluation["id"], directory=tmp_path)
    assert caught.value.code == "result_storage_failed"


def _assert_healthy_partial(directory, key, asynchronous, damaged, healthy):
    with pytest.raises(sf.ExecutionError) as caught:
        if asynchronous:
            asyncio.run(sf.reports.get_async(key, directory=directory))
        else:
            sf.reports.get(key, directory=directory)
    error = caught.value
    assert error.code == "candidates_failed"
    assert isinstance(error.details, dict)
    assert error.details["failed"] == {damaged.candidate.name: "result_metadata_invalid"}
    assert error.partial_report is not None
    assert [c.name for c in error.partial_report.candidates] == [healthy.candidate.name]
    assert len(error.partial_report.candidates.only.cases) == 3
    assert error.partial_report.candidates.only.cases[0].output == "answer 0"


@pytest.mark.parametrize("asynchronous", [False, True])
def test_legacy_missing_raw_result_cannot_hide_a_known_sibling(tmp_path, asynchronous):
    _, first, _ = pair(tmp_path)
    assert first.evaluation is not None
    damaged, missing = ResultStore(tmp_path).list()
    data = json.loads(damaged.manifest.read_text())
    data["evaluation"]["candidates"] = [damaged.candidate.name]
    atomic_json(damaged.manifest, data)
    missing.path.unlink()
    with pytest.raises(sf.ExecutionError) as caught:
        _recover(tmp_path, first.evaluation["id"], asynchronous)
    assert caught.value.code == "candidates_failed"
    assert isinstance(caught.value.details, dict)
    assert caught.value.details["failed"] == {
        damaged.candidate.name: "result_metadata_invalid",
        missing.candidate.name: "result_unavailable",
    }


@pytest.mark.parametrize("asynchronous", [False, True])
def test_legacy_without_complete_membership_has_named_metadata_error(tmp_path, asynchronous):
    _, first, _ = pair(tmp_path)
    assert first.evaluation is not None
    for run in ResultStore(tmp_path).list():
        data = json.loads(run.manifest.read_text())
        data["evaluation"]["candidates"] = [run.candidate.name]
        atomic_json(run.manifest, data)
    with pytest.raises(sf.ExecutionError) as caught:
        _recover(tmp_path, first.evaluation["id"], asynchronous)
    assert caught.value.code == "result_metadata_invalid"


def _recover(directory, key, asynchronous):
    if asynchronous:
        return asyncio.run(sf.reports.get_async(key, directory=directory))
    return sf.reports.get(key, directory=directory)
