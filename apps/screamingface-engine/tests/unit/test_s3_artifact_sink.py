"""`S3ArtifactStore.open_sink` — a result streamed to object storage without living in memory.

FEATURE: memory fix 3 (OME-1835). The Runner spools a result's chunks to an anonymous local
temp file, then sends ONE PUT whose body is read back from that file in 64 KiB chunks.

INVARIANT: the PUT is a plain single-object request with the body's sha256 signed in
`x-amz-content-sha256` and an explicit `Content-Length`. It is NOT chunked payload signing, so
the SigV4 bound in `sigv4.py` still holds, and the wire carries no `Transfer-Encoding`.

The fake S3 is `httpx.MockTransport`, the same seam as `test_s3_artifact_store.py`.
"""

from __future__ import annotations

import hashlib
import io
import tempfile
from pathlib import Path

import httpx
import pytest

from screamingface_engine.artifacts.ports import ArtifactSink, StreamingArtifactWriter
from screamingface_engine.artifacts.s3 import (
    S3ArtifactStore,
    S3Config,
    S3StorageError,
    _file_chunks,
)
from screamingface_engine.artifacts.sigv4 import Credentials
from url4.streaming.protocol.signals import ResultArtifact

BUCKET = "artifacts"


def _config() -> S3Config:
    return S3Config(
        endpoint_url="http://garage.svc:3900",
        bucket=BUCKET,
        credentials=Credentials(
            access_key="GKtestaccess", secret_key="testsecret", region="garage"
        ),
    )


class _Recorder:
    """Records every request as the wire saw it, and answers with a configurable status."""

    def __init__(self, *, status: int = 200, text: str = "") -> None:
        self.status = status
        self.text = text
        self.requests: list[dict[str, object]] = []

    def handle(self, request: httpx.Request) -> httpx.Response:
        body = request.read()
        self.requests.append(
            {
                "method": request.method,
                "path": request.url.path,
                "headers": {name.lower(): value for name, value in request.headers.items()},
                "body": body,
            }
        )
        return httpx.Response(self.status, text=self.text)

    def store(self) -> S3ArtifactStore:
        transport = httpx.MockTransport(self.handle)
        return S3ArtifactStore(
            _config(),
            client_factory=lambda: httpx.Client(transport=transport),
            async_client_factory=lambda: httpx.AsyncClient(transport=transport),
        )


def test_a_committed_sink_sends_exactly_one_put_under_its_digest() -> None:
    """INVARIANT: one streamed PUT, keyed and signed by the body's own sha256, with the body
    length declared up front. More than two 64 KiB chunks, so the file is read in several
    passes and the body must still arrive whole."""
    recorder = _Recorder()
    data = ("é" * 40_000 + "x" * 70_000).encode("utf-8")
    digest = hashlib.sha256(data).hexdigest()
    sink = recorder.store().open_sink()

    sink.write(data[:50_000])
    sink.write(data[50_000:100_000])
    sink.write(data[100_000:])
    artifact = sink.commit()

    assert len(recorder.requests) == 1
    (request,) = recorder.requests
    assert request["method"] == "PUT"
    assert request["path"] == f"/{BUCKET}/{digest}"
    headers = request["headers"]
    assert isinstance(headers, dict)
    assert headers["x-amz-content-sha256"] == digest
    assert headers["content-length"] == str(len(data))
    assert "transfer-encoding" not in headers
    signed = headers["authorization"].split("SignedHeaders=")[1].split(",")[0]
    assert "content-length" in signed.split(";")
    assert request["body"] == data
    assert artifact == ResultArtifact(id=digest, size_bytes=len(data), sha256=digest)


def test_the_sink_ticket_equals_write_bytes() -> None:
    """WHY: a streamed result and a buffered result of the same bytes must mint the same ticket,
    or the route and the redemption check would disagree about the id."""
    data = ("é" * 40_000 + "x" * 70_000).encode("utf-8")
    sink = _Recorder().store().open_sink()
    sink.write(data)

    streamed = sink.commit()
    buffered = _Recorder().store().write_bytes(data)

    assert streamed == buffered


def test_the_file_is_read_in_64_kib_chunks() -> None:
    assert [len(c) for c in _file_chunks(io.BytesIO(b"x" * 150_000))] == [65536, 65536, 18928]


def test_a_refused_put_raises_and_leaves_no_temp_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """INVARIANT: a failed commit raises, mints no ticket, and leaves nothing on local disk.
    A sink that has failed to commit is closed, so a later write is refused."""
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    recorder = _Recorder(status=403, text="AccessDenied")
    sink = recorder.store().open_sink()
    sink.write(b"abc")

    with pytest.raises(S3StorageError):
        sink.commit()

    assert list(tmp_path.iterdir()) == []
    with pytest.raises(ValueError):
        sink.write(b"x")


def test_abort_sends_nothing() -> None:
    recorder = _Recorder()
    sink = recorder.store().open_sink()
    sink.write(b"abc")

    sink.abort()
    sink.abort()

    assert recorder.requests == []


def test_an_empty_sink_cannot_commit() -> None:
    recorder = _Recorder()
    sink = recorder.store().open_sink()

    with pytest.raises(ValueError):
        sink.commit()

    assert recorder.requests == []


def test_the_store_satisfies_the_streaming_port() -> None:
    store = _Recorder().store()

    assert isinstance(store, StreamingArtifactWriter)
    sink = store.open_sink()
    assert isinstance(sink, ArtifactSink)
    sink.abort()
