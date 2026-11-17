"""Detach a Run, and pick it up again from anywhere (E5 P2 spec D11, D14, §4.6; plan C2).

FEATURE: a detached Run (OME-1837). STORY: as a researcher, I start an evaluation with
`detach=True` and close my notebook; later, from any machine, `sf.runs.get(run_id).wait()` gives
me the same Report I would have got had I stayed.

INVARIANT (D14): a Report rebuilt from the Engine (context, records, results) equals, field by
field, the Report an attached evaluation of the same Run returns.
"""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest
from _run_engine import RUN_ID, ended, event, run_engine, settled, state
from test_client_run import REPLAY_URL4
from test_client_run import _engine as _catalog_engine
from test_evaluation_outcome import valid_body

import screamingface as sf
from screamingface import runs
from screamingface.errors import ExecutionError

BODY = valid_body().encode()
_MODELS = [sf.Model("provider/opus", name="left"), sf.Model("provider/opus", name="right")]
_SCRIPT = [[state(0, "scheduled"), event(0, 1), settled(0, BODY), settled(1, BODY), ended()]]
_RESULTS = {0: BODY, 1: BODY}


def _routed(engine_url: str) -> httpx.MockTransport:
    """The catalog fixture, with `/runs` reads forwarded to the stub Engine that holds the Run."""

    def handle(request: httpx.Request) -> httpx.Response:
        if not request.url.path.startswith("/runs"):
            return _catalog_engine(request)
        answer = httpx.request(
            request.method,
            engine_url + request.url.raw_path.decode(),
            content=request.content,
            headers={"content-type": request.headers.get("content-type", "application/json")},
        )
        return httpx.Response(
            answer.status_code,
            headers={"content-type": answer.headers.get("content-type", "application/json")},
            content=answer.content,
        )

    return httpx.MockTransport(handle)


def _client(url: str) -> sf.Client:
    return sf.Client(engine_url=url, http_transport=_routed(url))


@pytest.fixture
def results_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    directory = tmp_path / "first-machine"
    monkeypatch.setenv("SCREAMINGFACE_RESULTS_DIR", str(directory))
    return directory


