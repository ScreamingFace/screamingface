"""Blob delete on every backend (chat-run erd §1.1, CR-26).

FEATURE: chat-run. The chat-input store deletes a record once its run has finished, so
`BlobStore.delete` must remove the data object and the metadata object on each backend.

INVARIANT: an absent blob is not an error. A second delete, or a delete the backend answers
with 404, raises nothing.

TEST-PLAN: CR-26 `blob_delete_removes_data_and_metadata_on_each_backend`, one case per backend.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from pathlib import Path

import httpx
import pytest
from _chat_world import MemoryObjects

from screamingface_engine.artifacts.blob_objects import (
    FilesystemBlobObjects,
    S3BlobObjects,
)
from screamingface_engine.artifacts.blobs import BlobScope, BlobStore
from screamingface_engine.artifacts.s3 import S3ArtifactStore, S3Config
from screamingface_engine.artifacts.sigv4 import Credentials

RUN = "a" * 64
PDF = b"%PDF-1.7\n" + b"x" * 20
PDF_TYPE = "application/pdf"
ENDPOINT = "http://garage.svc:3900"


def _scope() -> BlobScope:
    return BlobScope.for_caller(None, RUN)


def _filesystem(tmp_path: Path) -> tuple[BlobStore, Callable[[], list[str]]]:
    store = BlobStore(FilesystemBlobObjects(tmp_path))
    return store, lambda: [str(p) for p in (tmp_path / "blobs").rglob("*") if p.is_file()]


class _FakeS3:
    """Objects in a dict, the requests it saw, and the status it answers a DELETE with."""

    def __init__(self, delete_status: int = 204) -> None:
        self.objects: dict[str, bytes] = {}
        self.requests: list[httpx.Request] = []
        self.delete_status = delete_status

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        path = request.url.path
        if request.method == "DELETE":
            self.objects.pop(path, None)
            return httpx.Response(self.delete_status, text="deleted")
        if request.method == "PUT":
            self.objects[path] = request.content
            return httpx.Response(200)
        body = self.objects.get(path)
        return (
            httpx.Response(200, content=body)
            if body is not None
            else httpx.Response(404, text="NoSuchKey")
        )

    def objects_store(self) -> S3BlobObjects:
        config = S3Config(
            endpoint_url=ENDPOINT,
            bucket="blobs",
            credentials=Credentials(
                access_key="GKtestaccess", secret_key="testsecret", region="garage"
            ),
        )
        store = S3ArtifactStore(
            config,
            client_factory=lambda: httpx.Client(transport=httpx.MockTransport(self.handle)),
            async_client_factory=lambda: httpx.AsyncClient(
                transport=httpx.MockTransport(self.handle)
            ),
        )
        return S3BlobObjects(store)


def _s3(tmp_path: Path) -> tuple[BlobStore, Callable[[], list[str]]]:
    fake = _FakeS3()
    return BlobStore(fake.objects_store()), lambda: list(fake.objects)


def _in_memory(tmp_path: Path) -> tuple[BlobStore, Callable[[], list[str]]]:
    objects = MemoryObjects()
    return BlobStore(objects), lambda: list(objects.objects)


@pytest.mark.parametrize(
    "backend",
    [
        pytest.param(_filesystem, id="filesystem"),
        pytest.param(_s3, id="s3"),
        pytest.param(_in_memory, id="in-memory"),
    ],
)
def test_blob_delete_removes_data_and_metadata_on_each_backend(
    tmp_path: Path,
    backend: Callable[[Path], tuple[BlobStore, Callable[[], list[str]]]],
) -> None:
    store, stored = backend(tmp_path)
    sha = hashlib.sha256(PDF).hexdigest()
    store.ingest(_scope(), sha, PDF_TYPE, PDF)
    assert store.read(_scope(), sha) is not None
    assert len(stored()) == 2

    store.delete(_scope(), sha)

    assert store.read(_scope(), sha) is None
    assert stored() == []
    store.delete(_scope(), sha)


def test_blob_delete_on_s3_removes_metadata_before_data() -> None:
    fake = _FakeS3()
    store = BlobStore(fake.objects_store())
    sha = hashlib.sha256(PDF).hexdigest()
    store.ingest(_scope(), sha, PDF_TYPE, PDF)
    fake.requests.clear()

    store.delete(_scope(), sha)

    deletes = [request for request in fake.requests if request.method == "DELETE"]
    assert len(deletes) == 2
    assert deletes[0].url.path.endswith(f"/{sha}.json")
    assert deletes[1].url.path.endswith(f"/{sha}")


def test_blob_delete_on_s3_treats_a_404_as_absent() -> None:
    fake = _FakeS3(delete_status=404)
    store = BlobStore(fake.objects_store())
    sha = hashlib.sha256(PDF).hexdigest()

    store.delete(_scope(), sha)

    assert [request.method for request in fake.requests] == ["DELETE", "DELETE"]


def test_an_in_memory_backend_without_delete_keeps_its_objects() -> None:
    class DictObjectsNoDelete:
        def __init__(self) -> None:
            self.data: dict[str, bytes] = {}

        def put(self, key: str, data: bytes) -> None:
            self.data[key] = data

        def get(self, key: str) -> bytes | None:
            return self.data.get(key)

        def sweep(self, ttl_seconds: float, *, now: float | None = None) -> int:
            return 0

    objects = DictObjectsNoDelete()
    store = BlobStore(objects)
    sha = hashlib.sha256(PDF).hexdigest()
    store.ingest(_scope(), sha, PDF_TYPE, PDF)
    kept = dict(objects.data)

    store.delete(_scope(), sha)

    assert objects.data == kept


def test_a_malformed_digest_deletes_nothing() -> None:
    fake = _FakeS3()
    store = BlobStore(fake.objects_store())

    store.delete(_scope(), "not-hex")

    assert fake.requests == []
