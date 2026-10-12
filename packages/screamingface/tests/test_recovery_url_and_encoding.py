"""Invalid origins and encoded artifacts cannot defeat durable recovery."""

import gzip
import hashlib
import json
import tracemalloc

import httpx
import pytest
from test_persistence_followup import pair
from test_saved_runs import outcome
from test_transport_artifact_fetch import _candidate

import screamingface as sf
from screamingface._engine.result_download import download_async, download_sync
from screamingface._results.store import ResultStore, atomic_json


@pytest.mark.asyncio
@pytest.mark.parametrize("asynchronous", [False, True])
@pytest.mark.parametrize(
    "engine_url", [None, "broken-origin", "https://fixture.example/path", "https://host:invalid"]
)
async def test_invalid_saved_origin_preserves_healthy_partial(
    tmp_path, monkeypatch, asynchronous, engine_url
):
    original, healthy, damaged = pair(tmp_path)
    atomic_json(tmp_path / "evaluations" / "evaluation.json", healthy.evaluation)
    value = json.loads(damaged.manifest.read_text())
    body = damaged.path.read_bytes()
    value["engine_url"] = engine_url
    value["outcome"]["artifact"] = {
        "id": hashlib.sha256(body).hexdigest(),
        "size_bytes": len(body),
        "sha256": hashlib.sha256(body).hexdigest(),
    }
    atomic_json(damaged.manifest, value)
    damaged.path.unlink()

    def forbidden(*args, **kwargs):
        raise AssertionError("Invalid saved origin reached Client construction")

    monkeypatch.setattr(sf, "Client", forbidden)
    monkeypatch.setattr(sf, "AsyncClient", forbidden)
    monkeypatch.setattr("screamingface.client.Client", forbidden)
    monkeypatch.setattr("screamingface.client.AsyncClient", forbidden)
    with pytest.raises(sf.ExecutionError) as caught:
        if asynchronous:
            await sf.reports.get_async("evaluation", directory=tmp_path)
        else:
            sf.reports.get("evaluation", directory=tmp_path)
    assert caught.value.code == "candidates_failed"
    assert isinstance(caught.value.details, dict)
    assert caught.value.details["failed"] == {"second": "result_metadata_invalid"}
    assert caught.value.partial_report is not None
    assert caught.value.partial_report.to_dict() == original.to_dict()


@pytest.mark.asyncio
@pytest.mark.parametrize("asynchronous", [False, True])
async def test_encoded_success_is_rejected_before_consuming_body(tmp_path, asynchronous):
    # INVARIANT: an encoded HTTP 200 cannot expand before the artifact-size guard runs.
    payload = gzip.compress(b"x" * (32 * 1024 * 1024))
    consumed = []

    class CompressedStream(httpx.SyncByteStream, httpx.AsyncByteStream):
        def __iter__(self):
            consumed.append(True)
            yield payload

        async def __aiter__(self):
            for chunk in self:
                yield chunk

    saved = ResultStore(tmp_path).record("https://fixture.example", _candidate(), outcome())
    transport = httpx.MockTransport(
        lambda _: httpx.Response(
            200, headers={"content-encoding": "gzip"}, stream=CompressedStream()
        )
    )

    async def mint():
        return "token"

    tracemalloc.start()
    try:
        with pytest.raises(sf.ExecutionError) as caught:
            if asynchronous:
                async with httpx.AsyncClient(
                    base_url=saved.engine_url, transport=transport
                ) as http:
                    await download_async(http, saved, mint)
            else:
                with httpx.Client(base_url=saved.engine_url, transport=transport) as http:
                    download_sync(http, saved, lambda: "token")
        peak = tracemalloc.get_traced_memory()[1]
    finally:
        tracemalloc.stop()
    assert caught.value.code == "result_integrity_mismatch"
    assert not consumed
    assert peak < 2 * 1024 * 1024
    assert saved.manifest.exists()
    assert not saved.path.exists()
    assert not list(saved.path.parent.glob(".download-*"))


@pytest.mark.asyncio
@pytest.mark.parametrize("asynchronous", [False, True])
async def test_artifact_requests_negotiate_identity_encoding(tmp_path, asynchronous):
    saved = ResultStore(tmp_path).record("https://fixture.example", _candidate(), outcome())
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(404)

    async def mint():
        return "token"

    transport = httpx.MockTransport(respond)
    with pytest.raises(sf.ExecutionError) as caught:
        if asynchronous:
            async with httpx.AsyncClient(base_url=saved.engine_url, transport=transport) as http:
                await download_async(http, saved, mint)
        else:
            with httpx.Client(base_url=saved.engine_url, transport=transport) as http:
                download_sync(http, saved, lambda: "token")
    assert caught.value.code == "result_expired"
    assert len(requests) == 1
    assert requests[0].headers["accept-encoding"] == "identity"
