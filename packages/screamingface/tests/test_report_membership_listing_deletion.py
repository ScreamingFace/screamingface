"""Discovery and deletion cannot trust a damaged first candidate's membership."""

import json
from copy import deepcopy
from dataclasses import replace

import pytest
from test_persistence_followup import pair

import screamingface as sf
from screamingface._results.store import ResultStore, atomic_json


def damaged_pair(directory, canonical):
    _, first, _ = pair(directory)
    context = deepcopy(first.evaluation)
    assert context is not None
    manifest = directory / "evaluations" / f"{context['id']}.json"
    if canonical:
        atomic_json(manifest, context)
    damaged, healthy = ResultStore(directory).list()
    data = json.loads(damaged.manifest.read_text())
    data["evaluation"]["candidates"] = [damaged.candidate.name]
    atomic_json(damaged.manifest, data)
    return context, manifest, damaged, healthy


@pytest.mark.parametrize("canonical", [False, True])
@pytest.mark.parametrize("missing", [False, True])
def test_listing_retains_all_candidates_and_truthful_completeness(tmp_path, canonical, missing):
    context, _, _, healthy = damaged_pair(tmp_path, canonical)
    if missing:
        healthy.path.unlink()
    entry = sf.reports.list(directory=tmp_path)[0]
    assert set(entry.candidates) == set(context["candidates"])
    assert entry.downloaded is not missing
    if canonical:
        assert entry.candidates == tuple(context["candidates"])


def test_legacy_listing_includes_known_runs_when_every_context_is_truncated(tmp_path):
    context, _, _, _ = damaged_pair(tmp_path, False)
    for run in ResultStore(tmp_path).list():
        data = json.loads(run.manifest.read_text())
        data["evaluation"]["candidates"] = [run.candidate.name]
        atomic_json(run.manifest, data)
    entry = sf.reports.list(directory=tmp_path)[0]
    assert set(entry.candidates) == set(context["candidates"])
    assert entry.downloaded


@pytest.mark.parametrize("canonical", [False, True])
def test_listing_retains_expected_but_unsaved_candidates(tmp_path, canonical):
    context, manifest, _, _ = damaged_pair(tmp_path, canonical)
    context["candidates"].append("not-yet-saved")
    if canonical:
        atomic_json(manifest, context)
    else:
        run = ResultStore(tmp_path).list()[1]
        data = json.loads(run.manifest.read_text())
        data["evaluation"] = context
        atomic_json(run.manifest, data)
    entry = sf.reports.list(directory=tmp_path)[0]
    assert set(entry.candidates) == set(context["candidates"])
    assert not entry.downloaded


@pytest.mark.parametrize("canonical", [False, True])
def test_listing_reads_only_metadata_not_case_results(tmp_path, monkeypatch, canonical):
    context, _, _, _ = damaged_pair(tmp_path, canonical)
    for run in ResultStore(tmp_path).list():
        run.path.write_text("invalid raw result JSON")

    def forbidden(*args, **kwargs):
        raise AssertionError("Listing decoded a raw result")

    monkeypatch.setattr(sf.reports, "_local", forbidden)
    entry = sf.reports.list(directory=tmp_path)[0]
    assert set(entry.candidates) == set(context["candidates"])
    assert entry.downloaded


@pytest.mark.parametrize("payload", ["{", "null", '{"id":"other"}'])
def test_listing_invalid_canonical_metadata_is_a_named_error(tmp_path, payload):
    _, manifest, _, _ = damaged_pair(tmp_path, True)
    manifest.write_text(payload)
    with pytest.raises(sf.ExecutionError) as caught:
        sf.reports.list(directory=tmp_path)
    assert caught.value.code == "result_metadata_invalid"


def test_listing_conflicting_canonical_identity_is_a_named_error(tmp_path):
    context, manifest, _, _ = damaged_pair(tmp_path, True)
    atomic_json(manifest, {**context, "id": "different-evaluation"})
    with pytest.raises(sf.ExecutionError) as caught:
        sf.reports.list(directory=tmp_path)
    assert caught.value.code == "result_metadata_invalid"


def test_listing_unreadable_canonical_manifest_is_a_named_storage_error(tmp_path, monkeypatch):
    _, manifest, _, _ = damaged_pair(tmp_path, True)
    read_text = type(manifest).read_text

    def unreadable(path, *args, **kwargs):
        if path == manifest:
            raise PermissionError("evaluation manifest is unreadable")
        return read_text(path, *args, **kwargs)

    monkeypatch.setattr(type(manifest), "read_text", unreadable)
    with pytest.raises(sf.ExecutionError) as caught:
        sf.reports.list(directory=tmp_path)
    assert caught.value.code == "result_storage_failed"


@pytest.mark.parametrize("canonical", ["valid", "missing", "invalid"])
@pytest.mark.parametrize("lookup", ["evaluation", "damaged", "healthy"])
def test_deletion_removes_every_same_identity_run_and_preserves_other_groups(
    tmp_path, canonical, lookup
):
    context, manifest, damaged, healthy = damaged_pair(tmp_path, canonical != "missing")
    if canonical == "invalid":
        manifest.write_text("invalid canonical JSON")
    store = ResultStore(tmp_path)
    unrelated_context = {**context, "id": "unrelated"}
    unrelated = store.record(
        healthy.engine_url,
        healthy.candidate,
        replace(healthy.outcome, run_id="unrelated-run"),
        unrelated_context,
    )
    unrelated.path.write_bytes(healthy.path.read_bytes())
    other_manifest = tmp_path / "evaluations" / "unrelated.json"
    atomic_json(other_manifest, unrelated_context)
    key = {"evaluation": context["id"], "damaged": damaged.key, "healthy": healthy.key}[lookup]
    sf.reports.delete(key, directory=tmp_path)
    assert not damaged.manifest.parent.exists()
    assert not healthy.manifest.parent.exists()
    assert not manifest.exists()
    assert unrelated.path.exists()
    assert other_manifest.exists()
    assert [run.key for run in store.list()] == [unrelated.key]
