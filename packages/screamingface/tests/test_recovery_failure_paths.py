"""Recovery membership and per-candidate failures preserve paid results."""

import asyncio
import errno
from dataclasses import replace
from typing import Any, cast

import httpx
import pytest
from _run_transport import AsyncPlaying, ScriptedRun
from test_client_run import _engine as catalog_engine
from test_evaluation_outcome import valid_outcome
from test_transport_artifact_fetch import _candidate

import screamingface as sf
from screamingface._engine import transport as transport_module
from screamingface._evaluation.model import _compiled_candidate, _compiled_evaluation
from screamingface._results.store import ResultStore
from screamingface.discovery import BenchmarkInfo


def prepared_transport(tmp_path, monkeypatch, asynchronous):
    monkeypatch.setenv("SCREAMINGFACE_RESULTS_DIR", str(tmp_path))
    adapter = (
        transport_module.AsyncUrl4CloudTransport
        if asynchronous
        else transport_module.Url4CloudTransport
    )
    transport = adapter("https://engine.example", save_results=True)
    selected = _candidate()
    evaluation = _compiled_evaluation(
        benchmark=BenchmarkInfo("draco", "fixture-revision", 1),
        limit=None,
        case_count=1,
        candidates=(selected,),
        required_models=selected.models,
    )
    # WHY: deterministic identity collision avoids allocator-dependent timing while
    # exercising the actual preparation, failed-run, save and recovery boundaries.
    monkeypatch.setattr(transport_module, "id", lambda _: 42, raising=False)
    from screamingface._results import evaluation as saved_evaluation

    monkeypatch.setattr(saved_evaluation, "id", lambda _: 42, raising=False)
    transport.prepare_results(evaluation, (selected,))
    return transport, selected


def refuse_mint(*args, **kwargs):
    raise sf.ExecutionError("admission failed")


def standalone_outcome():
    return valid_outcome("standalone")


def _standalone(selected):
    return _compiled_candidate(
        name="standalone",
        kind=selected.kind,
        models=selected.models,
        url4=selected.url4,
        operations=selected.operations,
    )


def _evaluation_of(selected):
    return _compiled_evaluation(
        benchmark=BenchmarkInfo("draco", "fixture-revision", 1),
        limit=None,
        case_count=1,
        candidates=(selected,),
        required_models=selected.models,
    )


_FAILURES = {
    "follow": sf.ExecutionError("the follow failed"),
    "cancelled": asyncio.CancelledError(),
}


@pytest.mark.parametrize("failure", ["follow", "cancelled"])
def test_failed_sync_membership_cannot_poison_later_standalone(tmp_path, monkeypatch, failure):
    from screamingface._evaluation.runner import _prepared_results

    value, selected = prepared_transport(tmp_path, monkeypatch, False)
    transport = cast(transport_module.Url4CloudTransport, value)
    try:
        # The evaluation ends with its follow failing, inside the runner's own boundary.
        with pytest.raises(type(_FAILURES[failure])):
            with _prepared_results(transport, _evaluation_of(selected), (selected,)):
                raise _FAILURES[failure]
        assert not transport._result_contexts
        transport._save_result(_standalone(selected), standalone_outcome())
        saved = ResultStore(tmp_path).list()[0]
        assert saved.evaluation is None
        assert sf.reports.get(saved.key, directory=tmp_path).candidates[0].name == "standalone"
    finally:
        transport.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["follow", "cancelled"])
async def test_failed_async_membership_cannot_poison_later_standalone(
    tmp_path, monkeypatch, failure
):
    from screamingface._evaluation.runner import _prepared_results

    value, selected = prepared_transport(tmp_path, monkeypatch, True)
    transport = cast(transport_module.AsyncUrl4CloudTransport, value)
    try:
        with pytest.raises(type(_FAILURES[failure])):
            with _prepared_results(transport, _evaluation_of(selected), (selected,)):
                raise _FAILURES[failure]
        assert not transport._result_contexts
        await transport._save_result(_standalone(selected), standalone_outcome())
        saved = ResultStore(tmp_path).list()[0]
        assert saved.evaluation is None
        assert (await sf.reports.get_async(saved.key, directory=tmp_path)).candidates[
            0
        ].name == "standalone"
    finally:
        await transport.close()


class DiskTransport(ScriptedRun):
    def __init__(self, directory):
        super().__init__()
        self.directory = directory

    def run(self, candidate, on_event):
        value = valid_outcome(candidate.name)
        path = self.directory / f"{candidate.name}.json"
        path.write_text(value.result_body)
        return replace(value, result_body=None, result_path=path)


class AsyncDiskTransport(AsyncPlaying):
    def __init__(self, directory):
        super().__init__(DiskTransport(directory))


def indexing_failure(monkeypatch):
    from screamingface._results import cases

    original = cases.index_result

    def index(path):
        if path.name == "bad.json":
            raise OSError(errno.ENOSPC, "index disk full")
        return original(path)

    monkeypatch.setattr(cases, "index_result", index)


