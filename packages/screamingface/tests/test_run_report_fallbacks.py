"""When `Run.wait()` and `Run.report()` cannot use the Engine's build (#1878 review round 4).

FEATURE: a detached Run (OME-1837). STORY: as a researcher, my Run's Report opens whenever this
machine holds it: with a transport that cannot follow or rebuild, when the Engine lost or no
longer keeps the Run's context, and without disturbing a Report already saved here whole.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

import httpx
import pytest
from test_client_run import _engine as _catalog_engine
from test_runs_wire import _problem, _record

import screamingface as sf
from screamingface import runs

_Handler = Callable[[httpx.Request], httpx.Response]
SAVED = object()


@pytest.fixture(autouse=True)
def _results_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SCREAMINGFACE_RESULTS_DIR", str(tmp_path / "results"))


@pytest.fixture
def saved_here(monkeypatch: pytest.MonkeyPatch) -> None:
    """This machine holds the Run's Report."""
    monkeypatch.setattr(sf.reports, "get", lambda report_id: SAVED)
    monkeypatch.setattr(runs, "with_run_id", lambda report, run_id: report)


def _p2(context: str, **overrides: Any) -> dict[str, Any]:
    record = _record(
        state="complete",
        detached=True,
        deadline_at="2026-11-05T10:00:00Z",
        stopped_by=None,
        context={
            "sha256": hashlib.sha256(context.encode()).hexdigest(),
            "size_bytes": len(context.encode()),
        },
    )
    for index, candidate in enumerate(record["candidates"]):
        candidate["index"] = index
        candidate["start"] = {"name": candidate["name"], "url4": "/gsm8k?model=openai/x"}
    record.update(overrides)
    return record


def _client(handler: _Handler, run_transport: object = None) -> sf.Client:
    def route(request: httpx.Request) -> httpx.Response:
        if request.url.path.startswith("/runs"):
            return handler(request)
        return _catalog_engine(request)

    return sf.Client(
        engine_url="https://engine.example",
        http_transport=httpx.MockTransport(route),
        run_transport=cast(Any, run_transport),
    )


def _run(client: sf.Client, state: str = "complete") -> runs.Run:
    record = runs._wire._decode_run(_record(state=state))
    return runs._run(record, client)


class _CannotFollow:
    """A custom `run_transport`: it runs Candidates, and can neither follow nor rebuild a Run."""

    def run(self, candidate: Any, on_event: Any) -> Any:
        raise AssertionError("not used")

    def cancel_active(self) -> None:
        pass

    def close(self) -> None:
        pass


def test_wait_with_a_transport_that_cannot_follow_reads_the_run_until_it_ends(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    states = ["running", "running", "running", "complete"]
    reads: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        reads.append(request.url.query.decode())
        state = states.pop(0) if len(states) > 1 else states[0]
        return httpx.Response(200, json=_record(state=state))

    monkeypatch.setattr(runs, "_WAIT_POLL_S", 0.0)
    monkeypatch.setattr(runs.Run, "report", lambda self: SAVED)
    with _client(handler, _CannotFollow()) as client:
        assert _run(client, "running").wait() is SAVED

    assert reads.count("view=summary") >= 3


@pytest.mark.usefixtures("saved_here")
def test_report_with_a_transport_that_cannot_rebuild_reads_this_machine() -> None:
    context = json.dumps({"benchmark": {"name": "gsm8k"}})

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/context"):
            return httpx.Response(200, content=context.encode())
        return httpx.Response(200, json=_p2(context))

    with _client(handler, _CannotFollow()) as client:
        assert _run(client).report() is SAVED


@pytest.mark.usefixtures("saved_here")
def test_report_reads_this_machine_when_the_run_goes_between_its_two_reads() -> None:
    """Retention deleted the Run after its full read and before its context read."""
    context = json.dumps({"benchmark": {"name": "gsm8k"}})

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/context"):
            return _problem(404, "run_not_found")
        return httpx.Response(200, json=_p2(context))

    with _client(handler) as client:
        assert _run(client).report() is SAVED


@pytest.mark.usefixtures("saved_here")
def test_report_reads_this_machine_when_the_context_cannot_be_read_back() -> None:
    """A context this Client cannot rebuild an evaluation from (one a newer Client wrote)."""
    context = "not a context"

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/context"):
            return httpx.Response(200, content=context.encode())
        return httpx.Response(200, json=_p2(context))

    with _client(handler) as client:
        assert _run(client).report() is SAVED
