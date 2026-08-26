"""PUT-only object store evidence for the cache-snapshot uploader (OME-1021).

The store is the last hop before Garage: the URL is path-style, the body streams off the
event loop with an explicit Content-Length and a full-payload sha256 (no aws-chunked
encoding), every signed header travels with the request, and any refusal or transport
failure surfaces as a sanitized :class:`S3StorageError` that carries no credential material.
"""

from __future__ import annotations

from collections.abc import Callable, Coroutine
from pathlib import Path
from typing import Any

import httpx
import pytest

from aigateway.core.object_store import S3ObjectStore, S3ObjectStoreConfig, S3StorageError
from aigateway.core.sigv4 import Credentials

Handler = Callable[[httpx.Request], httpx.Response]
AsyncHandler = Callable[[httpx.Request], Coroutine[None, None, httpx.Response]]

_SECRET = "wJalrXUtnFEMI/K7MDENG+bPxRfiCYEXAMPLEKEY"
_SHA256 = "ab" * 32
_BUCKET = "screamingface-cache-snapshots"
_KEY = "cache-snapshots/2026-08-28T05-00-00Z.sql.gz"


def _store(
    handler: Handler | AsyncHandler,
) -> S3ObjectStore:
    def factory() -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=httpx.MockTransport(handler))

    return S3ObjectStore(
        S3ObjectStoreConfig(
            endpoint_url="http://127.0.0.1:3900",
            bucket=_BUCKET,
            credentials=Credentials(access_key="GKtestaccess", secret_key=_SECRET, region="garage"),
        ),
        client_factory=factory,
    )


@pytest.mark.asyncio
async def test_put_sends_a_path_style_signed_request_with_a_streaming_body(tmp_path: Path) -> None:
    body = b"hello snapshot " * 1000
    archive = tmp_path / "snapshot.sql.gz"
    archive.write_bytes(body)
    captured: dict[str, Any] = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        captured["method"] = request.method
        captured["url"] = str(request.url)
        captured["headers"] = dict(request.headers)
        captured["payload"] = await request.aread()
        return httpx.Response(200, text="")

    await _store(handler).put(_KEY, archive, sha256_hex=_SHA256)

    # Path-style addressing: {endpoint}/{bucket}/{key}, key unencoded.
    assert captured["method"] == "PUT"
    assert captured["url"] == f"http://127.0.0.1:3900/{_BUCKET}/{_KEY}"
    headers = captured["headers"]
    assert headers["host"] == "127.0.0.1:3900"
    assert headers["x-amz-content-sha256"] == _SHA256
    assert headers["content-length"] == str(len(body))
    assert headers["authorization"].startswith("AWS4-HMAC-SHA256 Credential=GKtestaccess/")
    assert "SignedHeaders=host;x-amz-content-sha256;x-amz-date" in headers["authorization"]
    assert "aws-chunked" not in headers["authorization"]
    assert captured["payload"] == body  # the whole file arrived, streaming


@pytest.mark.asyncio
async def test_a_refused_upload_raises_a_sanitized_error(tmp_path: Path) -> None:
    archive = tmp_path / "snapshot.sql.gz"
    archive.write_bytes(b"x")

    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, text="<Error><Code>SignatureDoesNotMatch</Code></Error>")

    with pytest.raises(S3StorageError) as excinfo:
        await _store(handler).put(_KEY, archive, sha256_hex=_SHA256)
    message = str(excinfo.value)
    assert "403" in message
    assert _SECRET not in message  # no credential material


@pytest.mark.asyncio
async def test_a_transport_failure_is_wrapped(tmp_path: Path) -> None:
    archive = tmp_path / "snapshot.sql.gz"
    archive.write_bytes(b"x")

    async def handler(_request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("boom")

    with pytest.raises(S3StorageError):
        await _store(handler).put(_KEY, archive, sha256_hex=_SHA256)


@pytest.mark.asyncio
async def test_the_upload_path_refuses_an_absent_file(tmp_path: Path) -> None:
    async def handler(_request: httpx.Request) -> httpx.Response:
        raise AssertionError("must not be reached")

    with pytest.raises(FileNotFoundError):
        await _store(handler).put(_KEY, tmp_path / "missing.sql.gz", sha256_hex=_SHA256)
