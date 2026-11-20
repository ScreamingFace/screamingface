"""Completion, recovery and serialization regressions from the PR review."""

import asyncio
import hashlib
from contextlib import closing
from dataclasses import replace
from pathlib import Path

import pytest
from _run_engine import AsyncCollectingSink, CollectingSink, one_candidate, run_engine
from test_saved_runs import saved_fixture
from test_transport_artifact_fetch import _candidate

import screamingface as sf
from screamingface._core.ports import _ResultArtifact
from screamingface._engine.transport import AsyncUrl4CloudTransport, Url4CloudTransport
from screamingface._evaluation.model import (
    _compiled_candidate,
    _model_parameter_assignment,
)
from screamingface._results.store import ResultStore


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
    script, results = one_candidate(b'{"cases":[]}')

    async def run(url):
        transport = AsyncUrl4CloudTransport(url, save_results=True)
        sink = AsyncCollectingSink()
        try:
            run_id = await transport.register_run(None, (parameterized(),))
            await transport.follow_run(run_id, (parameterized(),), sink)
        finally:
            await transport.close()
        return sink.outcomes[0]

    with run_engine(script, results) as engine:
        if asynchronous:
            result = asyncio.run(run(engine.url))
        else:
            sink = CollectingSink()
            with closing(Url4CloudTransport(engine.url, save_results=True)) as transport:
                run_id = transport.register_run(None, (parameterized(),))
                transport.follow_run(run_id, (parameterized(),), sink)
            result = sink.outcomes[0]
    saved = ResultStore(tmp_path).list()
    assert len(saved) == 1
    assert saved[0].outcome.run_id == result.run_id
    assert saved[0].path.read_text() == '{"cases":[]}'
    assert saved[0].candidate.url4 == parameterized().url4
    assert saved[0].candidate.parameter_assignments == ()


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
