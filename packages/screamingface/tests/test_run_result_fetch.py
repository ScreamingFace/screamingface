"""A driver-started Candidate's result, read from the Run's result route (E5 P2 spec D9a; plan C1).

FEATURE: a detached Run (OME-1837). STORY: as a researcher, a result the Engine kept for my Run
is fetched, checked and saved, whichever machine asks for it.

INVARIANT: the bytes are admitted only when their size and sha256 are the record's; a fetch never
buffers or writes past the declared size.
"""

from __future__ import annotations

import hashlib
from dataclasses import replace

import httpx
import pytest
from test_saved_runs import outcome
from test_transport_artifact_fetch import _candidate

from screamingface._core.ports import _RunResult
from screamingface._engine.result_download import (
    download_async,
    download_sync,
    fetch_result_async,
    fetch_result_sync,
)
from screamingface._results.store import ResultStore
from screamingface.errors import ExecutionError

ENGINE = "https://fixture.example"
RUN_ID = "run_" + "b" * 32
BODY = b'{"cases": []}'
RESULT = _RunResult(
    run_id=RUN_ID, index=3, size_bytes=len(BODY), sha256=hashlib.sha256(BODY).hexdigest()
)
ROUTE = f"/runs/{RUN_ID}/candidates/3/result"


def _outcome(result: _RunResult = RESULT):
    return replace(outcome(), result_body=None, artifact=None, run_result=result)


