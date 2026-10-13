"""Supported run-ID recovery aliases track both stores before fetching."""

import asyncio
import json
import os

import pytest
from test_saved_runs import saved_fixture

import screamingface as sf
from screamingface import reports
from screamingface._results import recovery_notice
from screamingface._results.store import ResultStore, atomic_json


def _observe_fetch(monkeypatch, markers, cancelled):
    fetch = reports._fetch

    def observed(run):
        # INVARIANT: every supported alias registers both stores before fetch/cancellation.
        for marker in markers:
            value = json.loads(marker.read_text())
            assert (value["state"], value["owner_pid"]) == ("running", os.getpid())
        if cancelled:
            raise asyncio.CancelledError()
        return fetch(run)

    async def observed_async(run):
        return observed(run)

    monkeypatch.setattr(reports, "_fetch", observed)
    monkeypatch.setattr(reports, "_fetch_async", observed_async)

    return fetch


@pytest.mark.parametrize("asynchronous", [False, True])
@pytest.mark.parametrize("cancelled", [False, True])
@pytest.mark.asyncio
async def test_run_id_recovery_tracks_source_and_destination(
    tmp_path, monkeypatch, asynchronous, cancelled
):
    original, saved = saved_fixture(tmp_path, 3)
    assert saved.evaluation is not None
    source = tmp_path / "evaluations/evaluation.json"
    destination = tmp_path / "copied"
    target = destination / "evaluations/evaluation.json"
    atomic_json(
        source,
        {**saved.evaluation, "state": "ready" if cancelled else "exporting", "owner_pid": 99999999},
    )
    fetch = _observe_fetch(monkeypatch, (source, target), cancelled)

    async def recover():
        if asynchronous:
            return await reports.get_async(
                saved.outcome.run_id, directory=tmp_path, destination=destination
            )
        return reports.get(saved.outcome.run_id, directory=tmp_path, destination=destination)

    if cancelled:
        with pytest.raises(asyncio.CancelledError):
            await recover()
    else:
        assert (await recover()).to_json() == original.to_json()
    monkeypatch.setattr(recovery_notice, "_owner_alive", lambda pid: False)
    for marker in (source, target):
        value = json.loads(marker.read_text())
        assert (value["state"], value["owner_pid"]) == (
            "running" if cancelled else "ready",
            os.getpid(),
        )
        assert recovery_notice._is_interrupted(value) is cancelled
    if not cancelled:
        monkeypatch.setattr(reports, "_fetch", fetch)
        assert sf.reports.get("evaluation", directory=destination).to_json() == original.to_json()


@pytest.mark.parametrize("asynchronous", [False, True])
@pytest.mark.parametrize("ambiguous", [False, True])
@pytest.mark.asyncio
async def test_run_id_lifecycle_preserves_unresolvable_alias_errors(
    tmp_path, asynchronous, ambiguous
):
    _, saved = saved_fixture(tmp_path, 3)
    if ambiguous:
        duplicate = tmp_path / ("a" * 64) / "run.json"
        atomic_json(duplicate, json.loads(saved.manifest.read_text()))
    lookup = saved.outcome.run_id if ambiguous else "missing-run"
    destination = tmp_path / "copied"
    with pytest.raises(KeyError):
        if asynchronous:
            await reports.get_async(lookup, directory=tmp_path, destination=destination)
        else:
            reports.get(lookup, directory=tmp_path, destination=destination)
    assert not (destination / "evaluations").exists()
    assert len(ResultStore(tmp_path).list()) == (2 if ambiguous else 1)
