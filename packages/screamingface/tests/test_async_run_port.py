"""An `AsyncClient`'s detached Run is read and followed through the AsyncClient itself (E5 P2
spec D14, §4.6; owner decision 2026-11-18): no synchronous Client is made for it.

FEATURE: a detached Run (OME-1837). STORY: as a researcher in async code, my detached Run waits,
reports and cancels on the event loop, signed in once, through the AsyncClient I made.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest
from _run_engine import RUN_ID, run_engine
from test_detach_reattach import (
    _MODELS,
    _RESULTS,
    _SCRIPT,
    _another_machine,
    _client,
    _routed,
    results_dir,  # noqa: F401  (a fixture the tests request)
)

import screamingface as sf
from screamingface import runs


def _async_client(url: str) -> sf.AsyncClient:
    return sf.AsyncClient(engine_url=url, http_transport=_routed(url))


@pytest.fixture
def no_sync_client(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fails a test that makes a synchronous Client, or the synchronous transport every one of
    them opens (the hidden Client this replaced was made without `__init__`)."""
    from screamingface._engine import transport

    def refuse(self: Any, *args: Any, **kwargs: Any) -> None:
        raise AssertionError("an AsyncClient's Run made a synchronous Client")

    monkeypatch.setattr(sf.Client, "__init__", refuse)
    monkeypatch.setattr(transport.Url4CloudTransport, "__init__", refuse)


@pytest.mark.asyncio
@pytest.mark.usefixtures("results_dir", "no_sync_client")
async def test_an_async_clients_detached_run_waits_and_reports_on_the_event_loop() -> None:
    beats = 0

    async def heartbeat() -> None:
        nonlocal beats
        while True:
            await asyncio.sleep(0.005)
            beats += 1

    with run_engine(_SCRIPT, _RESULTS) as engine:
        engine.state.run_state = "running"
        async with _async_client(engine.url) as client:
            run = await client.evaluate(_MODELS, benchmark="draco", progress=False, detach=True)
            ticker = asyncio.create_task(heartbeat())
            try:
                report = await run.wait_async()
            finally:
                ticker.cancel()

    assert [candidate.name for candidate in report.candidates] == ["left", "right"]
    assert engine.state.follow_queries == ["events=false"]
    assert beats > 0, "the wait blocked the event loop"


@pytest.mark.asyncio
@pytest.mark.usefixtures("results_dir")
async def test_an_async_clients_run_report_equals_the_one_an_attached_run_gives(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """D14: the async build fetches on the event loop, then the same build takes the results,
    so the Report is equal field by field, built on another machine."""
    with run_engine(_SCRIPT, _RESULTS) as engine:
        with _client(engine.url) as client:
            attached = client.evaluate(_MODELS, benchmark="draco", progress=False)
        _another_machine(tmp_path, monkeypatch)
        fetched = [path for path in engine.state.fetched if path.endswith("/result")]
        async with _async_client(engine.url) as aclient:
            record = await runs._wire.get_async(aclient._http_request, RUN_ID, summary=True)
            report = await runs._bound(record, runs._AsyncRuns(aclient)).report_async()

    assert report.to_json() == attached.to_json()
    again = [path for path in engine.state.fetched if path.endswith("/result")]
    assert len(again) == len(fetched) * 2, "the second machine fetched every result"


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["refresh", "progress", "wait", "report", "cancel"])
@pytest.mark.usefixtures("results_dir")
async def test_an_async_clients_run_refuses_its_sync_methods(method: str) -> None:
    with run_engine(_SCRIPT, _RESULTS) as engine:
        async with _async_client(engine.url) as client:
            run = await client.evaluate(_MODELS, benchmark="draco", progress=False, detach=True)
            with pytest.raises(TypeError, match=rf"run\.{method}_async\(\)"):
                getattr(run, method)()

    assert engine.state.deleted == []
    assert engine.state.followed == []


@pytest.mark.asyncio
@pytest.mark.usefixtures("results_dir", "no_sync_client")
async def test_an_async_clients_run_refreshes_and_cancels_on_the_event_loop() -> None:
    with run_engine(_SCRIPT, _RESULTS) as engine:
        async with _async_client(engine.url) as client:
            run = await client.evaluate(_MODELS, benchmark="draco", progress=False, detach=True)
            fresh = await run.refresh_async()
            progress = await run.progress_async()
            await run.cancel_async()

    assert (fresh.id, progress.total) == (RUN_ID, 2)
    assert [p for p in engine.state.fetched if p.startswith(f"/runs/{RUN_ID}")] == [
        f"/runs/{RUN_ID}?view=summary"
    ] * 2
    assert engine.state.deleted == [f"/runs/{RUN_ID}"]


@pytest.mark.asyncio
@pytest.mark.usefixtures("results_dir")
async def test_a_clients_run_has_the_same_async_methods() -> None:
    with run_engine(_SCRIPT, _RESULTS) as engine, _client(engine.url) as client:
        run = client.evaluate(_MODELS, benchmark="draco", progress=False, detach=True)
        fresh = await run.refresh_async()
        progress = await run.progress_async()
        await run.cancel_async()

    assert (fresh.id, progress.total) == (RUN_ID, 2)
    assert engine.state.deleted == [f"/runs/{RUN_ID}"]


@pytest.mark.asyncio
@pytest.mark.usefixtures("results_dir", "no_sync_client")
async def test_an_async_clients_run_read_from_this_machine_makes_no_sync_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """#1878 review: a Run the Engine no longer keeps, missing a result here, is read through
    `sf.reports.get_async`, which fetches that result without a synchronous Client."""
    from screamingface._results.store import ResultStore

    with run_engine(_SCRIPT, _RESULTS) as engine:
        async with _async_client(engine.url) as client:
            attached = await client.evaluate(_MODELS, benchmark="draco", progress=False)
            record = await runs._wire.get_async(client._http_request, RUN_ID, summary=True)
            ResultStore().list()[0].path.unlink()

            async def deleted(*args: Any, **kwargs: Any) -> Any:
                raise KeyError(RUN_ID)

            monkeypatch.setattr(runs._wire, "get_async", deleted)
            report = await runs._bound(record, runs._AsyncRuns(client)).report_async()

    assert report.to_json() == attached.to_json()
