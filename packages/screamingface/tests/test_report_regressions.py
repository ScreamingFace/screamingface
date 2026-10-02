"""Adversarial recovery checks beyond the normal report fixtures."""

import json
import os
from dataclasses import replace

import pytest
from test_saved_runs import saved_fixture

import screamingface as sf
from screamingface._evaluation.model import _compiled_candidate
from screamingface._results.store import ResultStore, atomic_json


@pytest.mark.parametrize("asynchronous", [False, True])
@pytest.mark.asyncio
async def test_limited_evaluation_recovers(tmp_path, asynchronous):
    _, saved = saved_fixture(tmp_path, 3)
    assert saved.evaluation is not None
    context = dict(saved.evaluation)
    context["benchmark"] = {**context["benchmark"], "case_count": 100}
    ResultStore(tmp_path).record(saved.engine_url, saved.candidate, saved.outcome, context)
    report = (
        await sf.reports.get_async("evaluation", directory=tmp_path)
        if asynchronous
        else sf.reports.get("evaluation", directory=tmp_path)
    )
    assert report.case_count == 3
    assert report.benchmark.case_count == 100
    assert len(report.candidates[0].cases) == 3


@pytest.mark.parametrize("damaged", ["{", '{"schema":"screamingface.saved-run.v2"}'])
def test_unrelated_invalid_manifest_does_not_block_recovery(tmp_path, damaged):
    original, saved = saved_fixture(tmp_path, 3)
    broken = tmp_path / ("f" * 64) / "run.json"
    broken.parent.mkdir()
    broken.write_text(damaged)
    assert sf.reports.get(saved.key, directory=tmp_path).to_json() == original.to_json()
    assert len(sf.reports.list(directory=tmp_path)) == 1
    with pytest.raises(sf.ExecutionError):
        sf.reports.get("f" * 64, directory=tmp_path)
    sf.reports.delete(saved.key, directory=tmp_path)
    assert broken.read_text() == damaged


def test_interrupted_group_recovery_retains_pending_marker(tmp_path, monkeypatch):
    _, saved = saved_fixture(tmp_path, 3, expected=["model", "second"])
    second = ResultStore(tmp_path).record(
        saved.engine_url,
        _compiled_candidate(
            name="second",
            kind=saved.candidate.kind,
            models=saved.candidate.models,
            url4=saved.candidate.url4,
            operations=saved.candidate.operations,
        ),
        replace(saved.outcome, run_id="second"),
        saved.evaluation,
    )
    second.path.write_bytes(saved.path.read_bytes())
    marker = tmp_path / "evaluations" / "evaluation.json"
    atomic_json(marker, {"state": "ready", "owner_pid": 99999999})
    decode = sf.reports._decode
    seen = []

    def stop_on_second(run, outcome):
        seen.append(run.candidate.name)
        if len(seen) == 2:
            assert json.loads(marker.read_text())["state"] == "running"
            raise SystemExit(73)
        return decode(run, outcome)

    monkeypatch.setattr(sf.reports, "_decode", stop_on_second)
    with pytest.raises(SystemExit):
        sf.reports.get("evaluation", directory=tmp_path)
    pending = json.loads(marker.read_text())
    assert pending == {"state": "running", "owner_pid": os.getpid()}
    monkeypatch.setattr(sf.reports, "_decode", decode)
    assert len(sf.reports.get("evaluation", directory=tmp_path).candidates) == 2
    assert json.loads(marker.read_text())["state"] == "ready"


@pytest.mark.asyncio
async def test_async_recovery_moves_disk_work_off_event_loop(tmp_path, monkeypatch):
    import threading

    original, saved = saved_fixture(tmp_path, 3)
    loop_thread = threading.get_ident()
    threads = []
    local, decode = sf.reports._local, sf.reports._decode

    def check_local(run):
        threads.append(threading.get_ident())
        return local(run)

    def check_decode(run, outcome):
        threads.append(threading.get_ident())
        return decode(run, outcome)

    monkeypatch.setattr(sf.reports, "_local", check_local)
    monkeypatch.setattr(sf.reports, "_decode", check_decode)
    report = await sf.reports.get_async(
        saved.key, directory=tmp_path, destination=tmp_path / "copy"
    )
    assert report.to_json() == original.to_json()
    assert len(threads) == 2
    assert all(thread != loop_thread for thread in threads)


def test_invalid_sibling_is_reported_as_incomplete(tmp_path):
    _, saved = saved_fixture(tmp_path, 3, expected=["model", "second"])
    second = ResultStore(tmp_path).record(
        saved.engine_url,
        _compiled_candidate(
            name="second",
            kind=saved.candidate.kind,
            models=saved.candidate.models,
            url4=saved.candidate.url4,
            operations=saved.candidate.operations,
        ),
        replace(saved.outcome, run_id="second"),
        saved.evaluation,
    )
    second.manifest.write_text("{")
    with pytest.raises(sf.ExecutionError) as error:
        sf.reports.get("evaluation", directory=tmp_path)
    assert error.value.code == "candidates_failed"
    assert error.value.details == {"failed": {"second": "result_not_received"}}
    assert error.value.partial_report is not None
    assert error.value.partial_report.candidates[0].name == "model"