def _engine(body: bytes, seen: list[httpx.Request], status: int = 200) -> httpx.MockTransport:
    def respond(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(status, content=body, headers={"content-type": "application/json"})

    return httpx.MockTransport(respond)


def _never_minted() -> str:
    raise AssertionError("the result route takes the caller's identity, not a capability")


def test_a_saved_result_is_fetched_from_the_runs_result_route(tmp_path) -> None:
    saved = ResultStore(tmp_path).record(ENGINE, _candidate(), _outcome())
    seen: list[httpx.Request] = []

    with httpx.Client(base_url=ENGINE, transport=_engine(BODY, seen)) as http:
        fetched = download_sync(http, saved, _never_minted)

    assert [request.url.path for request in seen] == [ROUTE]
    assert "URL4-Capability" not in seen[0].headers
    assert saved.path.read_bytes() == BODY
    assert (fetched.result_path, fetched.run_result) == (saved.path, RESULT)


@pytest.mark.parametrize("body", [b'{"cases": [1]}', BODY + b" "], ids=["checksum", "size"])
def test_bytes_that_are_not_the_records_are_refused_and_not_saved(tmp_path, body: bytes) -> None:
    saved = ResultStore(tmp_path).record(ENGINE, _candidate(), _outcome())

    with httpx.Client(base_url=ENGINE, transport=_engine(body, [])) as http:
        with pytest.raises(ExecutionError) as raised:
            download_sync(http, saved, _never_minted)

    assert raised.value.code == "result_integrity_mismatch"
    assert not saved.path.exists()


def test_a_result_past_its_runs_retention_is_expired(tmp_path) -> None:
    saved = ResultStore(tmp_path).record(ENGINE, _candidate(), _outcome())

    with httpx.Client(base_url=ENGINE, transport=_engine(b"", [], status=404)) as http:
        with pytest.raises(ExecutionError) as raised:
            download_sync(http, saved, _never_minted)

    assert raised.value.code == "result_expired"


def test_a_saved_result_reference_names_only_a_run_and_an_index(tmp_path) -> None:
    """INVARIANT: saved metadata cannot redirect a fetch (`../`, another host)."""
    bad = replace(RESULT, run_id="../../artifacts/x")
    saved = ResultStore(tmp_path).record(ENGINE, _candidate(), _outcome(bad))

    with httpx.Client(base_url=ENGINE, transport=_engine(BODY, [])) as http:
        with pytest.raises(ExecutionError) as raised:
            download_sync(http, saved, _never_minted)

    assert raised.value.code == "result_metadata_invalid"


def test_the_manifest_keeps_the_runs_result_reference(tmp_path) -> None:
    store = ResultStore(tmp_path)
    saved = store.record(ENGINE, _candidate(), _outcome())

    assert store.load(saved.key).outcome.run_result == RESULT


def test_an_unsaved_result_is_read_into_memory() -> None:
    seen: list[httpx.Request] = []

    with httpx.Client(base_url=ENGINE, transport=_engine(BODY, seen)) as http:
        fetched = fetch_result_sync(http, _outcome())

    assert fetched.result_body == BODY.decode()
    assert [request.url.path for request in seen] == [ROUTE]


@pytest.mark.asyncio
async def test_the_async_twins_read_the_same_route(tmp_path) -> None:
    saved = ResultStore(tmp_path).record(ENGINE, _candidate(), _outcome())
    seen: list[httpx.Request] = []

    async def never() -> str:
        raise AssertionError("no capability")

    async with httpx.AsyncClient(base_url=ENGINE, transport=_engine(BODY, seen)) as http:
        downloaded = await download_async(http, saved, never)
        in_memory = await fetch_result_async(http, _outcome())

    assert saved.path.read_bytes() == BODY
    assert (downloaded.result_path, in_memory.result_body) == (saved.path, BODY.decode())
    assert [request.url.path for request in seen] == [ROUTE, ROUTE]


_NOT_UTF8 = b'{"cases": "\xff"}'
_NOT_UTF8_RESULT = _RunResult(
    run_id=RUN_ID,
    index=3,
    size_bytes=len(_NOT_UTF8),
    sha256=hashlib.sha256(_NOT_UTF8).hexdigest(),
)


def test_a_result_that_is_not_utf8_is_refused_when_read_into_memory() -> None:
    """As a saved download refuses it: `result_integrity_mismatch`, not a bare decode error."""
    with httpx.Client(base_url=ENGINE, transport=_engine(_NOT_UTF8, [])) as http:
        with pytest.raises(ExecutionError) as raised:
            fetch_result_sync(http, _outcome(_NOT_UTF8_RESULT))

    assert raised.value.code == "result_integrity_mismatch"


@pytest.mark.asyncio
async def test_an_async_result_that_is_not_utf8_is_refused_when_read_into_memory() -> None:
    async with httpx.AsyncClient(base_url=ENGINE, transport=_engine(_NOT_UTF8, [])) as http:
        with pytest.raises(ExecutionError) as raised:
            await fetch_result_async(http, _outcome(_NOT_UTF8_RESULT))

    assert raised.value.code == "result_integrity_mismatch"


# --- Review round 2: a saved Run result is checked and re-fetched like an artifact ----------


def test_a_saved_run_result_whose_download_did_not_finish_is_fetched_again(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The recovery notice says `sf.reports.get(id)`; it re-fetches from the Run's route."""
    from _run_engine import run_engine

    from screamingface.reports import _fetch

    monkeypatch.setenv("SCREAMINGFACE_RESULTS_DIR", str(tmp_path / "results"))
    with run_engine([], {3: BODY}) as engine:
        saved = ResultStore(tmp_path).record(engine.url, _candidate(), _outcome())
        fetched = _fetch(saved)

    assert [path for path in engine.state.fetched] == [ROUTE]
    assert (fetched.result_path, saved.path.read_bytes()) == (saved.path, BODY)


def test_a_saved_run_result_that_changed_on_disk_is_refused(tmp_path) -> None:
    from screamingface.reports import _local

    saved = ResultStore(tmp_path).record(ENGINE, _candidate(), _outcome())
    saved.path.write_bytes(BODY[:-1] + b" ")

    with pytest.raises(ExecutionError) as raised:
        _local(saved)

    assert raised.value.code == "result_integrity_mismatch"


@pytest.mark.parametrize("login", [True, False])
def test_a_fetch_that_may_not_log_in_says_so_on_its_request(tmp_path, login: bool) -> None:
    """Round 3 (spec D15): a follow fetches its results without ever starting a sign-in; the
    request carries that, for the sign-in flow to read."""
    from screamingface._core.wire import _NO_LOGIN

    seen: list[httpx.Request] = []
    saved = ResultStore(tmp_path).record(ENGINE, _candidate(), _outcome())
    with httpx.Client(base_url=ENGINE, transport=_engine(BODY, seen)) as http:
        fetch_result_sync(http, _outcome(), login=login)
        download_sync(http, saved, _never_minted, login=login)

    assert [request.extensions.get(_NO_LOGIN, False) for request in seen] == [not login] * 2


@pytest.mark.asyncio
async def test_an_async_fetch_that_may_not_log_in_says_so_on_its_request(tmp_path) -> None:
    from screamingface._core.wire import _NO_LOGIN

    seen: list[httpx.Request] = []
    saved = ResultStore(tmp_path).record(ENGINE, _candidate(), _outcome())

    def respond(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, content=BODY, headers={"content-type": "application/json"})

    async with httpx.AsyncClient(base_url=ENGINE, transport=httpx.MockTransport(respond)) as http:
        await fetch_result_async(http, _outcome(), login=False)
        await download_async(http, saved, _never_minted_async, login=False)

    assert [request.extensions.get(_NO_LOGIN) for request in seen] == [True, True]


async def _never_minted_async() -> str:
    raise AssertionError("the result route takes the caller's identity, not a capability")


# --- review round 4: the Run result request is safe to re-send ----------------------------


def _flaky(body: bytes, seen: list[httpx.Request], failures: list[int]) -> httpx.MockTransport:
    """Answers each status in ``failures`` once, in order, then the result."""

    def respond(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if failures:
            return httpx.Response(failures.pop(0), content=b"{}")
        return httpx.Response(200, content=body, headers={"content-type": "application/json"})

    return httpx.MockTransport(respond)


def test_the_run_result_request_is_marked_safe_to_re_send(tmp_path) -> None:
    """It changes nothing on the Engine, so an Access challenge re-sends it after the sign-in,
    and the retrying transport re-sends it after an edge failure."""
    from screamingface._core.wire import _REPLAY_SAFE

    saved = ResultStore(tmp_path).record(ENGINE, _candidate(), _outcome())
    seen: list[httpx.Request] = []

    with httpx.Client(base_url=ENGINE, transport=_engine(BODY, seen)) as http:
        download_sync(http, saved, _never_minted)
        fetch_result_sync(http, _outcome())

    assert [request.extensions.get(_REPLAY_SAFE) for request in seen] == [True, True]


@pytest.mark.parametrize("status", [503, 520])
def test_an_edge_failure_on_the_result_route_is_tried_again(tmp_path, status: int) -> None:
    """A Candidate that succeeded on the Engine is not failed by one transient answer."""
    saved = ResultStore(tmp_path).record(ENGINE, _candidate(), _outcome())
    seen: list[httpx.Request] = []

    with httpx.Client(base_url=ENGINE, transport=_flaky(BODY, seen, [status])) as http:
        fetched = download_sync(http, saved, _never_minted)
    with httpx.Client(base_url=ENGINE, transport=_flaky(BODY, [], [status])) as http:
        read = fetch_result_sync(http, _outcome())

    assert len(seen) == 2
    assert fetched.result_path == saved.path
    assert read.result_body == BODY.decode()


@pytest.mark.asyncio
async def test_an_async_edge_failure_on_the_result_route_is_tried_again(tmp_path) -> None:
    saved = ResultStore(tmp_path).record(ENGINE, _candidate(), _outcome())

    async def never() -> str:
        raise AssertionError("the result route takes the caller's identity")

    transport = _flaky(BODY, [], [503])
    async with httpx.AsyncClient(base_url=ENGINE, transport=transport) as http:
        fetched = await download_async(http, saved, never)
    async with httpx.AsyncClient(base_url=ENGINE, transport=_flaky(BODY, [], [503])) as http:
        read = await fetch_result_async(http, _outcome())

    assert fetched.result_path == saved.path
    assert read.result_body == BODY.decode()


def test_an_application_error_on_the_result_route_is_not_tried_again(tmp_path) -> None:
    """WHY 500 is not retried: an application error repeats (`_core.retry`)."""
    seen: list[httpx.Request] = []

    with httpx.Client(base_url=ENGINE, transport=_flaky(BODY, seen, [500])) as http:
        with pytest.raises(ExecutionError) as raised:
            fetch_result_sync(http, _outcome())

    assert raised.value.status == 500
    assert len(seen) == 1
