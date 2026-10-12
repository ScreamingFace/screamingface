"""Corrupt saved metadata cannot poison healthy recovery or evade deletion."""

import json
from dataclasses import replace

import pytest
from test_persistence_followup import pair

import screamingface as sf
from screamingface._results.store import ResultStore, atomic_json


def corrupt_pair(directory, defect):
    original, healthy, damaged = pair(directory)
    assert healthy.evaluation is not None
    atomic_json(directory / "evaluations" / "evaluation.json", healthy.evaluation)
    payload = json.loads(damaged.manifest.read_text())
    if defect == "root_cost":
        payload["outcome"]["root_usage"]["cost_usd"] = "broken"
    elif defect.startswith("cache_"):
        payload["outcome"][defect] = "broken"
    else:
        payload["evaluation"][defect] = None
    atomic_json(damaged.manifest, payload)
    return original, healthy, damaged


COST_FIELDS = ["cache_saved_cost_usd", "cache_saved_cost_archive_usd", "root_cost"]


@pytest.mark.parametrize("defect", COST_FIELDS)
def test_corrupt_cost_discovery_preserves_unrelated_report(tmp_path, defect):
    _, healthy, _ = corrupt_pair(tmp_path, defect)
    assert healthy.evaluation is not None
    other = ResultStore(tmp_path).record(
        healthy.engine_url,
        healthy.candidate,
        replace(healthy.outcome, run_id="unrelated"),
        {**healthy.evaluation, "id": "unrelated", "candidates": ["model"]},
    )
    other.path.write_bytes(healthy.path.read_bytes())
    entries = {entry.id: entry for entry in sf.reports.list(directory=tmp_path)}
    assert set(entries) == {"evaluation", "unrelated"}
    assert not entries["evaluation"].downloaded
    assert entries["unrelated"].downloaded
    assert sf.reports.get("unrelated", directory=tmp_path).candidates[0].name == "model"


@pytest.mark.parametrize("defect", COST_FIELDS + ["candidates"])
@pytest.mark.parametrize("asynchronous", [False, True])
@pytest.mark.asyncio
async def test_corrupt_sibling_metadata_has_named_failure_and_healthy_partial(
    tmp_path, defect, asynchronous
):
    original, healthy, _ = corrupt_pair(tmp_path, defect)
    with pytest.raises(sf.ExecutionError) as caught:
        if asynchronous:
            await sf.reports.get_async(healthy.key, directory=tmp_path)
        else:
            sf.reports.get(healthy.key, directory=tmp_path)
    assert caught.value.code == "candidates_failed"
    assert isinstance(caught.value.details, dict)
    assert caught.value.details["failed"] == {"second": "result_metadata_invalid"}
    partial = caught.value.partial_report
    assert partial is not None
    assert [candidate.name for candidate in partial.candidates] == ["model"]
    assert partial.candidates[0].to_dict() == original.candidates[0].to_dict()


@pytest.mark.parametrize("defect", COST_FIELDS)
def test_corrupt_cost_saved_key_is_named_metadata_error(tmp_path, defect):
    _, _, damaged = corrupt_pair(tmp_path, defect)
    with pytest.raises(sf.ExecutionError) as caught:
        sf.reports.get(damaged.key, directory=tmp_path)
    assert caught.value.code == "result_metadata_invalid"


@pytest.mark.parametrize("defect", COST_FIELDS + ["candidates", "case_count", "benchmark"])
@pytest.mark.parametrize("lookup", ["evaluation", "healthy", "damaged"])
def test_delete_removes_corrupt_members_and_preserves_unrelated(tmp_path, defect, lookup):
    _, healthy, damaged = corrupt_pair(tmp_path, defect)
    assert healthy.evaluation is not None
    other = ResultStore(tmp_path).record(
        healthy.engine_url,
        healthy.candidate,
        replace(healthy.outcome, run_id="unrelated"),
        {**healthy.evaluation, "id": "unrelated", "candidates": ["model"]},
    )
    other.path.write_bytes(healthy.path.read_bytes())
    key = {"evaluation": "evaluation", "healthy": healthy.key, "damaged": damaged.key}[lookup]
    sf.reports.delete(key, directory=tmp_path)
    assert not healthy.manifest.parent.exists()
    assert not damaged.manifest.parent.exists()
    assert not (tmp_path / "evaluations" / "evaluation.json").exists()
    assert other.path.exists()
    assert [entry.id for entry in sf.reports.list(directory=tmp_path)] == ["unrelated"]


def test_delete_public_id_when_all_memberships_are_undecodable(tmp_path):
    _, healthy, damaged = corrupt_pair(tmp_path, "candidates")
    payload = json.loads(healthy.manifest.read_text())
    payload["evaluation"]["candidates"] = None
    atomic_json(healthy.manifest, payload)
    sf.reports.delete("evaluation", directory=tmp_path)
    assert not healthy.manifest.parent.exists()
    assert not damaged.manifest.parent.exists()


def test_delete_corrupt_key_cannot_redirect_manifest_unlink(tmp_path):
    _, _, damaged = corrupt_pair(tmp_path / "results", "candidates")
    outside = tmp_path / "outside.json"
    outside.write_text("preserve")
    payload = json.loads(damaged.manifest.read_text())
    payload["evaluation"]["id"] = "../../outside"
    atomic_json(damaged.manifest, payload)
    sf.reports.delete(damaged.key, directory=tmp_path / "results")
    assert not damaged.manifest.parent.exists()
    assert outside.read_text() == "preserve"
