"""PB-7a — the two `VersionArchiveReader` adapters (C8b).

FEATURE: OME-1307 (E14). INVARIANT under test: the scoreboard only READS the bucket (GET, signed),
and a missing archive is `ArchiveMissing`, never an empty pair.
"""

from __future__ import annotations

import uuid
from pathlib import Path

import httpx
import pytest

from scoreboard.adapters.fs_archive_reader import FilesystemArchiveReader
from scoreboard.adapters.s3_archive_reader import S3ArchiveConfig, S3ArchiveReader
from scoreboard.adapters.sigv4 import Credentials
from scoreboard.core.publish.ports import ArchiveMissing, PublisherError
from tests.unit.publish._fakes import canonical_pair

_SECRET = "s3-secret-key-value"


def _write_pair(root: Path, version_id: uuid.UUID) -> None:
    pair = canonical_pair()
    folder = root / "cache-versions" / str(version_id)
    folder.mkdir(parents=True)
    (folder / "entries.jsonl.gz").write_bytes(pair.entries)
    (folder / "manifest.json").write_bytes(pair.manifest)


@pytest.mark.asyncio
async def test_filesystem_reader_reads_pair_and_refuses_escape(tmp_path: Path) -> None:
    root = tmp_path / "bucket"
    version_id = uuid.uuid4()
    _write_pair(root, version_id)
    reader = FilesystemArchiveReader(root)

    pair = await reader.read(version_id)

    assert pair == canonical_pair()
    with pytest.raises(ArchiveMissing):
        await reader.read(uuid.uuid4())

    # A version folder that is a link to a place outside the root is refused, not followed.
    outside = tmp_path / "outside"
    _write_pair(outside, version_id)
    escaped = uuid.uuid4()
    (root / "cache-versions" / str(escaped)).symlink_to(
        outside / "cache-versions" / str(version_id), target_is_directory=True
    )
    with pytest.raises(ArchiveMissing):
        await reader.read(escaped)


def _s3_reader(handler: httpx.MockTransport) -> S3ArchiveReader:
    config = S3ArchiveConfig(
        endpoint_url="http://garage.test:3900",
        bucket="cv",
        credentials=Credentials(access_key="AKIATEST", secret_key=_SECRET, region="garage"),
    )
    return S3ArchiveReader(config, client_factory=lambda: httpx.AsyncClient(transport=handler))


@pytest.mark.asyncio
async def test_s3_reader_signs_get_and_maps_404_to_missing() -> None:
    version_id = uuid.uuid4()
    pair = canonical_pair()
    seen: list[httpx.Request] = []

    def serve(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if str(version_id) not in request.url.path:
            return httpx.Response(404, text="<Error><Code>NoSuchKey</Code></Error>")
        body = pair.manifest if request.url.path.endswith("manifest.json") else pair.entries
        return httpx.Response(200, content=body)

    reader = _s3_reader(httpx.MockTransport(serve))

    assert await reader.read(version_id) == pair
    with pytest.raises(ArchiveMissing):
        await reader.read(uuid.uuid4())

    paths = {request.url.path for request in seen[:2]}
    assert paths == {
        f"/cv/cache-versions/{version_id}/entries.jsonl.gz",
        f"/cv/cache-versions/{version_id}/manifest.json",
    }
    for request in seen:
        assert request.method == "GET"
        assert request.headers["Authorization"].startswith("AWS4-HMAC-SHA256 Credential=AKIATEST/")
        assert _SECRET not in request.headers["Authorization"]


@pytest.mark.asyncio
async def test_s3_reader_maps_other_failures_to_a_retryable_sanitized_error() -> None:
    def serve(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("manifest.json"):
            raise httpx.ConnectTimeout("no route", request=request)
        return httpx.Response(503, text="<Error>slow down</Error>")

    reader = _s3_reader(httpx.MockTransport(serve))

    with pytest.raises(PublisherError) as refused:
        await reader.read(uuid.uuid4())

    assert refused.value.retryable is True
    assert "503" in refused.value.message
    assert _SECRET not in refused.value.message


@pytest.mark.parametrize(
    "endpoint",
    [
        "ftp://garage.test",
        "http://garage.test/base",
        "http://garage.test?x=1",
        "http://user:pw@garage.test",
    ],
)
def test_s3_config_refuses_an_endpoint_that_is_not_an_origin(endpoint: str) -> None:
    # WHY: the signature covers `/<bucket>/<key>` only, so any other part of the URL would be sent
    # but not signed: a guaranteed 403 that reads as bad keys.
    with pytest.raises(ValueError, match="endpoint"):
        S3ArchiveConfig(
            endpoint_url=endpoint,
            bucket="cv",
            credentials=Credentials(access_key="a", secret_key="b", region="garage"),
        )


@pytest.mark.asyncio
async def test_s3_reader_maps_a_transport_error_to_a_retryable_sanitized_error() -> None:
    def serve(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("no route to garage.test:3900", request=request)

    with pytest.raises(PublisherError) as refused:
        await _s3_reader(httpx.MockTransport(serve)).read(uuid.uuid4())

    assert refused.value.retryable is True
    assert "ConnectTimeout" in refused.value.message
    # WHY: the text of a transport error can carry the host; only the class name is kept.
    assert "garage.test" not in refused.value.message
