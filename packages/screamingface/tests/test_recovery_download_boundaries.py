"""Download diagnostics and disk access remain bounded and compatible."""

import os
from pathlib import Path
from typing import Any, cast

import httpx
import pytest
from test_saved_runs import outcome, saved_fixture
from test_transport_artifact_fetch import _candidate

import screamingface as sf
from screamingface._engine.result_download import download_async, download_sync
from screamingface._results.store import ResultStore


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
