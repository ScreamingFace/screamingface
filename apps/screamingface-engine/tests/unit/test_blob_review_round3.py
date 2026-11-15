"""#1603 review round 3 (HupBaHa, 2026-11-04): bounded S3 error bodies; re-upload heals a sidecar.

FEATURE: run blob store (OME-1540), epic OME-1529.
STORY: as an operator, a hostile store or proxy answering a blob read with a huge error body
cannot exhaust the App's or the Runner's memory; as a client, re-uploading a valid file repairs a
record the store got wrong instead of leaving the ref unreadable.

INVARIANT (item 1): an error response on a streamed or capped S3 read costs at most a small
diagnostic prefix plus one network chunk — never the whole body.
INVARIANT (item 2): a stored record survives a repeat upload only when it agrees with the bytes
just verified — size, and (with `verify_signature`) the signature of its recorded type.
Otherwise it is corrupt, rewritten from the upload, and the next read serves it.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import httpx
import pytest

from screamingface_engine.artifacts.blobs import (
    BlobPolicy,
    BlobScope,
    BlobStore,
    FilesystemBlobObjects,
    S3BlobObjects,
)
from screamingface_engine.artifacts.ports import RemoteStream
from screamingface_engine.artifacts.s3 import S3ArtifactStore, S3Config, S3StorageError
from screamingface_engine.artifacts.sigv4 import Credentials

RUN = "f" * 64
SCOPE = BlobScope.for_caller("alice@example.org", RUN)
PDF = b"%PDF-1.7\n" + b"round3" * 20
PDF_HEX = hashlib.sha256(PDF).hexdigest()
KEY = f"{SCOPE.key_prefix}/{PDF_HEX}"
ERROR_XML = b"<Error><Code>InternalError</Code><Message>boom</Message></Error>"
HUGE = 1_000_000
CHUNK = 1024
# WHY these bounds: the diagnostic prefix is 512 bytes; the fake serves 1024-byte chunks, so
# reading the prefix pulls exactly one chunk. Anything near the megabyte is the old bug.
PULL_BOUND = 512 + CHUNK


class _ErrorBody:
    """A lazy 1 MB HTTP 500 body: bytes count only once the client actually reads them."""

    def __init__(self) -> None:
        self.bytes_pulled = 0
        self._body = ERROR_XML + b"x" * (HUGE - len(ERROR_XML))

    def sync_chunks(self) -> Iterator[bytes]:
        for at in range(0, len(self._body), CHUNK):
            chunk = self._body[at : at + CHUNK]
            self.bytes_pulled += len(chunk)
            yield chunk

    async def async_chunks(self) -> AsyncIterator[bytes]:
        for chunk in self.sync_chunks():
            yield chunk


def _config() -> S3Config:
    return S3Config(
        endpoint_url="http://blobs.garage.svc:3900",
        bucket="blobs",
        credentials=Credentials(access_key="GKblobs", secret_key="blobs-secret", region="garage"),
    )


def test_a_huge_s3_error_body_on_a_capped_read_pulls_only_a_prefix() -> None:
    body = _ErrorBody()

    def handle(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, content=body.sync_chunks())

    store = S3ArtifactStore(
        _config(), client_factory=lambda: httpx.Client(transport=httpx.MockTransport(handle))
    )
    with pytest.raises(S3StorageError) as caught:
        store.get_object_at_most(KEY, 100)

    assert body.bytes_pulled <= PULL_BOUND
    # The diagnostic is still there: the store's own error code names the cause.
    assert "InternalError" in str(caught.value)
    assert "500" in str(caught.value)


def test_a_huge_s3_error_body_through_the_blob_backend_pulls_only_a_prefix() -> None:
    body = _ErrorBody()

    def handle(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, content=body.sync_chunks())

    objects = S3BlobObjects(
        S3ArtifactStore(
            _config(), client_factory=lambda: httpx.Client(transport=httpx.MockTransport(handle))
        )
    )
    with pytest.raises(S3StorageError):
        objects.get_at_most(f"{KEY}.json", 100)
    assert body.bytes_pulled <= PULL_BOUND


def test_a_non_utf8_s3_error_prefix_is_decoded_with_replacement() -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, content=b"\xff\xfe<Error>SlowDown</Error>")

    store = S3ArtifactStore(
        _config(), client_factory=lambda: httpx.Client(transport=httpx.MockTransport(handle))
    )
    with pytest.raises(S3StorageError) as caught:
        store.get_object_at_most(KEY, 100)
    assert "SlowDown" in str(caught.value)
    assert "�" in str(caught.value)


def test_a_huge_s3_error_body_on_the_artifact_stream_pulls_only_a_prefix() -> None:
    """The async artifact stream is the other streamed read: its error body is bounded too."""
    body = _ErrorBody()
    artifact_id = "a" * 64

    def handle_head(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers={"content-length": "10"})

    async def handle_get(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, content=body.async_chunks())

    store = S3ArtifactStore(
        _config(),
        client_factory=lambda: httpx.Client(transport=httpx.MockTransport(handle_head)),
        async_client_factory=lambda: httpx.AsyncClient(transport=httpx.MockTransport(handle_get)),
    )
    found = store.content(artifact_id)
    assert isinstance(found, RemoteStream)

    async def drain() -> None:
        async for _chunk in found.stream:
            pass

    with pytest.raises(S3StorageError) as caught:
        asyncio.run(drain())
    assert body.bytes_pulled <= PULL_BOUND
    assert "InternalError" in str(caught.value)


# --- item 2: a re-upload heals a record that disagrees with the verified bytes ------------------


class _MemoryS3:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    def handle(self, request: httpx.Request) -> httpx.Response:
        key = request.url.path.split("/", 2)[2]
        if request.method == "PUT":
            if request.headers.get("if-none-match") == "*" and key in self.objects:
                return httpx.Response(412)
            self.objects[key] = request.content
            return httpx.Response(200)
        found = self.objects.get(key)
        return httpx.Response(404) if found is None else httpx.Response(200, content=found)


@pytest.fixture(params=["filesystem", "s3"])
def objects(
    request: pytest.FixtureRequest, tmp_path: Path
) -> FilesystemBlobObjects | S3BlobObjects:
    if request.param == "filesystem":
        return FilesystemBlobObjects(tmp_path / "blobs")
    fake = _MemoryS3()
    return S3BlobObjects(
        S3ArtifactStore(
            _config(),
            client_factory=lambda: httpx.Client(transport=httpx.MockTransport(fake.handle)),
        )
    )


def _plant_png_label(objects: FilesystemBlobObjects | S3BlobObjects) -> None:
    """Dmitry's repro: PDF bytes under a CLOSED-schema sidecar that says `image/png`."""
    objects.put(KEY, PDF)
    objects.put(
        f"{KEY}.json", json.dumps({"media_type": "image/png", "size_bytes": len(PDF)}).encode()
    )