def assert_healthy_partial(error):
    assert error.code == "candidates_failed"
    assert error.details == {"failed": {"bad": "result_storage_failed"}}
    assert error.partial_report is not None
    assert [c.name for c in error.partial_report.candidates] == ["ok"]
    assert error.partial_report.candidates[0].cases[0].output == "Answer"


@pytest.mark.parametrize("order", [("ok", "bad"), ("bad", "ok")])
def test_sync_indexing_failure_preserves_healthy_completed_sibling(tmp_path, monkeypatch, order):
    indexing_failure(monkeypatch)
    with sf.Client(
        engine_url="https://engine.example",
        http_transport=httpx.MockTransport(catalog_engine),
        run_transport=DiskTransport(tmp_path),
    ) as client:
        with pytest.raises(sf.ExecutionError) as error:
            client.evaluate(
                [sf.Model("provider/opus", name=name) for name in order],
                benchmark="draco",
                progress=False,
            )
    assert_healthy_partial(error.value)


@pytest.mark.asyncio
@pytest.mark.parametrize("order", [("ok", "bad"), ("bad", "ok")])
async def test_async_indexing_failure_preserves_healthy_completed_sibling(
    tmp_path, monkeypatch, order
):
    indexing_failure(monkeypatch)
    async with sf.AsyncClient(
        engine_url="https://engine.example",
        http_transport=httpx.MockTransport(catalog_engine),
        run_transport=AsyncDiskTransport(tmp_path),
    ) as client:
        with pytest.raises(sf.ExecutionError) as error:
            await client.evaluate(
                [sf.Model("provider/opus", name=name) for name in order],
                benchmark="draco",
                progress=False,
            )
    assert_healthy_partial(error.value)


@pytest.mark.asyncio
@pytest.mark.parametrize("asynchronous", [False, True])
async def test_unstarted_membership_cannot_attach_to_distinct_candidate(
    tmp_path, monkeypatch, asynchronous
):
    transport, selected = prepared_transport(tmp_path, monkeypatch, asynchronous)
    standalone = _compiled_candidate(
        name="standalone",
        kind=selected.kind,
        models=selected.models,
        url4=selected.url4,
        operations=selected.operations,
    )
    try:
        if isinstance(transport, transport_module.AsyncUrl4CloudTransport):
            await transport._save_result(standalone, standalone_outcome())
        else:
            transport._save_result(standalone, standalone_outcome())
        saved = ResultStore(tmp_path).list()[0]
        assert saved.evaluation is None
        assert sf.reports.get(saved.key, directory=tmp_path).candidates[0].name == "standalone"
    finally:
        if isinstance(transport, transport_module.AsyncUrl4CloudTransport):
            await transport.close()
        else:
            transport.close()


def test_all_completed_candidates_with_invalid_results_are_named(tmp_path, monkeypatch):
    indexing_failure(monkeypatch)
    with sf.Client(
        engine_url="https://engine.example",
        http_transport=httpx.MockTransport(catalog_engine),
        run_transport=DiskTransport(tmp_path),
    ) as client:
        with pytest.raises(sf.ExecutionError) as error:
            client.evaluate(
                sf.Model("provider/opus", name="bad"), benchmark="draco", progress=False
            )
    assert error.value.code == "candidates_failed"
    assert error.value.details == {"failed": {"bad": "result_storage_failed"}}
    assert error.value.partial_report is None
    assert isinstance(error.value.__cause__, sf.ExecutionError)
    assert error.value.__cause__.code == "result_storage_failed"


@pytest.mark.asyncio
@pytest.mark.parametrize("unrelated", [False, True])
async def test_cancelled_evaluation_releases_candidates_waiting_for_capacity(
    tmp_path, monkeypatch, unrelated
):
    """A cancelled evaluation whose Candidates wait for capacity cancels its Run and releases
    every Candidate's membership; another evaluation's stays (E5 P2 spec D14)."""
    from _run_engine import RUN_ID, run_engine, state

    monkeypatch.setenv("SCREAMINGFACE_RESULTS_DIR", str(tmp_path))
    script = [[*(state(index, "pending") for index in range(9)), "hold"]]
    with run_engine(script, {}) as engine:
        transport = transport_module.AsyncUrl4CloudTransport(engine.url, save_results=True)
        other = _candidate()
        if unrelated:
            transport.prepare_results(_evaluation_of(other), (other,))
        async with sf.AsyncClient(
            engine_url=engine.url,
            http_transport=httpx.MockTransport(catalog_engine),
            run_transport=cast(Any, transport),
        ) as client:
            task = asyncio.create_task(
                client.evaluate(
                    [sf.Model("provider/opus", name=str(index)) for index in range(9)],
                    benchmark="draco",
                    progress=False,
                )
            )
            try:
                assert await asyncio.to_thread(engine.state.holding.wait, 5)
            finally:
                task.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await task
            assert set(transport._result_contexts) == ({id(other)} if unrelated else set())

    assert engine.state.deleted == [f"/runs/{RUN_ID}"]
