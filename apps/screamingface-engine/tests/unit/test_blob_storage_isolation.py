"""The run blob store on its OWN storage (#1603 review comment 1; owner decision 2026-11-03).

FEATURE: run blob store (OME-1540), epic OME-1529.
STORY: as an operator of a self-hosted engine, a client uploading files until the blob store
is full gets its uploads refused — and every paid run still delivers its result, because
results park in a different store.

INVARIANT: an explicit blob backend never shares the artifact store's directory, bucket,
endpoint or credentials; a full blob store fails uploads (503 + Retry-After) and nothing else.
"""

from __future__ import annotations

import errno
import hashlib
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest
from _fakes import RecordingJobRunner
from fastapi import FastAPI
from httpx import ASGITransport

from screamingface_engine import job_env
from screamingface_engine.app import create_app
from screamingface_engine.artifacts.blobs import (
    BlobScope,
    BlobStore,
    FilesystemBlobObjects,
    S3BlobObjects,
)
from screamingface_engine.artifacts.s3 import S3ArtifactStore
from screamingface_engine.artifacts.wiring import (
    blob_objects_from_values,
    blob_s3_config_from_values,
    blob_store_from_env,
)
from screamingface_engine.auth import JwtCodec
from screamingface_engine.config import Settings
from screamingface_engine.testing import InMemoryEventStream

SECRET = "blob-isolation-secret-0123456789abcdef01234"
T0 = datetime(2026, 11, 3, 12, 0, 0, tzinfo=UTC)
RUN = "d" * 64
PDF = b"%PDF-1.7\n" + b"isolated" * 20
PDF_HEX = hashlib.sha256(PDF).hexdigest()
PATH = f"/blob/sha256/{PDF_HEX}"

RESULTS_HOST = "results.garage.svc:3900"
BLOBS_HOST = "blobs.garage.svc:3900"
ARTIFACT_S3 = {
    "artifact_store": "s3",
    "artifact_s3_endpoint_url": f"http://{RESULTS_HOST}",
    "artifact_s3_bucket": "results",
    "artifact_s3_access_key": "GKresults",
    "artifact_s3_secret_key": "results-secret",
}
BLOB_S3 = {
    "blob_store": "s3",
    "blob_s3_endpoint_url": f"http://{BLOBS_HOST}",
    "blob_s3_bucket": "blobs",
    "blob_s3_access_key": "GKblobs",
    "blob_s3_secret_key": "blobs-secret",
}
BLOB_S3_ENV = {
    job_env.BLOB_STORE: "s3",
    job_env.BLOB_S3_ENDPOINT_URL: f"http://{BLOBS_HOST}",
    job_env.BLOB_S3_BUCKET: "blobs",
    job_env.BLOB_S3_ACCESS_KEY: "GKblobs",
    job_env.BLOB_S3_SECRET_KEY: "blobs-secret",
}


def _cap() -> dict[str, str]:
    token = JwtCodec(secret=SECRET, iat_window_s=60, capability_lifetime_s=58_800).sign(RUN, T0)
    return {"URL4-Capability": token, "X-User-Email": "alice@example.org"}


def _app(**overrides: object) -> FastAPI:
    settings = Settings.model_validate({"jwt_secret": SECRET, "iat_window_s": 60, **overrides})
    return create_app(
        settings, stream=InMemoryEventStream(), job_runner=RecordingJobRunner(), clock=lambda: T0
    )


async def _upload(app: FastAPI) -> httpx.Response:
    async with httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        return await c.put(PATH, content=PDF, headers={**_cap(), "Content-Type": "application/pdf"})


# --- the names: one variable per setting, both halves --------------------------------------


@pytest.mark.parametrize(
    ("field", "name"),
    [
        ("blob_store", job_env.BLOB_STORE),
        ("blobs_dir", job_env.BLOBS_DIR),
        ("blob_s3_endpoint_url", job_env.BLOB_S3_ENDPOINT_URL),
        ("blob_s3_bucket", job_env.BLOB_S3_BUCKET),
        ("blob_s3_region", job_env.BLOB_S3_REGION),
        ("blob_s3_access_key", job_env.BLOB_S3_ACCESS_KEY),
        ("blob_s3_secret_key", job_env.BLOB_S3_SECRET_KEY),
    ],
)
def test_the_app_setting_and_the_runner_env_name_are_the_same_variable(
    field: str, name: str
) -> None:
    # INVARIANT: a one-sided rename would point the App's uploads and the Runner's reads at
    # different blob stores.
    assert field in Settings.model_fields
    assert f"URL4_CLOUD_{field.upper()}" == name
    assert name in job_env.DEPLOY_TIME


