"""Completion, recovery and serialization regressions from the PR review."""

import asyncio
import hashlib
import json
from contextlib import closing
from dataclasses import replace
from pathlib import Path

import pytest
from protocol_server import protocol_server
from test_saved_runs import saved_fixture
from test_transport_artifact_fetch import _candidate

import screamingface as sf
from screamingface._core.ports import _ResultArtifact
from screamingface._engine.transport import AsyncUrl4CloudTransport, Url4CloudTransport
from screamingface._evaluation.model import (
    _compiled_candidate,
    _compiled_evaluation,
    _model_parameter_assignment,
)
from screamingface._results.store import ResultStore, atomic_json


def parameterized():
    source = _candidate()
    return _compiled_candidate(
        name=source.name,
        kind=source.kind,
        models=source.models,
        url4=source.url4,
        operations=source.operations,
        parameter_assignments=[
            _model_parameter_assignment(
                operation_id=source.operations[0].id,
                model=source.models[0],
                params={"temperature": 0.0, "max_tokens": 8192},
            )
        ],
    )


@pytest.mark.parametrize("asynchronous", [False, True])
def test_parameterized_transport_retains_completed_ticket(tmp_path, monkeypatch, asynchronous):
    monkeypatch.setenv("SCREAMINGFACE_RESULTS_DIR", str(tmp_path))

    async def run(url):
        transport = AsyncUrl4CloudTransport(url)
        try:
            return await transport.run(parameterized(), None)
        finally:
            await transport.close()

    with protocol_server(mode="artifact_result", artifact_body='{"cases":[]}') as engine:
        if asynchronous:
            result = asyncio.run(run(engine.url))
        else:
            with closing(Url4CloudTransport(engine.url)) as transport:
                result = transport.run(parameterized(), None)
    saved = ResultStore(tmp_path).list()
    assert len(saved) == 1
    assert saved[0].outcome.run_id == result.run_id
    assert saved[0].path.read_text() == '{"cases":[]}'
    assert saved[0].candidate.url4 == parameterized().url4
    assert saved[0].candidate.parameter_assignments == ()


def test_progress_completion_keeps_unfinished_evaluation_pending(tmp_path):
    from screamingface._evaluation.completion import completion_callback

    original, saved = saved_fixture(tmp_path, 3, expected=["model", "unfinished"])
    marker = tmp_path / "evaluations/evaluation.json"
    atomic_json(marker, {"state": "running", "owner_pid": 99999999})
    evaluation = _compiled_evaluation(
        benchmark=original.benchmark,
        limit=None,
        case_count=3,
        candidates=[saved.candidate],
        required_models=saved.candidate.models,
    )
    seen = []

    class Observer:
        candidate_result = staticmethod(seen.append)

    complete = completion_callback(evaluation, Observer())
    assert complete is not None
    complete(saved.candidate, replace(saved.outcome, result_body=None, result_path=saved.path))
    assert len(seen) == 1
    assert json.loads(marker.read_text())["state"] == "running"


def pair(tmp_path):
    original, saved = saved_fixture(tmp_path, 3, expected=["model", "second"])
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
    return original, saved, second


