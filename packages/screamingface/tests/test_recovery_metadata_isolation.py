"""Invalid sibling recovery metadata never discards healthy paid results."""

import asyncio
import json

import httpx
import pytest
from test_persistence_followup import pair

import screamingface as sf
from screamingface._engine.result_download import download_async, download_sync
from screamingface._results.store import atomic_json


def recover(directory, key, asynchronous):
    if asynchronous:
        return asyncio.run(sf.reports.get_async(key, directory=directory))
    return sf.reports.get(key, directory=directory)


@pytest.mark.parametrize("asynchronous", [False, True])
@pytest.mark.parametrize("field", ["benchmark", "case_count", "candidates"])
def test_conflicting_sibling_membership_preserves_healthy_partial(tmp_path, asynchronous, field):
    _, first, second = pair(tmp_path)
    value = json.loads(second.manifest.read_text())
    context = value["evaluation"]
    if field == "benchmark":
        context["benchmark"]["case_count"] += 1
    elif field == "case_count":
        context["case_count"] = 1
    else:
        context["candidates"] = list(reversed(context["candidates"]))
    atomic_json(second.manifest, value)
    with pytest.raises(sf.ExecutionError) as error:
        recover(tmp_path, first.key, asynchronous)
    assert error.value.code == "candidates_failed"
    assert isinstance(error.value.details, dict)
    assert error.value.details["failed"] == {"second": "result_metadata_invalid"}
    assert error.value.partial_report is not None
    assert [candidate.name for candidate in error.value.partial_report.candidates] == ["model"]
    assert error.value.partial_report.candidates[0].cases[0].output == "answer 0"


@pytest.mark.parametrize("asynchronous", [False, True])
@pytest.mark.parametrize(
    "field,value",
    [("id", 123), ("size_bytes", "3"), ("size_bytes", -1), ("size_bytes", True), ("sha256", None)],
)
def test_invalid_ticket_preserves_healthy_partial_before_auth_or_fetch(
    tmp_path, monkeypatch, asynchronous, field, value
):
    _, first, second = pair(tmp_path)
    manifest = json.loads(second.manifest.read_text())
    manifest["outcome"]["artifact"] = {"id": "a" * 64, "size_bytes": 3, "sha256": "a" * 64}
    manifest["outcome"]["artifact"][field] = value
    atomic_json(second.manifest, manifest)
    second.path.unlink()
    install_offline_fetch(monkeypatch)
    with pytest.raises(sf.ExecutionError) as error:
        recover(tmp_path, first.key, asynchronous)
    assert error.value.code == "candidates_failed"
    assert isinstance(error.value.details, dict)
    assert error.value.details["failed"] == {"second": "result_metadata_invalid"}
    assert error.value.partial_report is not None
    assert [candidate.name for candidate in error.value.partial_report.candidates] == ["model"]


def install_offline_fetch(monkeypatch):
    def respond(request):
        raise AssertionError("invalid ticket reached HTTP")

    def mint():
        raise AssertionError("invalid ticket reached authentication")

    def fetch(run):
        local = sf.reports._local(run)
        if local is not None:
            return local
        with httpx.Client(base_url=run.engine_url, transport=httpx.MockTransport(respond)) as http:
            return download_sync(http, run, mint)

    async def fetch_async(run):
        local = sf.reports._local(run)
        if local is not None:
            return local

        async def mint_async():
            mint()
            return "token"

        async with httpx.AsyncClient(
            base_url=run.engine_url, transport=httpx.MockTransport(respond)
        ) as http:
            return await download_async(http, run, mint_async)

    monkeypatch.setattr(sf.reports, "_fetch", fetch)
    monkeypatch.setattr(sf.reports, "_fetch_async", fetch_async)


@pytest.mark.parametrize("asynchronous", [False, True])
@pytest.mark.parametrize("field", ["started_at", "completed_at"])
def test_naive_timestamp_preserves_healthy_partial_before_fetch(
    tmp_path, monkeypatch, asynchronous, field
):
    _, first, second = pair(tmp_path)
    manifest = json.loads(second.manifest.read_text())
    manifest["outcome"][field] = "2026-09-30T00:00:00"
    manifest["outcome"]["artifact"] = {"id": "a" * 64, "size_bytes": 3, "sha256": "a" * 64}
    atomic_json(second.manifest, manifest)
    second.path.unlink()
    install_offline_fetch(monkeypatch)
    with pytest.raises(sf.ExecutionError) as error:
        recover(tmp_path, first.key, asynchronous)
    assert error.value.code == "candidates_failed"
    assert isinstance(error.value.details, dict)
    assert error.value.details["failed"] == {"second": "result_metadata_invalid"}
    assert error.value.partial_report is not None
    assert [candidate.name for candidate in error.value.partial_report.candidates] == ["model"]
