"""`BlobStore` — the run-scoped, content-addressed blob store (OME-1540).

FEATURE: image and PDF inputs (epic OME-1529). A file with no URL — a client upload, or an https
attachment that OME-1543 writes through — is kept here, and url4 `/blob/sha256/<hex>` (C1) and
`blob:sha256/<hex>` (C3) refs resolve against it as a direct tenant + run store read.

INVARIANT (spec F3, authorization): a digest is NOT a bearer capability. A read is scoped to the
(tenant, run) it was ingested under; any other scope sees `None`, exactly what a missing blob is.
INVARIANT (spec F3, integrity): sha256 is verified at ingest AND on every read; a mismatch is the
typed, permanent `x.blob_digest_mismatch`.

Every behaviour runs on BOTH backends: the filesystem one and S3 against a fake endpoint.
"""

from __future__ import annotations

import hashlib
import logging
import os
import time
from pathlib import Path

import httpx
import pytest

from screamingface_engine.artifacts.blobs import (
    ATTACHMENT_MEDIA_TYPES,
    BLOB_DIGEST_MISMATCH,
    BLOB_TOO_LARGE,
    BLOB_UNSUPPORTED_MEDIA_TYPE,
    DEFAULT_BLOB_MAX_BYTES,
    BlobDigestMismatch,
    BlobObjects,
    BlobPolicy,
    BlobScope,
    BlobStore,
    BlobTooLarge,
    BlobUnsupportedMediaType,
    FilesystemBlobObjects,
    S3BlobObjects,
    ScopedBlobReader,
)
from screamingface_engine.artifacts.s3 import S3ArtifactStore, S3Config
from screamingface_engine.artifacts.sigv4 import Credentials

PNG = b"\x89PNG\r\n\x1a\n" + b"pixels" * 10
PNG_HEX = hashlib.sha256(PNG).hexdigest()
RUN_A = "A" * 64
RUN_B = "B" * 64
ALICE = "alice@example.org"
BOB = "bob@example.org"
SCOPE = BlobScope.for_caller(ALICE, RUN_A)


class _FakeS3:
    """Objects keyed by their FULL path below the bucket — blob keys carry slashes."""

    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}
        self.requests: list[httpx.Request] = []

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        key = request.url.path.split("/", 2)[2]
        if request.method == "PUT":
            self.objects[key] = request.content
            return httpx.Response(200)
        body = self.objects.get(key)
        if body is None:
            return httpx.Response(404, text="NoSuchKey")
        return httpx.Response(200, content=body)


def _s3_objects(fake: _FakeS3) -> S3BlobObjects:
    config = S3Config(
        endpoint_url="http://garage.svc:3900",
        bucket="artifacts",
        credentials=Credentials(access_key="GKtest", secret_key="testsecret", region="garage"),
    )
    store = S3ArtifactStore(
        config,
        client_factory=lambda: httpx.Client(transport=httpx.MockTransport(fake.handle)),
    )
    return S3BlobObjects(store)


@pytest.fixture(params=["filesystem", "s3"])
def objects(request: pytest.FixtureRequest, tmp_path: Path) -> BlobObjects:
    if request.param == "filesystem":
        return FilesystemBlobObjects(tmp_path / "artifacts")
    return _s3_objects(_FakeS3())


# --- scope -----------------------------------------------------------------------------------


def test_the_tenant_is_never_the_raw_email() -> None:
    """INVARIANT: the email is identity, not a key — it never lands in a path or object key."""
    scope = BlobScope.for_caller(ALICE, RUN_A)
    assert ALICE not in scope.key_prefix
    assert scope.key_prefix.startswith("blobs/")
    assert RUN_A in scope.key_prefix


def test_no_identity_is_the_fixed_anonymous_partition() -> None:
    assert BlobScope.for_caller(None, RUN_A).tenant == "anonymous"
    assert BlobScope.for_caller("   ", RUN_A).tenant == "anonymous"


def test_an_email_can_never_collide_with_the_anonymous_partition() -> None:
    assert BlobScope.for_caller("anonymous", RUN_A).tenant != "anonymous"