def test_a_valid_reupload_heals_an_allowed_but_wrong_sidecar(
    objects: FilesystemBlobObjects | S3BlobObjects,
) -> None:
    _plant_png_label(objects)
    store = BlobStore(objects, BlobPolicy(verify_signature=True))

    blob, created = store.ingest(SCOPE, PDF_HEX, "application/pdf", PDF)

    assert created is False
    assert blob.media_type == "application/pdf"
    found = store.read(SCOPE, PDF_HEX)
    assert found is not None
    assert found[0].media_type == "application/pdf"
    assert found[1] == PDF


def test_the_healed_sidecar_is_rewritten_in_the_backend(
    objects: FilesystemBlobObjects | S3BlobObjects,
) -> None:
    _plant_png_label(objects)
    BlobStore(objects, BlobPolicy(verify_signature=True)).ingest(
        SCOPE, PDF_HEX, "application/pdf", PDF
    )
    raw = objects.get(f"{KEY}.json")
    assert raw is not None
    assert json.loads(raw) == {"media_type": "application/pdf", "size_bytes": len(PDF)}


def test_a_healing_reupload_logs_the_corruption_without_the_scope(
    objects: FilesystemBlobObjects | S3BlobObjects, caplog: pytest.LogCaptureFixture
) -> None:
    _plant_png_label(objects)
    with caplog.at_level("WARNING"):
        BlobStore(objects, BlobPolicy(verify_signature=True)).ingest(
            SCOPE, PDF_HEX, "application/pdf", PDF
        )
    logged = " ".join(r.getMessage() for r in caplog.records)
    assert "rewriting" in logged
    assert RUN not in logged


def test_a_matching_sidecar_is_kept_by_a_signature_checked_reupload(
    objects: FilesystemBlobObjects | S3BlobObjects,
) -> None:
    store = BlobStore(objects, BlobPolicy(verify_signature=True))
    first, created_first = store.ingest(SCOPE, PDF_HEX, "application/pdf", PDF)
    again, created_again = store.ingest(SCOPE, PDF_HEX, "Application/PDF; x=1", PDF)
    assert (created_first, created_again) == (True, False)
    assert again == first


# --- item 1 follow-up: the non-streamed requests (HEAD/PUT/DELETE) bound their error bodies too --


def _erroring_store(body: _ErrorBody, status: int = 500) -> S3ArtifactStore:
    def handle(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, content=body.sync_chunks())

    return S3ArtifactStore(
        _config(), client_factory=lambda: httpx.Client(transport=httpx.MockTransport(handle))
    )


def test_a_huge_s3_error_body_on_a_put_pulls_only_a_prefix() -> None:
    body = _ErrorBody()
    with pytest.raises(S3StorageError) as caught:
        _erroring_store(body).put_object(KEY, PDF)
    assert body.bytes_pulled <= PULL_BOUND
    assert "InternalError" in str(caught.value)
    assert "500" in str(caught.value)


def test_a_huge_s3_error_body_on_a_conditional_put_pulls_only_a_prefix() -> None:
    body = _ErrorBody()
    with pytest.raises(S3StorageError):
        _erroring_store(body).put_object_if_absent(f"{KEY}.json", b"{}")
    assert body.bytes_pulled <= PULL_BOUND


def test_a_huge_s3_error_body_on_a_head_pulls_only_a_prefix() -> None:
    body = _ErrorBody()
    with pytest.raises(S3StorageError) as caught:
        _erroring_store(body).content("a" * 64)
    assert body.bytes_pulled <= PULL_BOUND
    assert "InternalError" in str(caught.value)


def test_a_huge_s3_error_body_on_a_delete_pulls_only_a_prefix() -> None:
    body = _ErrorBody()
    with pytest.raises(S3StorageError):
        _erroring_store(body).delete("a" * 64)
    assert body.bytes_pulled <= PULL_BOUND


def test_404_and_412_bodies_are_not_read_at_all() -> None:
    """The absent and precondition-failed answers stay `None` and cost no body bytes."""
    missing, raced = _ErrorBody(), _ErrorBody()
    assert _erroring_store(missing, 404).content("a" * 64) is None
    assert _erroring_store(raced, 412).put_object_if_absent(f"{KEY}.json", b"{}") is False
    assert (missing.bytes_pulled, raced.bytes_pulled) == (0, 0)
