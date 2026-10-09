"""Damaged membership and overlapping presentation must preserve recovery."""

import json

import pytest
from test_persistence_followup import pair
from test_saved_runs import saved_fixture

import screamingface as sf
from screamingface._results.store import ResultStore


def change_membership(run, field, value):
    payload = json.loads(run.manifest.read_text())
    payload["evaluation"][field] = value
    run.manifest.write_text(json.dumps(payload))


@pytest.mark.parametrize(
    "field,value",
    [
        ("id", None),
        ("id", "../outside"),
        ("candidates", "model"),
        ("candidates", []),
        ("candidates", ["model", "model"]),
        ("case_count", "invalid"),
        ("case_count", True),
        ("case_count", 100),
        ("benchmark", {}),
    ],
)
def test_invalid_membership_isolated_before_grouping(tmp_path, field, value):
    _, first, second = pair(tmp_path)
    change_membership(second, field, value)
    runs = ResultStore(tmp_path).list()
    assert [run.key for run in runs] == [first.key]
    with pytest.raises(sf.ExecutionError) as error:
        sf.reports.get(second.key, directory=tmp_path)
    assert error.value.code == "result_metadata_invalid"
    with pytest.raises(sf.ExecutionError) as error:
        sf.reports.get(first.key, directory=tmp_path)
    assert error.value.code == "candidates_failed"
    assert error.value.partial_report is not None
    assert error.value.partial_report.candidates[0].name == "model"


def test_unrelated_missing_membership_id_does_not_poison_recovery(tmp_path):
    original, first = saved_fixture(tmp_path, 3)
    unrelated = tmp_path / ("f" * 64) / "run.json"
    unrelated.parent.mkdir()
    payload = json.loads(first.manifest.read_text())
    payload["evaluation"].pop("id")
    unrelated.write_text(json.dumps(payload))
    assert sf.reports.get(first.key, directory=tmp_path).to_json() == original.to_json()


@pytest.mark.asyncio
async def test_invalid_sibling_async_recovery_returns_healthy_partial(tmp_path):
    _, first, second = pair(tmp_path)
    change_membership(second, "case_count", "invalid")
    with pytest.raises(sf.ExecutionError) as error:
        await sf.reports.get_async(first.key, directory=tmp_path)
    assert error.value.code == "candidates_failed"
    assert error.value.partial_report is not None
    assert error.value.partial_report.candidates[0].name == "model"


def test_incomplete_legacy_membership_recovery_is_structured(tmp_path):
    _, run = saved_fixture(tmp_path, 3)
    payload = json.loads(run.manifest.read_text())
    payload["evaluation"].pop("benchmark")
    run.manifest.write_text(json.dumps(payload))
    assert len(ResultStore(tmp_path).list()) == 1
    with pytest.raises(sf.ExecutionError) as error:
        sf.reports.get(run.key, directory=tmp_path)
    assert isinstance(error.value.details, dict)
    failed = error.value.details["failed"]
    assert isinstance(failed, dict)
    assert failed == {"model": "result_metadata_invalid"}