def _another_machine(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """An empty local result store: nothing of the Run is on this machine."""
    monkeypatch.setenv("SCREAMINGFACE_RESULTS_DIR", str(tmp_path / "second-machine"))


def test_detach_returns_the_run_at_once_and_follows_nothing(results_dir: Path) -> None:
    with run_engine(_SCRIPT, _RESULTS) as engine, _client(engine.url) as client:
        run = client.evaluate(
            _MODELS, benchmark="draco", progress=False, detach=True, deadline=timedelta(hours=2)
        )

    assert isinstance(run, runs.Run)
    assert run.id == RUN_ID
    (sent,) = engine.state.registered
    assert (sent["detach"], sent["deadline_s"]) == (True, 7200)
    assert engine.state.followed == []


def test_detach_without_a_deadline_takes_the_engines_default(results_dir: Path) -> None:
    with run_engine(_SCRIPT, _RESULTS) as engine, _client(engine.url) as client:
        client.evaluate(_MODELS, benchmark="draco", progress=False, detach=True)

    assert engine.state.registered[0]["deadline_s"] is None


@pytest.mark.parametrize(
    "deadline", [timedelta(hours=1), timedelta(0), timedelta(seconds=-5), 3600]
)
def test_a_deadline_needs_detach_and_a_positive_timedelta(results_dir: Path, deadline: Any) -> None:
    detach = deadline != timedelta(hours=1)
    with run_engine(_SCRIPT, _RESULTS) as engine, _client(engine.url) as client:
        with pytest.raises((ValueError, TypeError)):
            client.evaluate(
                _MODELS, benchmark="draco", progress=False, detach=detach, deadline=deadline
            )

    assert engine.state.registered == []


def test_wait_follows_the_run_and_returns_the_report_an_attached_run_gives(
    results_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with run_engine(_SCRIPT, _RESULTS) as engine, _client(engine.url) as client:
        attached = client.evaluate(_MODELS, benchmark="draco", progress=False)
    with run_engine(_SCRIPT, _RESULTS) as engine:
        engine.state.run_state = "running"
        with _client(engine.url) as client:
            run_id = client.evaluate(_MODELS, benchmark="draco", progress=False, detach=True).id
        _another_machine(tmp_path, monkeypatch)
        with _client(engine.url) as elsewhere:
            run = runs._run(runs._wire.get_sync(elsewhere._http_request, run_id), elsewhere)
            report = run.wait()

    assert engine.state.followed == [f"/runs/{RUN_ID}/events"]
    assert report.to_json() == attached.to_json()


def test_report_on_another_machine_is_built_from_the_engine_and_kept(
    results_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with run_engine(_SCRIPT, _RESULTS) as engine:
        with _client(engine.url) as client:
            attached = client.evaluate(_MODELS, benchmark="draco", progress=False)
        _another_machine(tmp_path, monkeypatch)
        with _client(engine.url) as elsewhere:
            run = runs._run(runs._wire.get_sync(elsewhere._http_request, RUN_ID), elsewhere)
            first = run.report()
            fetched = list(engine.state.fetched)
            again = run.report()

    assert first.to_json() == attached.to_json()
    assert again.to_json() == attached.to_json()
    # The second read came from this machine's store: no result was fetched again.
    results = [path for path in engine.state.fetched if path.endswith("/result")]
    assert results == [path for path in fetched if path.endswith("/result")]


def test_a_run_still_going_has_no_report_yet(results_dir: Path) -> None:
    with run_engine(_SCRIPT, _RESULTS) as engine, _client(engine.url) as client:
        engine.state.run_state = "running"
        run = client.evaluate(_MODELS, benchmark="draco", progress=False, detach=True)
        with pytest.raises(ExecutionError) as raised:
            run.report()

    assert raised.value.code == "run_not_finished"


def test_a_context_that_does_not_match_the_runs_checksum_is_refused(
    results_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with run_engine(_SCRIPT, _RESULTS) as engine, _client(engine.url) as client:
        run = client.evaluate(_MODELS, benchmark="draco", progress=False, detach=True)
        _another_machine(tmp_path, monkeypatch)
        engine.state.served_context = '{"schema": "replaced"}'
        with pytest.raises(ExecutionError) as raised:
            run.report()

    assert raised.value.code == "context_mismatch"


def test_a_failed_candidate_reattaches_as_a_partial_report(
    results_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    error = {"code": "provider_error", "message": "upstream down", "permanent": False}
    script = [[settled(0, BODY), settled(1, b"", state="failed", error=error), ended("partial")]]
    with run_engine(script, {0: BODY}) as engine, _client(engine.url) as client:
        run = client.evaluate(_MODELS, benchmark="draco", progress=False, detach=True)
        _another_machine(tmp_path, monkeypatch)
        with pytest.raises(ExecutionError) as raised:
            run.report()

    assert raised.value.code == "candidates_failed"
    assert raised.value.details == {"failed": {"right": "provider_error"}}
    assert raised.value.partial_report is not None
    assert raised.value.partial_report.run_id == RUN_ID


def test_progress_and_refresh_read_the_summary(results_dir: Path) -> None:
    with run_engine(_SCRIPT, _RESULTS) as engine, _client(engine.url) as client:
        run = client.evaluate(_MODELS, benchmark="draco", progress=False, detach=True)
        progress = run.progress()

    assert (progress.done, progress.total) == (2, 2)
    reads = [path for path in engine.state.fetched if path.startswith(f"/runs/{RUN_ID}")]
    assert reads and all("view=summary" in path for path in reads)


def test_a_raw_url4_evaluation_detaches_too(results_dir: Path) -> None:
    with run_engine(_SCRIPT, _RESULTS) as engine, _client(engine.url) as client:
        run = client.evaluate(REPLAY_URL4, progress=False, detach=True)

    assert isinstance(run, runs.Run)
    assert engine.state.registered[0]["detach"] is True
    assert engine.state.followed == []


@pytest.mark.asyncio
async def test_the_async_client_detaches_too(results_dir: Path) -> None:
    with run_engine(_SCRIPT, _RESULTS) as engine:
        async with sf.AsyncClient(
            engine_url=engine.url, http_transport=_routed(engine.url)
        ) as client:
            run = await client.evaluate(_MODELS, benchmark="draco", progress=False, detach=True)

    assert isinstance(run, runs.Run)
    assert engine.state.followed == []
