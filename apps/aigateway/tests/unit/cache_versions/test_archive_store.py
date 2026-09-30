"""Support: the two write-once archive adapters (OME-1307, GW-freeze; contract C8a).

FEATURE: OME-1307 (E14) - an archive object is written once and never overwritten.
INVARIANT: no credential ever reaches an error message. INVARIANT: an existing object is left
untouched, whatever the new bytes are.
"""

from __future__ import annotations

import os
from pathlib import Path

import httpx
import pytest

from aigateway.core.cache_versions.archive_store import (
    FilesystemVersionArchiveStore,
    S3VersionArchiveStore,
)
from aigateway.core.cache_versions.ports import ArchiveStoreError
from aigateway.core.object_store import S3ObjectStoreConfig
from aigateway.core.sigv4 import EMPTY_PAYLOAD_SHA256, Credentials

pytestmark = pytest.mark.asyncio

_SECRET = "wJalrXUtnFEMI/K7MDENG+bPxRfiCYEXAMPLEKEY"
_BUCKET = "screamingface-cache-versions"
_KEY = "cache-versions/11111111-2222-4333-8444-555555555555/entries.jsonl.gz"
_SHA = "ab" * 32


class _Server:
    """A recording MockTransport handler with one scripted answer for each method."""

    def __init__(self, head: int | Exception, put: int | Exception = 200) -> None:
        self._answers = {"HEAD": head, "PUT": put}
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        answer = self._answers[request.method]
        if isinstance(answer, Exception):
            raise answer
        return httpx.Response(answer, text="<Error>refused</Error>")

    @property
    def methods(self) -> list[str]:
        return [r.method for r in self.requests]


def _store(server: _Server) -> S3VersionArchiveStore:
    return S3VersionArchiveStore(
        S3ObjectStoreConfig(
            endpoint_url="http://127.0.0.1:3900",
            bucket=_BUCKET,
            credentials=Credentials(access_key="GKtestaccess", secret_key=_SECRET, region="garage"),
        ),
        client_factory=lambda: httpx.AsyncClient(transport=httpx.MockTransport(server)),
    )


@pytest.fixture
def archive_file(tmp_path: Path) -> Path:
    path = tmp_path / "entries.jsonl.gz"
    path.write_bytes(b"archive bytes" * 100)
    return path


async def test_s3_existing_object_is_not_written_again(archive_file: Path) -> None:
    server = _Server(head=200)

    assert await _store(server).put_once(_KEY, archive_file, sha256_hex=_SHA) == "exists"

    assert server.methods == ["HEAD"]


async def test_s3_head_is_a_signed_empty_payload_request(archive_file: Path) -> None:
    server = _Server(head=200)

    await _store(server).put_once(_KEY, archive_file, sha256_hex=_SHA)

    head = server.requests[0]
    assert str(head.url) == f"http://127.0.0.1:3900/{_BUCKET}/{_KEY}"
    assert head.headers["x-amz-content-sha256"] == EMPTY_PAYLOAD_SHA256
    authorization = head.headers["authorization"]
    assert authorization.startswith("AWS4-HMAC-SHA256 Credential=GKtestaccess/")
    assert "SignedHeaders=host;x-amz-content-sha256;x-amz-date" in authorization
    assert _SECRET not in authorization


async def test_s3_missing_object_is_put_once_with_the_payload_hash(archive_file: Path) -> None:
    server = _Server(head=404, put=200)

    assert await _store(server).put_once(_KEY, archive_file, sha256_hex=_SHA) == "written"

    assert server.methods == ["HEAD", "PUT"]
    put = server.requests[1]
    # The server refuses bytes that do not hash to this value: that is the CV-H6 check.
    assert put.headers["x-amz-content-sha256"] == _SHA
    assert put.headers["content-length"] == str(archive_file.stat().st_size)
    assert put.content == archive_file.read_bytes()


@pytest.mark.parametrize("status", [403, 500, 301])
async def test_s3_head_with_another_status_is_an_error_and_writes_nothing(
    status: int, archive_file: Path
) -> None:
    server = _Server(head=status)

    with pytest.raises(ArchiveStoreError) as excinfo:
        await _store(server).put_once(_KEY, archive_file, sha256_hex=_SHA)

    assert server.methods == ["HEAD"], "a redirect is never followed"
    assert str(status) in str(excinfo.value)
    assert _SECRET not in str(excinfo.value)


@pytest.mark.parametrize("status", [403, 500, 307])
async def test_s3_put_refusal_is_an_error(status: int, archive_file: Path) -> None:
    server = _Server(head=404, put=status)

    with pytest.raises(ArchiveStoreError) as excinfo:
        await _store(server).put_once(_KEY, archive_file, sha256_hex=_SHA)

    assert server.methods == ["HEAD", "PUT"]
    assert _SECRET not in str(excinfo.value)


@pytest.mark.parametrize(
    "server",
    [
        pytest.param(_Server(head=httpx.ConnectError("down")), id="head-unreachable"),
        pytest.param(
            _Server(head=404, put=httpx.ConnectError("down mid-put")), id="put-unreachable"
        ),
    ],
)
async def test_s3_transport_failure_is_an_error_without_credentials(
    server: _Server, archive_file: Path
) -> None:
    with pytest.raises(ArchiveStoreError) as excinfo:
        await _store(server).put_once(_KEY, archive_file, sha256_hex=_SHA)

    assert _SECRET not in str(excinfo.value)
    assert "GKtestaccess" not in str(excinfo.value)


async def test_filesystem_writes_once_and_never_overwrites(
    tmp_path: Path, archive_file: Path
) -> None:
    root = tmp_path / "archive"
    store = FilesystemVersionArchiveStore(root)
    original = archive_file.read_bytes()

    first = await store.put_once(_KEY, archive_file, sha256_hex=_SHA)
    archive_file.write_bytes(b"other bytes")
    second = await store.put_once(_KEY, archive_file, sha256_hex=_SHA)

    assert (first, second) == ("written", "exists")
    assert (root / _KEY).read_bytes() == original
    assert [p.name for p in (root / _KEY).parent.iterdir()] == ["entries.jsonl.gz"], (
        "no temp file is left behind"
    )


async def test_filesystem_lost_link_race_reports_exists_and_cleans_up(
    tmp_path: Path, archive_file: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "archive"

    def _rival_won(src: object, dst: object, **kwargs: object) -> None:
        raise FileExistsError(str(dst))

    monkeypatch.setattr(os, "link", _rival_won)

    result = await FilesystemVersionArchiveStore(root).put_once(_KEY, archive_file, sha256_hex=_SHA)

    assert result == "exists"
    assert list((root / _KEY).parent.iterdir()) == []
