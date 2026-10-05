"""Review regressions protect bounded downloads and ordinary sequence/lifecycle behavior."""

import os
import threading
from pathlib import Path
from typing import Any, cast

import httpx
import pytest
from test_case_navigation import multi_candidate_report
from test_saved_runs import outcome, saved_fixture
from test_transport_artifact_fetch import _candidate

import screamingface as sf
from screamingface._engine.result_download import download_async, download_sync
from screamingface._results.lifecycle import report_operation
from screamingface._results.store import ResultStore, atomic_json
from screamingface.reports import _decode


class _ErrorStream(httpx.SyncByteStream, httpx.AsyncByteStream):
    def __init__(self):
        self.consumed = 0

    def __iter__(self):
        for _ in range(512):
            self.consumed += 65536
            yield b"x" * 65536

    async def __aiter__(self):
        for chunk in self:
            yield chunk


@pytest.mark.parametrize("status", [404, 410, 500])
def test_error_download_body_is_bounded(tmp_path, status):
    saved = ResultStore(tmp_path).record("https://fixture.example", _candidate(), outcome())
    stream = _ErrorStream()
    with httpx.Client(
        base_url=saved.engine_url,
        transport=httpx.MockTransport(lambda _: httpx.Response(status, stream=stream)),
    ) as http:
        with pytest.raises(sf.ScreamingFaceError):
            download_sync(http, saved, lambda: "token")
    assert stream.consumed <= (0 if status in (404, 410) else 65536)
    assert not saved.path.exists()


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [404, 410, 500])
async def test_async_error_download_body_is_bounded(tmp_path, status):
    saved = ResultStore(tmp_path).record("https://fixture.example", _candidate(), outcome())
    stream = _ErrorStream()

    async def mint():
        return "token"

    async with httpx.AsyncClient(
        base_url=saved.engine_url,
        transport=httpx.MockTransport(lambda _: httpx.Response(status, stream=stream)),
    ) as http:
        with pytest.raises(sf.ScreamingFaceError):
            await download_async(http, saved, mint)
    assert stream.consumed <= (0 if status in (404, 410) else 65536)
    assert not saved.path.exists()


@pytest.mark.parametrize("state", ["rendering", "exporting"])
def test_inline_results_retain_presentation_ownership(tmp_path, state):
    import json

    original, saved = saved_fixture(tmp_path, 3)
    assert saved.evaluation is not None
    path = tmp_path / "evaluations/evaluation.json"
    atomic_json(path, {**saved.evaluation, "owner_pid": os.getpid(), "state": "ready"})
    reopened = _decode(saved, saved.persist_inline())
    assert reopened.to_json() == original.to_json()
    with report_operation(reopened, state):
        assert json.loads(path.read_text())["state"] == state
    assert json.loads(path.read_text())["state"] == "ready"


def test_disk_sequence_rejects_float_positions(tmp_path):
    _, saved = saved_fixture(tmp_path, 3)
    reopened = sf.reports.get(saved.key, directory=tmp_path)
    with pytest.raises(TypeError):
        cast(Any, reopened.candidates[0].cases)[1.0]


def test_disk_sequence_accepts_integer_index_protocol(tmp_path):
    class Index:
        def __index__(self):
            return -1

    _, saved = saved_fixture(tmp_path, 3)
    reopened = sf.reports.get(saved.key, directory=tmp_path)
    assert cast(Any, reopened.candidates[0].cases)[Index()].case_id == 2


@pytest.mark.asyncio
async def test_candidate_selection_uses_worker_and_loading_controls(tmp_path, monkeypatch):
    from screamingface._ui.report_browser import ReportBrowser

    monkeypatch.chdir(tmp_path)
    browser = ReportBrowser(multi_candidate_report(count=30))
    loop_thread = threading.get_ident()
    renders = []
    original = browser._page_html

    def render(page):
        renders.append(threading.get_ident())
        return original(page)

    monkeypatch.setattr(browser, "_page_html", render)
    browser.candidate.value = 0
    assert browser._page_task is not None
    assert browser.candidate.disabled and browser.go_to.disabled
    await browser._page_task
    assert renders and all(thread != loop_thread for thread in renders)
    assert not browser.candidate.disabled and not browser.go_to.disabled


@pytest.mark.parametrize("pid", [2**31, 2**32, 2**80])
def test_invalid_owner_pid_cannot_block_discovery(tmp_path, monkeypatch, pid):
    from screamingface._results import recovery_notice

    _, saved = saved_fixture(tmp_path, 3)
    assert saved.evaluation is not None
    atomic_json(
        tmp_path / "evaluations/evaluation.json",
        {**saved.evaluation, "owner_pid": pid, "state": "running"},
    )
    monkeypatch.setattr(recovery_notice, "running_in_notebook", lambda: True)
    monkeypatch.setattr(
        recovery_notice, "display_notebook_notice", lambda _: pytest.fail("unsafe PID")
    )
    recovery_notice.show_recoverable_results(ResultStore(tmp_path), saved.engine_url)


def test_saved_atomic_write_preserves_primary_failure(tmp_path, monkeypatch):
    from screamingface._results.store import atomic_bytes

    def fail_sync(_):
        raise RuntimeError("primary failure")

    def fail_cleanup(*args, **kwargs):
        raise OSError("cleanup failure")

    monkeypatch.setattr(os, "fsync", fail_sync)
    monkeypatch.setattr(Path, "unlink", fail_cleanup)
    with pytest.raises(RuntimeError, match="primary failure"):
        atomic_bytes(tmp_path / "record.json", b"data")


@pytest.mark.parametrize("asynchronous", [False, True])
def test_encoded_error_download_does_not_decompress(tmp_path, asynchronous):
    import asyncio
    import gzip
    import tracemalloc

    payload = gzip.compress(b"x" * (32 * 1024 * 1024))

    class CompressedStream(httpx.SyncByteStream, httpx.AsyncByteStream):
        def __iter__(self):
            yield payload

        async def __aiter__(self):
            yield payload

    saved = ResultStore(tmp_path).record("https://fixture.example", _candidate(), outcome())
    transport = httpx.MockTransport(
        lambda _: httpx.Response(
            500, headers={"content-encoding": "gzip"}, stream=CompressedStream()
        )
    )

    async def run_async():
        async def mint():
            return "token"

        async with httpx.AsyncClient(base_url=saved.engine_url, transport=transport) as http:
            await download_async(http, saved, mint)

    tracemalloc.start()
    try:
        with pytest.raises(sf.ScreamingFaceError):
            if asynchronous:
                asyncio.run(run_async())
            else:
                with httpx.Client(base_url=saved.engine_url, transport=transport) as http:
                    download_sync(http, saved, lambda: "token")
        assert tracemalloc.get_traced_memory()[1] < 2 * 1024 * 1024
    finally:
        tracemalloc.stop()


@pytest.mark.asyncio
async def test_queued_candidate_change_cannot_replace_inflight_selection(tmp_path, monkeypatch):
    from screamingface._ui.report_browser import ReportBrowser

    monkeypatch.chdir(tmp_path)
    browser = ReportBrowser(multi_candidate_report(count=30))
    browser.candidate.value = 0
    browser.candidate.value = 1
    assert browser.candidate.value == 0
    assert browser.navigation.selected == 0
    assert browser._page_task is not None
    await browser._page_task
    assert not browser.candidate.disabled