def test_the_default_blob_directory_is_outside_the_artifact_tree() -> None:
    blobs, artifacts = Path(job_env.DEFAULT_BLOBS_DIR), Path(job_env.DEFAULT_ARTIFACTS_DIR)
    assert not blobs.is_relative_to(artifacts)
    assert not artifacts.is_relative_to(blobs)


def test_an_empty_blob_store_setting_means_follow(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(job_env.BLOB_STORE, "")
    assert Settings().blob_store is None


# --- filesystem: separate directories, and a full blob directory fails only uploads -------


@pytest.mark.asyncio
async def test_uploads_land_in_the_blob_directory_not_the_artifact_one(tmp_path: Path) -> None:
    app = _app(
        artifacts_dir=str(tmp_path / "artifacts"),
        blob_store="filesystem",
        blobs_dir=str(tmp_path / "blobs"),
    )
    assert (await _upload(app)).status_code == 201

    assert [p for p in (tmp_path / "blobs").rglob(PDF_HEX) if p.is_file()]
    assert not (tmp_path / "artifacts").exists() or not list((tmp_path / "artifacts").rglob("*"))


@pytest.mark.asyncio
async def test_a_full_blob_directory_refuses_uploads_and_results_still_park(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    blobs_dir = tmp_path / "blobs"
    real_put = FilesystemBlobObjects.put

    def full_disk_put(self: FilesystemBlobObjects, key: str, data: bytes) -> None:
        # The blob volume is full; any other directory still has room.
        if self._root == blobs_dir:  # noqa: SLF001 - simulating one full volume
            raise OSError(errno.ENOSPC, "No space left on device")
        real_put(self, key, data)

    monkeypatch.setattr(FilesystemBlobObjects, "put", full_disk_put)
    app = _app(
        artifacts_dir=str(tmp_path / "artifacts"),
        blob_store="filesystem",
        blobs_dir=str(blobs_dir),
    )

    refused = await _upload(app)
    parked = app.state.artifact_store.write_bytes(b'{"result": "paid for"}')

    assert refused.status_code == 503
    assert int(refused.headers["retry-after"]) > 0
    assert parked.size_bytes > 0
    assert app.state.artifact_store.content(parked.id) is not None


# --- s3: separate endpoints, buckets and keys; a full blob store fails only uploads ---------


class _TwoStores:
    """Two fake S3 endpoints; the blob one can be made full (507, as Garage answers a full disk)."""

    def __init__(self) -> None:
        self.objects: dict[str, dict[str, bytes]] = {RESULTS_HOST: {}, BLOBS_HOST: {}}
        self.requests: list[httpx.Request] = []
        self.blobs_full = False

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        host = request.url.netloc.decode()
        store = self.objects[host]
        if request.method == "PUT":
            if host == BLOBS_HOST and self.blobs_full:
                return httpx.Response(507, text="<Error><Code>InsufficientStorage</Code></Error>")
            store[request.url.path] = request.content
            return httpx.Response(200)
        body = store.get(request.url.path)
        return httpx.Response(404) if body is None else httpx.Response(200, content=body)


@pytest.fixture
def two_stores(monkeypatch: pytest.MonkeyPatch) -> _TwoStores:
    fake = _TwoStores()
    monkeypatch.setattr(
        S3ArtifactStore,
        "_default_client",
        lambda self: httpx.Client(transport=httpx.MockTransport(fake.handle)),
    )
    return fake


@pytest.mark.asyncio
async def test_s3_uploads_go_to_the_blob_bucket_with_the_blob_key(two_stores: _TwoStores) -> None:
    app = _app(**ARTIFACT_S3, **BLOB_S3)

    assert (await _upload(app)).status_code == 201

    puts = [r for r in two_stores.requests if r.method == "PUT"]
    assert puts
    assert {r.url.netloc.decode() for r in puts} == {BLOBS_HOST}
    assert all(r.url.path.startswith("/blobs/blobs/") for r in puts)
    assert all("GKblobs/" in r.headers["authorization"] for r in puts)
    assert two_stores.objects[RESULTS_HOST] == {}


@pytest.mark.asyncio
async def test_a_full_s3_blob_store_refuses_uploads_and_results_still_park(
    two_stores: _TwoStores,
) -> None:
    app = _app(**ARTIFACT_S3, **BLOB_S3)
    two_stores.blobs_full = True

    refused = await _upload(app)
    parked = app.state.artifact_store.write_bytes(b'{"result": "paid for"}')

    assert refused.status_code == 503
    assert int(refused.headers["retry-after"]) > 0
    assert refused.json()["permanent"] is False
    assert f"/results/{parked.id}" in two_stores.objects[RESULTS_HOST]


def test_an_explicit_s3_blob_store_never_borrows_the_artifact_settings() -> None:
    artifact_only = {
        job_env.ARTIFACT_STORE: "s3",
        job_env.ARTIFACT_S3_ENDPOINT_URL: f"http://{RESULTS_HOST}",
        job_env.ARTIFACT_S3_BUCKET: "results",
        job_env.ARTIFACT_S3_ACCESS_KEY: "GKresults",
        job_env.ARTIFACT_S3_SECRET_KEY: "results-secret",
        job_env.BLOB_STORE: "s3",
    }
    with pytest.raises(ValueError, match=job_env.BLOB_S3_BUCKET) as caught:
        blob_objects_from_values(artifact_only)
    assert "results-secret" not in str(caught.value)


def test_the_blob_s3_config_reads_only_blob_names() -> None:
    config = blob_s3_config_from_values(BLOB_S3_ENV)
    assert config.endpoint_url == f"http://{BLOBS_HOST}"
    assert config.bucket == "blobs"
    assert config.credentials.access_key == "GKblobs"
    assert config.credentials.region == job_env.DEFAULT_ARTIFACT_S3_REGION


def test_an_unknown_blob_backend_is_refused() -> None:
    with pytest.raises(ValueError, match=job_env.BLOB_STORE):
        blob_objects_from_values({job_env.BLOB_STORE: "azure"})


# --- the Runner reads the same separate store the App wrote --------------------------------


def test_the_runner_reads_what_the_app_wrote_in_the_blob_directory(tmp_path: Path) -> None:
    scope = BlobScope.for_caller("alice@example.org", RUN)
    BlobStore(FilesystemBlobObjects(tmp_path / "blobs")).ingest(
        scope, PDF_HEX, "application/pdf", PDF
    )
    env = {
        job_env.ARTIFACTS_DIR: str(tmp_path / "artifacts"),
        job_env.BLOB_STORE: "filesystem",
        job_env.BLOBS_DIR: str(tmp_path / "blobs"),
    }

    found = blob_store_from_env(env).read(scope, PDF_HEX)

    assert found is not None
    assert found[1] == PDF


def test_the_runner_builds_the_blob_bucket_backend_from_its_env() -> None:
    assert isinstance(blob_store_from_env(BLOB_S3_ENV).objects, S3BlobObjects)


def test_the_filesystem_default_is_the_sibling_directory() -> None:
    objects = blob_objects_from_values({job_env.BLOB_STORE: "filesystem"})
    assert isinstance(objects, FilesystemBlobObjects)
    assert objects._root == Path(job_env.DEFAULT_BLOBS_DIR)  # noqa: SLF001


# --- deployment shape ---------------------------------------------------------------------


def test_a_queue_app_refuses_a_filesystem_blob_store(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match=job_env.BLOB_STORE):
        _app(runner="queue", **ARTIFACT_S3, blob_store="filesystem", blobs_dir=str(tmp_path))


def test_a_queue_app_accepts_a_separate_s3_blob_store(two_stores: _TwoStores) -> None:
    app = _app(runner="queue", **ARTIFACT_S3, **BLOB_S3)
    assert isinstance(app.state.blob_store.objects, S3BlobObjects)