def test_two_callers_get_two_tenants() -> None:
    assert BlobScope.for_caller(ALICE, RUN_A) != BlobScope.for_caller(BOB, RUN_A)


@pytest.mark.parametrize("run", ["", "../etc", "a/b", "x" * 129, "topic with space"])
def test_a_run_id_that_could_escape_its_prefix_is_refused(run: str) -> None:
    with pytest.raises(ValueError, match="run"):
        BlobScope.for_caller(ALICE, run)


# --- ingest + read round trip ----------------------------------------------------------------


def test_a_round_trip_returns_the_bytes_and_their_media_type(objects: BlobObjects) -> None:
    store = BlobStore(objects)

    stored, created = store.ingest(SCOPE, PNG_HEX, "image/png", PNG)
    read = store.read(SCOPE, PNG_HEX)

    assert created is True
    assert stored.sha256 == PNG_HEX
    assert stored.size_bytes == len(PNG)
    assert stored.media_type == "image/png"
    assert stored.ref == f"blob:sha256/{PNG_HEX}"
    assert read is not None
    assert read == (stored, PNG)


def test_uploading_the_same_bytes_again_returns_the_same_ref(objects: BlobObjects) -> None:
    store = BlobStore(objects)
    first, _ = store.ingest(SCOPE, PNG_HEX, "image/png", PNG)

    again, created = store.ingest(SCOPE, PNG_HEX, "image/png", PNG)

    assert created is False
    assert again == first


def test_a_repeat_upload_keeps_the_first_media_type(objects: BlobObjects) -> None:
    """WHY first-write-wins: a ref already handed out must not change type under its holder."""
    store = BlobStore(objects)
    store.ingest(SCOPE, PNG_HEX, "image/png", PNG)

    again, created = store.ingest(SCOPE, PNG_HEX, "image/jpeg", PNG)

    assert created is False
    assert again.media_type == "image/png"


def test_the_media_type_is_stored_bare_and_lowercased(objects: BlobObjects) -> None:
    """Spec F3 canonical encoding: lowercase media type, no parameters."""
    stored, _ = BlobStore(objects).ingest(SCOPE, PNG_HEX, "IMAGE/PNG; name=a.png", PNG)
    assert stored.media_type == "image/png"


def test_an_unknown_digest_reads_as_none(objects: BlobObjects) -> None:
    assert BlobStore(objects).read(SCOPE, "0" * 64) is None


def test_a_digest_from_another_run_reads_as_none(objects: BlobObjects) -> None:
    store = BlobStore(objects)
    store.ingest(SCOPE, PNG_HEX, "image/png", PNG)
    assert store.read(BlobScope.for_caller(ALICE, RUN_B), PNG_HEX) is None


def test_a_digest_from_another_tenant_reads_as_none(objects: BlobObjects) -> None:
    store = BlobStore(objects)
    store.ingest(SCOPE, PNG_HEX, "image/png", PNG)
    assert store.read(BlobScope.for_caller(BOB, RUN_A), PNG_HEX) is None
    assert store.read(BlobScope.for_caller(None, RUN_A), PNG_HEX) is None


@pytest.mark.parametrize("digest", ["../" + "a" * 61, "A" * 64, "a" * 63, "", "a" * 64 + "/x"])
def test_a_malformed_digest_reads_as_none(objects: BlobObjects, digest: str) -> None:
    assert BlobStore(objects).read(SCOPE, digest) is None


# --- ingest refusals -------------------------------------------------------------------------


def test_bytes_that_do_not_hash_to_the_claimed_digest_are_refused(objects: BlobObjects) -> None:
    store = BlobStore(objects)
    with pytest.raises(BlobDigestMismatch) as caught:
        store.ingest(SCOPE, "0" * 64, "image/png", PNG)
    assert caught.value.code == BLOB_DIGEST_MISMATCH == "x.blob_digest_mismatch"
    assert caught.value.permanent is True
    assert caught.value.at == "ingest"
    # INVARIANT: nothing is stored under a digest the bytes do not match.
    assert store.read(SCOPE, "0" * 64) is None
    assert store.read(SCOPE, PNG_HEX) is None


