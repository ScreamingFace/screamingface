"""Paid-result failure paths keep recovery, retries and status usable."""

import asyncio
import errno
import json
from dataclasses import replace
from typing import cast
from unittest.mock import AsyncMock

import httpx
import pytest
from test_client_run import _engine as catalog_engine
from test_evaluation_outcome import valid_outcome
from test_report_browser import large_report
from test_transport_artifact_fetch import _candidate

import screamingface as sf
from screamingface._engine import transport as transport_module
from screamingface._engine.trace import new_trace_context
from screamingface._evaluation.model import _compiled_candidate, _compiled_evaluation
from screamingface._results.store import ResultStore
from screamingface._ui.report_browser import ReportBrowser
from screamingface.discovery import BenchmarkInfo


def prepared_transport(tmp_path, monkeypatch, asynchronous):
    monkeypatch.setenv("SCREAMINGFACE_RESULTS_DIR", str(tmp_path))
    adapter = (
        transport_module.AsyncUrl4CloudTransport
        if asynchronous
        else transport_module.Url4CloudTransport
    )
    transport = adapter("https://engine.example")
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


@pytest.mark.parametrize("failure", ["admission", "run"])
def test_failed_sync_membership_cannot_poison_later_standalone(tmp_path, monkeypatch, failure):
    value, selected = prepared_transport(tmp_path, monkeypatch, False)
    transport = cast(transport_module.Url4CloudTransport, value)
    try:
        monkeypatch.setattr(
            transport_module,
            "_mint_sync",
            refuse_mint if failure == "admission" else lambda *a, **k: "token",
        )
        monkeypatch.setattr(transport, "_run_reconnecting", refuse_mint)
        with pytest.raises(sf.ExecutionError):
            transport.run(selected, None)
        assert not transport._result_contexts
        standalone = _compiled_candidate(
            name="standalone",
            kind=selected.kind,
            models=selected.models,
            url4=selected.url4,
            operations=selected.operations,
        )
        transport._save_result(standalone, standalone_outcome(), new_trace_context())
        saved = ResultStore(tmp_path).list()[0]
        assert saved.evaluation is None
        assert sf.reports.get(saved.key, directory=tmp_path).candidates[0].name == "standalone"
    finally:
        transport.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["admission", "run", "cancelled"])
async def test_failed_async_membership_cannot_poison_later_standalone(
    tmp_path, monkeypatch, failure
):
    value, selected = prepared_transport(tmp_path, monkeypatch, True)
    transport = cast(transport_module.AsyncUrl4CloudTransport, value)

    async def mint(*args, **kwargs):
        if failure == "admission":
            refuse_mint()
        return "token"

    async def run(*args, **kwargs):
        if failure == "cancelled":
            raise asyncio.CancelledError
        refuse_mint()

    try:
        monkeypatch.setattr(transport_module, "_mint_async", mint)
        monkeypatch.setattr(transport, "_run_reconnecting", run)
        expected = asyncio.CancelledError if failure == "cancelled" else sf.ExecutionError
        with pytest.raises(expected):
            await transport.run(selected, None)
        assert not transport._result_contexts
        standalone = _compiled_candidate(
            name="standalone",
            kind=selected.kind,
            models=selected.models,
            url4=selected.url4,
            operations=selected.operations,
        )
        await transport._save_result(standalone, standalone_outcome(), new_trace_context())
        saved = ResultStore(tmp_path).list()[0]
        assert saved.evaluation is None
        assert (await sf.reports.get_async(saved.key, directory=tmp_path)).candidates[
            0
        ].name == "standalone"
    finally:
        await transport.close()


class DiskTransport:
    def __init__(self, directory):
        self.directory = directory

    def run(self, candidate, on_event):
        value = valid_outcome(candidate.name)
        path = self.directory / f"{candidate.name}.json"
        path.write_text(value.result_body)
        return replace(value, result_body=None, result_path=path)

    def cancel_active(self):
        pass

    def close(self):
        pass


class AsyncDiskTransport(DiskTransport):
    async def run(self, candidate, on_event):
        return super().run(candidate, on_event)

    async def cancel_active(self):
        pass

    async def close(self):
        pass


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


def failed_snapshot(tmp_path, monkeypatch):
    from screamingface import _atomic_file

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        "screamingface._ui.report_files._served_url", lambda path: "/files/report.json"
    )
    browser = ReportBrowser(large_report(1))
    original = _atomic_file._sync_directory

    def fail(directory):
        raise OSError(errno.EIO, "directory durability failed")

    monkeypatch.setattr(_atomic_file, "_sync_directory", fail)
    return browser, original


def assert_failed_download(browser):
    assert json.loads(browser.snapshot.read_text()) == browser.report.to_dict()
    assert not browser.export.disabled
    assert "directory durability failed" in browser.notice.value
    assert browser.export_slot.children == (browser.export,)


def assert_download_ready(browser):
    assert browser.export_slot.children == (browser.exports,)
    assert ">Download</a>" in browser.exports.value
    assert "Download failed" not in browser.notice.value


def test_download_retry_after_snapshot_replacement(tmp_path, monkeypatch):
    browser, original = failed_snapshot(tmp_path, monkeypatch)
    browser.export.click()
    assert_failed_download(browser)
    monkeypatch.setattr("screamingface._atomic_file._sync_directory", original)
    browser.export.click()
    assert_download_ready(browser)


@pytest.mark.asyncio
async def test_async_download_retry_after_snapshot_replacement(tmp_path, monkeypatch):
    browser, original = failed_snapshot(tmp_path, monkeypatch)
    browser.export.click()
    assert browser._export_task is not None
    await browser._export_task
    assert_failed_download(browser)
    monkeypatch.setattr("screamingface._atomic_file._sync_directory", original)
    browser.export.click()
    assert browser._export_task is not None
    await browser._export_task
    assert_download_ready(browser)


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
            await transport._save_result(standalone, standalone_outcome(), new_trace_context())
        else:
            transport._save_result(standalone, standalone_outcome(), new_trace_context())
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
    monkeypatch.setenv("SCREAMINGFACE_RESULTS_DIR", str(tmp_path))
    transport = transport_module.AsyncUrl4CloudTransport("https://engine.example")
    other = _candidate()
    if unrelated:
        evaluation = _compiled_evaluation(
            benchmark=BenchmarkInfo("draco", "fixture-revision", 1),
            limit=None,
            case_count=1,
            candidates=(other,),
            required_models=other.models,
        )
        transport.prepare_results(evaluation, (other,))
    entered = []
    ready = asyncio.Event()

    async def waiting(candidate, on_event):
        entered.append(candidate.name)
        if len(entered) == 8:
            ready.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(transport, "_run", waiting)
    monkeypatch.setattr(transport, "cancel_active", AsyncMock())
    async with sf.AsyncClient(
        engine_url="https://engine.example",
        http_transport=httpx.MockTransport(catalog_engine),
        run_transport=transport,
    ) as client:
        task = asyncio.create_task(
            client.evaluate(
                [sf.Model("provider/opus", name=str(index)) for index in range(9)],
                benchmark="draco",
                progress=False,
            )
        )
        try:
            await asyncio.wait_for(ready.wait(), timeout=5)
        finally:
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        assert len(entered) == 8
        assert set(transport._result_contexts) == ({id(other)} if unrelated else set())
