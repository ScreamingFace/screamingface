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