def test_a_malformed_claimed_digest_is_a_mismatch(objects: BlobObjects) -> None:
    with pytest.raises(BlobDigestMismatch):
        BlobStore(objects).ingest(SCOPE, "../escape", "image/png", PNG)


def test_a_blob_over_the_cap_is_refused(objects: BlobObjects) -> None:
    store = BlobStore(objects, BlobPolicy(max_bytes=len(PNG) - 1))
    with pytest.raises(BlobTooLarge) as caught:
        store.ingest(SCOPE, PNG_HEX, "image/png", PNG)
    assert caught.value.code == BLOB_TOO_LARGE == "x.blob_too_large"
    assert store.read(SCOPE, PNG_HEX) is None


def test_a_blob_exactly_at_the_cap_is_accepted(objects: BlobObjects) -> None:
    stored, _ = BlobStore(objects, BlobPolicy(max_bytes=len(PNG))).ingest(
        SCOPE, PNG_HEX, "image/png", PNG
    )
    assert stored.size_bytes == len(PNG)


@pytest.mark.parametrize("media_type", ["text/plain", "image/svg+xml", "", "application/json"])
def test_a_media_type_outside_the_allowlist_is_refused(
    objects: BlobObjects, media_type: str
) -> None:
    store = BlobStore(objects)
    with pytest.raises(BlobUnsupportedMediaType) as caught:
        store.ingest(SCOPE, PNG_HEX, media_type, PNG)
    assert caught.value.code == BLOB_UNSUPPORTED_MEDIA_TYPE == "x.blob_unsupported_media_type"
    assert store.read(SCOPE, PNG_HEX) is None


def test_the_defaults_are_the_owner_decided_limits() -> None:
    """Owner decision 2026-10-28 (Q4a): 8,000,000 B and the five attachment types (spec F1b)."""
    assert DEFAULT_BLOB_MAX_BYTES == 8_000_000
    assert (
        frozenset({"image/png", "image/jpeg", "image/gif", "image/webp", "application/pdf"})
        == ATTACHMENT_MEDIA_TYPES
    )
    policy = BlobPolicy()
    assert policy.max_bytes == DEFAULT_BLOB_MAX_BYTES
    assert policy.media_types == ATTACHMENT_MEDIA_TYPES


# --- read-side integrity ---------------------------------------------------------------------


def _corrupt_filesystem(root: Path) -> None:
    [data] = [p for p in root.rglob("*") if p.is_file() and p.name == PNG_HEX]
    data.write_bytes(b"bit rot")