@pytest.mark.parametrize("asynchronous", [False, True])
@pytest.mark.asyncio
async def test_unreadable_sibling_returns_healthy_partial_report(
    tmp_path, monkeypatch, asynchronous
):
    _, saved, second = pair(tmp_path)
    payload = second.path.read_bytes()
    ResultStore(tmp_path).record(
        second.engine_url,
        second.candidate,
        replace(
            second.outcome,
            artifact=_ResultArtifact("a" * 64, len(payload), hashlib.sha256(payload).hexdigest()),
        ),
        second.evaluation,
    )
    open_file = Path.open

    def unreadable(path, *args, **kwargs):
        if path == second.path:
            raise PermissionError("unreadable result")
        return open_file(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", unreadable)
    with pytest.raises(sf.ExecutionError) as error:
        if asynchronous:
            await sf.reports.get_async(saved.key, directory=tmp_path)
        else:
            sf.reports.get(saved.key, directory=tmp_path)
    assert error.value.code == "candidates_failed"
    assert error.value.partial_report is not None
    assert [c.name for c in error.value.partial_report.candidates] == ["model"]
    assert error.value.details == {
        "failed": {"second": "result_storage_failed"},
        "failure_messages": {"second": str(error.value.__cause__)},
    }


@pytest.mark.parametrize("asynchronous", [False, True])
@pytest.mark.asyncio
async def test_destination_recovery_updates_both_lifecycle_records(tmp_path, asynchronous):
    _, saved = saved_fixture(tmp_path / "source", 3)
    marker = saved.path.parent.parent / "evaluations/evaluation.json"
    atomic_json(marker, {"state": "running", "owner_pid": 99999999})
    destination = tmp_path / "destination"
    if asynchronous:
        await sf.reports.get_async(
            saved.key, directory=marker.parent.parent, destination=destination
        )
    else:
        sf.reports.get(saved.key, directory=marker.parent.parent, destination=destination)
    assert json.loads(marker.read_text())["state"] == "ready"
    assert json.loads((destination / "evaluations/evaluation.json").read_text())["state"] == "ready"


def test_crash_after_progress_completion_is_discoverable(tmp_path):
    import os
    import subprocess
    import sys

    from screamingface._results.recovery_notice import _is_interrupted

    _, saved = saved_fixture(tmp_path, 3, expected=["model", "unfinished"])
    marker = tmp_path / "evaluations/evaluation.json"
    atomic_json(marker, {"state": "running", "owner_pid": os.getpid()})
    script = """
import os, sys
from dataclasses import replace
from pathlib import Path
from screamingface._results.store import ResultStore, atomic_json
from screamingface._evaluation.completion import completion_callback
from screamingface._evaluation.model import _compiled_evaluation
from screamingface.discovery import BenchmarkInfo
store = ResultStore(Path(sys.argv[1]))
run = store.load(sys.argv[2])
atomic_json(store.directory / 'evaluations/evaluation.json',
    {'state':'running', 'owner_pid':os.getpid()})
evaluation = _compiled_evaluation(
    benchmark=BenchmarkInfo(**run.evaluation['benchmark']), limit=None,
    case_count=3, candidates=[run.candidate], required_models=run.candidate.models)
class Observer:
    def candidate_result(self, result): pass
completion_callback(evaluation, Observer())(
    run.candidate, replace(run.outcome, result_path=run.path))
os._exit(73)
"""
    child = subprocess.run([sys.executable, "-c", script, str(tmp_path), saved.key], check=False)
    assert child.returncode == 73
    assert _is_interrupted(json.loads(marker.read_text()))


@pytest.mark.parametrize("asynchronous", [False, True])
@pytest.mark.asyncio
async def test_interruption_between_recovery_fetches_stays_pending(
    tmp_path, monkeypatch, asynchronous
):
    _, saved, _ = pair(tmp_path)
    marker = tmp_path / "evaluations/evaluation.json"
    atomic_json(marker, {"state": "ready", "owner_pid": 99999999})
    fetch = sf.reports._fetch
    seen = []

    def interrupted(run):
        seen.append(run.candidate.name)
        if len(seen) == 2:
            assert json.loads(marker.read_text())["state"] == "running"
            raise SystemExit(74)
        return fetch(run)

    async def interrupted_async(run):
        return interrupted(run)

    monkeypatch.setattr(sf.reports, "_fetch", interrupted)
    monkeypatch.setattr(sf.reports, "_fetch_async", interrupted_async)
    with pytest.raises(SystemExit):
        if asynchronous:
            await sf.reports.get_async(saved.key, directory=tmp_path)
        else:
            sf.reports.get(saved.key, directory=tmp_path)
    assert json.loads(marker.read_text())["state"] == "running"
