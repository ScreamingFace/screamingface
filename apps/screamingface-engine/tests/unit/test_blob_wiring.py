"""The Runner's side of the run blob store: build it and its scope from the run's env (OME-1540).

FEATURE: image and PDF inputs (epic OME-1529). The Runner binds a `ScopedBlobReader` for its
model calls (OME-1545); this pins that the store and the scope it reads come from the run
context — the same backend the App writes, the topic and the verified identity the run was
started with — and never from a ref (spec F3 step 1).
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from screamingface_engine import job_env
from screamingface_engine.artifacts.blobs import (
    BlobScope,
    BlobStore,
    FilesystemBlobObjects,
    S3BlobObjects,
    ScopedBlobReader,
)
from screamingface_engine.artifacts.wiring import (
    blob_reader_from_env,
    blob_scope_from_env,
    blob_store_from_env,
)

PNG = b"\x89PNG-wiring"
PNG_HEX = hashlib.sha256(PNG).hexdigest()
TOPIC = "T" * 64


def _env(tmp_path: Path, email: str | None = "alice@example.org") -> dict[str, str]:
    env = {job_env.TOPIC: TOPIC, job_env.ARTIFACTS_DIR: str(tmp_path / "artifacts")}
    env.update(job_env.identity_to_env({"X-User-Email": email} if email else {}))
    return env


def test_the_scope_is_the_runs_topic_and_verified_identity(tmp_path: Path) -> None:
    assert blob_scope_from_env(_env(tmp_path)) == BlobScope.for_caller("alice@example.org", TOPIC)
    assert blob_scope_from_env(_env(tmp_path, None)) == BlobScope.for_caller(None, TOPIC)


def test_a_run_without_a_topic_has_no_scope(tmp_path: Path) -> None:
    env = _env(tmp_path)
    del env[job_env.TOPIC]
    with pytest.raises(ValueError, match="run"):
        blob_scope_from_env(env)


def test_the_filesystem_store_reads_what_the_app_wrote(tmp_path: Path) -> None:
    app_side = BlobStore(FilesystemBlobObjects(tmp_path / "artifacts"))
    app_side.ingest(BlobScope.for_caller("alice@example.org", TOPIC), PNG_HEX, "image/png", PNG)

    found = blob_store_from_env(_env(tmp_path)).read(blob_scope_from_env(_env(tmp_path)), PNG_HEX)

    assert found is not None
    assert found[1] == PNG


def test_s3_selection_builds_the_s3_backend(tmp_path: Path) -> None:
    env = {
        **_env(tmp_path),
        job_env.ARTIFACT_STORE: "s3",
        job_env.ARTIFACT_S3_ENDPOINT_URL: "http://garage.svc:3900",
        job_env.ARTIFACT_S3_BUCKET: "artifacts",
        job_env.ARTIFACT_S3_ACCESS_KEY: "GKtest",
        job_env.ARTIFACT_S3_SECRET_KEY: "testsecret",
    }
    assert isinstance(blob_store_from_env(env).objects, S3BlobObjects)


@pytest.mark.asyncio
async def test_the_reader_is_scoped_to_this_run(tmp_path: Path) -> None:
    app_side = BlobStore(FilesystemBlobObjects(tmp_path / "artifacts"))
    app_side.ingest(BlobScope.for_caller("bob@example.org", TOPIC), PNG_HEX, "image/png", PNG)

    reader = blob_reader_from_env(_env(tmp_path))

    assert isinstance(reader, ScopedBlobReader)
    # INVARIANT (F3): same run, other tenant → not readable.
    assert await reader.read(f"sha256:{PNG_HEX}") is None