def test_corrupted_stored_bytes_fail_the_read_and_are_logged_without_bytes(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    root = tmp_path / "artifacts"
    store = BlobStore(FilesystemBlobObjects(root))
    store.ingest(SCOPE, PNG_HEX, "image/png", PNG)
    _corrupt_filesystem(root)

    with caplog.at_level(logging.ERROR), pytest.raises(BlobDigestMismatch) as caught:
        store.read(SCOPE, PNG_HEX)

    assert caught.value.at == "read"
    assert caught.value.permanent is True
    [record] = [r for r in caplog.records if "corrupt" in r.getMessage()]
    message = record.getMessage()
    assert PNG_HEX in message
    assert "bit rot" not in message
    # INVARIANT: the run id (topic) is a bearer capability and never reaches a log.
    assert RUN_A not in message
    assert ALICE not in message


def test_corrupted_s3_bytes_fail_the_read() -> None:
    fake = _FakeS3()
    store = BlobStore(_s3_objects(fake))
    store.ingest(SCOPE, PNG_HEX, "image/png", PNG)
    [key] = [k for k in fake.objects if k.endswith(PNG_HEX)]
    fake.objects[key] = b"tampered"

    with pytest.raises(BlobDigestMismatch):
        store.read(SCOPE, PNG_HEX)


def test_s3_object_keys_live_under_the_blobs_prefix_without_the_email() -> None:
    fake = _FakeS3()
    BlobStore(_s3_objects(fake)).ingest(SCOPE, PNG_HEX, "image/png", PNG)
    assert fake.objects
    for key in fake.objects:
        assert key.startswith("blobs/")
        assert ALICE not in key


def test_ingest_logs_digest_and_size_never_bytes(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.INFO):
        BlobStore(FilesystemBlobObjects(tmp_path)).ingest(SCOPE, PNG_HEX, "image/png", PNG)
    text = "\n".join(r.getMessage() for r in caplog.records)
    assert PNG_HEX in text
    assert str(len(PNG)) in text
    assert "pixels" not in text
    assert RUN_A not in text


# --- retention -------------------------------------------------------------------------------


def test_sweep_ages_out_blobs_older_than_the_ttl(tmp_path: Path) -> None:
    root = tmp_path / "artifacts"
    store = BlobStore(FilesystemBlobObjects(root))
    store.ingest(SCOPE, PNG_HEX, "image/png", PNG)
    old = time.time() - 1_000
    for path in root.rglob("*"):
        if path.is_file():
            os.utime(path, (old, old))

    removed = store.sweep(ttl_seconds=10)

    assert removed >= 1
    assert store.read(SCOPE, PNG_HEX) is None


def test_sweep_keeps_young_blobs(tmp_path: Path) -> None:
    store = BlobStore(FilesystemBlobObjects(tmp_path / "artifacts"))
    store.ingest(SCOPE, PNG_HEX, "image/png", PNG)
    assert store.sweep(ttl_seconds=3_600) == 0
    assert store.read(SCOPE, PNG_HEX) is not None


def test_sweep_never_touches_files_outside_the_blobs_prefix(tmp_path: Path) -> None:
    """INVARIANT: blobs share `artifacts_dir` with result parcels; the sweep takes only its own."""
    root = tmp_path / "artifacts"
    root.mkdir()
    parcel = root / ("c" * 64)
    parcel.write_bytes(b"result parcel")
    old = time.time() - 1_000
    os.utime(parcel, (old, old))

    BlobStore(FilesystemBlobObjects(root)).sweep(ttl_seconds=10)

    assert parcel.is_file()


def test_sweep_of_an_empty_store_is_zero(tmp_path: Path) -> None:
    assert BlobStore(FilesystemBlobObjects(tmp_path / "nothing")).sweep(ttl_seconds=10) == 0


def test_s3_sweep_is_the_bucket_lifecycle_rule() -> None:
    assert BlobStore(_s3_objects(_FakeS3())).sweep(ttl_seconds=10) == 0


# --- the OME-1545 reader port ----------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_scoped_reader_reads_a_sha256_prefixed_digest(objects: BlobObjects) -> None:
    store = BlobStore(objects)
    store.ingest(SCOPE, PNG_HEX, "image/png", PNG)
    assert await ScopedBlobReader(store, SCOPE).read(f"sha256:{PNG_HEX}") == PNG


@pytest.mark.asyncio
@pytest.mark.parametrize("digest", [PNG_HEX, f"md5:{PNG_HEX}", f"blob:sha256/{PNG_HEX}"])
async def test_the_scoped_reader_refuses_any_other_digest_spelling(
    objects: BlobObjects, digest: str
) -> None:
    store = BlobStore(objects)
    store.ingest(SCOPE, PNG_HEX, "image/png", PNG)
    assert await ScopedBlobReader(store, SCOPE).read(digest) is None


@pytest.mark.asyncio
async def test_the_scoped_reader_sees_only_its_own_run(objects: BlobObjects) -> None:
    store = BlobStore(objects)
    store.ingest(SCOPE, PNG_HEX, "image/png", PNG)
    other = ScopedBlobReader(store, BlobScope.for_caller(ALICE, RUN_B))
    assert await other.read(f"sha256:{PNG_HEX}") is None


@pytest.mark.asyncio
async def test_the_scoped_reader_surfaces_corruption_as_the_typed_mismatch(
    tmp_path: Path,
) -> None:
    root = tmp_path / "artifacts"
    store = BlobStore(FilesystemBlobObjects(root))
    store.ingest(SCOPE, PNG_HEX, "image/png", PNG)
    _corrupt_filesystem(root)
    with pytest.raises(BlobDigestMismatch):
        await ScopedBlobReader(store, SCOPE).read(f"sha256:{PNG_HEX}")
