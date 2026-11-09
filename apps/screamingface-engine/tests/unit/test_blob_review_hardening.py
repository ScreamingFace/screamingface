"""Blob store hardening from the #1603 review (Khoa, 2026-11-02; owner decisions 2026-11-03).

FEATURE: image and PDF inputs (epic OME-1529), run blob store (OME-1540).
STORY: as a url4 client uploading a picture, a storage outage tells me to retry (503 +
`Retry-After`) instead of a bare 500; a file whose bytes are not what it claims to be is
refused at upload; a fetched blob is never kept by a shared cache. As an operator, a typo in
`URL4_CLOUD_BLOB_MEDIA_TYPES` that would let the engine serve script from its own origin is
refused at boot.
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
from pydantic import ValidationError

from screamingface_engine.app import create_app
from screamingface_engine.artifacts.blobs import (
    ATTACHMENT_MEDIA_TYPES,
    BLOB_UNSUPPORTED_MEDIA_TYPE,
    DEFAULT_BLOB_MAX_BYTES,
    MEDIA_TYPE_SIGNATURES,
    BlobContentMismatch,
    BlobPolicy,
    BlobScope,
    BlobStore,
    FilesystemBlobObjects,
)
from screamingface_engine.artifacts.s3 import S3StorageError
from screamingface_engine.auth import JwtCodec
from screamingface_engine.config import Settings
from screamingface_engine.testing import InMemoryEventStream

SECRET = "rest-blob-hardening-secret-0123456789abcdef0"
WINDOW_S = 60
LIFETIME_S = 58_800
T0 = datetime(2026, 11, 3, 9, 0, 0, tzinfo=UTC)
RUN = "c" * 64
SCOPE = BlobScope.for_caller("alice@example.org", RUN)

# One body per attachment type, each opening with that type's real signature.
SAMPLES: dict[str, bytes] = {
    "application/pdf": b"%PDF-1.7\n" + b"page" * 20,
    "image/png": b"\x89PNG\r\n\x1a\n" + b"pixels" * 10,
    "image/jpeg": b"\xff\xd8\xff\xe0" + b"jfif" * 10,
    "image/gif": b"GIF89a" + b"frame" * 10,
    "image/webp": b"RIFF\x24\x00\x00\x00WEBPVP8 " + b"bits" * 10,
}


def _hex(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


def _cap(topic: str = RUN) -> dict[str, str]:
    return {
        "URL4-Capability": JwtCodec(
            secret=SECRET, iat_window_s=WINDOW_S, capability_lifetime_s=LIFETIME_S
        ).sign(topic, T0),
        "X-User-Email": "alice@example.org",
    }


def _app(tmp_path: Path, **overrides: object) -> FastAPI:
    settings = Settings.model_validate(
        {
            "jwt_secret": SECRET,
            "iat_window_s": WINDOW_S,
            "artifacts_dir": str(tmp_path / "artifacts"),
            # #1603 review round 2 (owner 2026-11-04): an unset blob store is OFF (503), so the
            # route tests configure one. WHY the same tmp directory: these tests pin route
            # behaviour and the on-disk layout below it; store separation is pinned in
            # test_blob_storage_isolation.py.
            "blob_store": "filesystem",
            "blobs_dir": str(tmp_path / "artifacts"),
            **overrides,
        }
    )
    return create_app(
        settings, stream=InMemoryEventStream(), job_runner=RecordingJobRunner(), clock=lambda: T0
    )


def _client(app: FastAPI) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


class _BrokenObjects:
    """A blob backend whose every call fails the way a sick store does."""

    def __init__(self, exc: Exception) -> None:
        self._exc = exc

    def put(self, key: str, data: bytes) -> None:
        raise self._exc

    def get(self, key: str) -> bytes | None:
        raise self._exc

    def sweep(self, ttl_seconds: float, *, now: float | None = None) -> int:
        return 0


# --- comment 2 (rest/blobs.py:117): storage failures are a retryable 503 problem ------------

_STORAGE_FAILURES = [
    pytest.param(S3StorageError("endpoint unreachable"), id="s3"),
    pytest.param(OSError(errno.ENOSPC, "No space left on device"), id="disk-full"),
    pytest.param(PermissionError(errno.EACCES, "Permission denied"), id="permission"),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", _STORAGE_FAILURES)
@pytest.mark.parametrize("method", ["PUT", "GET"])
async def test_a_storage_failure_is_a_503_problem_with_retry_after(
    tmp_path: Path, failure: Exception, method: str
) -> None:
    app = _app(tmp_path)
    app.state.blob_store = BlobStore(_BrokenObjects(failure))
    body = SAMPLES["application/pdf"]
    async with _client(app) as client:
        response = await client.request(
            method,
            f"/blob/sha256/{_hex(body)}",
            content=body if method == "PUT" else None,
            headers={**_cap(), "Content-Type": "application/pdf"},
        )

    assert response.status_code == 503, response.text
    assert response.headers["content-type"] == "application/problem+json"
    # INVARIANT: a whole number of seconds a client can sleep on (RFC 9110 §10.2.3).
    assert int(response.headers["retry-after"]) > 0
    problem = response.json()
    assert problem["status"] == 503
    assert problem["permanent"] is False
    # INVARIANT: the backend's own message (paths, endpoints) never reaches the client.
    assert str(failure) not in response.text


@pytest.mark.asyncio
async def test_a_storage_failure_is_logged_without_the_bytes(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    app = _app(tmp_path)
    app.state.blob_store = BlobStore(_BrokenObjects(OSError(errno.ENOSPC, "full")))
    body = SAMPLES["application/pdf"]
    with caplog.at_level("WARNING"):
        async with _client(app) as client:
            await client.put(
                f"/blob/sha256/{_hex(body)}",
                content=body,
                headers={**_cap(), "Content-Type": "application/pdf"},
            )
    logged = " ".join(r.getMessage() for r in caplog.records)
    assert "blob storage unavailable" in logged
    assert RUN not in logged  # the run id is the capability topic, a bearer secret
    assert "alice@example.org" not in logged


# --- comment 4 (config.py:135): the media-type setting is a subset of the attachment types --


@pytest.mark.parametrize(
    "unsafe", ["text/html", "image/svg+xml", "application/javascript", "text/plain", ""]
)
def test_a_media_type_outside_the_attachment_types_is_refused_at_config_load(
    unsafe: str,
) -> None:
    with pytest.raises(ValidationError, match="blob_media_types"):
        Settings.model_validate({"blob_media_types": ["image/png", unsafe]})


def test_the_refusal_names_the_offending_type_and_the_allowed_set() -> None:
    with pytest.raises(ValidationError) as caught:
        Settings.model_validate({"blob_media_types": ["image/svg+xml"]})
    message = str(caught.value)
    assert "image/svg+xml" in message
    for allowed in ATTACHMENT_MEDIA_TYPES:
        assert allowed in message


def test_a_subset_is_accepted_and_normalized() -> None:
    settings = Settings.model_validate({"blob_media_types": [" IMAGE/PNG ", "application/pdf"]})
    assert settings.blob_media_types == ["image/png", "application/pdf"]


def test_the_default_is_exactly_the_attachment_types() -> None:
    assert frozenset(Settings().blob_media_types) == ATTACHMENT_MEDIA_TYPES


def test_the_env_var_is_validated_too(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("URL4_CLOUD_BLOB_MEDIA_TYPES", '["text/html"]')
    with pytest.raises(ValidationError, match="text/html"):
        Settings()


# --- comment 5a (rest/blobs.py:157): a fetched blob is never cached ---------------------------


@pytest.mark.asyncio
async def test_a_fetched_blob_is_private_and_no_store(tmp_path: Path) -> None:
    body = SAMPLES["application/pdf"]
    path = f"/blob/sha256/{_hex(body)}"
    async with _client(_app(tmp_path)) as client:
        await client.put(path, content=body, headers={**_cap(), "Content-Type": "application/pdf"})
        got = await client.get(path, headers=_cap())
        missing = await client.get(f"/blob/sha256/{'0' * 64}", headers=_cap())

    assert got.status_code == 200
    assert got.headers["cache-control"] == "private, no-store"
    # WHY the 404 too: whether a run holds a digest is itself scoped information.
    assert missing.status_code == 404
    assert missing.headers["cache-control"] == "private, no-store"


# --- comment 5b (rest/blobs.py:157): the bytes must be what the label says --------------------


def test_the_signature_table_covers_exactly_the_attachment_types() -> None:
    # INVARIANT: a type added to ATTACHMENT_MEDIA_TYPES without a signature decision fails here.
    assert frozenset(MEDIA_TYPE_SIGNATURES) == ATTACHMENT_MEDIA_TYPES


@pytest.mark.parametrize("media_type", sorted(SAMPLES))
def test_bytes_matching_their_declared_type_are_accepted(tmp_path: Path, media_type: str) -> None:
    store = BlobStore(FilesystemBlobObjects(tmp_path), BlobPolicy(verify_signature=True))
    body = SAMPLES[media_type]
    stored, created = store.ingest(SCOPE, _hex(body), media_type, body)
    assert (stored.media_type, created) == (media_type, True)


@pytest.mark.parametrize("media_type", sorted(SAMPLES))
def test_bytes_of_another_type_are_refused_and_nothing_is_stored(
    tmp_path: Path, media_type: str
) -> None:
    store = BlobStore(FilesystemBlobObjects(tmp_path), BlobPolicy(verify_signature=True))
    impostor = b"<html><script>alert(1)</script></html>"
    with pytest.raises(BlobContentMismatch) as caught:
        store.ingest(SCOPE, _hex(impostor), media_type, impostor)
    assert caught.value.code == BLOB_UNSUPPORTED_MEDIA_TYPE
    assert store.read(SCOPE, _hex(impostor)) is None


def test_a_png_labelled_jpeg_is_refused(tmp_path: Path) -> None:
    store = BlobStore(FilesystemBlobObjects(tmp_path), BlobPolicy(verify_signature=True))
    png = SAMPLES["image/png"]
    with pytest.raises(BlobContentMismatch):
        store.ingest(SCOPE, _hex(png), "image/jpeg", png)


@pytest.mark.parametrize(
    "body",
    [
        b"RIFF\x24\x00\x00\x00AVI LIST",  # RIFF, but not WebP
        b"%PDF",  # a truncated signature
        b"GIF87",
        b"",
    ],
)
def test_near_misses_are_refused(tmp_path: Path, body: bytes) -> None:
    store = BlobStore(FilesystemBlobObjects(tmp_path), BlobPolicy(verify_signature=True))
    media_type = "image/webp" if body.startswith(b"RIFF") else "application/pdf"
    if body.startswith(b"GIF"):
        media_type = "image/gif"
    with pytest.raises(BlobContentMismatch):
        store.ingest(SCOPE, _hex(body), media_type, body)


def test_gif87a_is_a_gif(tmp_path: Path) -> None:
    store = BlobStore(FilesystemBlobObjects(tmp_path), BlobPolicy(verify_signature=True))
    body = b"GIF87a" + b"old" * 5
    stored, _ = store.ingest(SCOPE, _hex(body), "image/gif", body)
    assert stored.media_type == "image/gif"


@pytest.mark.asyncio
async def test_the_app_refuses_a_mislabelled_upload_with_415(tmp_path: Path) -> None:
    impostor = b"<svg xmlns='http://www.w3.org/2000/svg'><script/></svg>"
    path = f"/blob/sha256/{_hex(impostor)}"
    async with _client(_app(tmp_path)) as client:
        put = await client.put(
            path, content=impostor, headers={**_cap(), "Content-Type": "image/png"}
        )
        got = await client.get(path, headers=_cap())

    assert put.status_code == 415, put.text
    assert put.headers["content-type"] == "application/problem+json"
    assert put.json()["code"] == BLOB_UNSUPPORTED_MEDIA_TYPE
    assert put.json()["permanent"] is True
    assert got.status_code == 404


@pytest.mark.asyncio
@pytest.mark.parametrize("media_type", sorted(SAMPLES))
async def test_the_app_accepts_every_correctly_labelled_type(
    tmp_path: Path, media_type: str
) -> None:
    body = SAMPLES[media_type]
    async with _client(_app(tmp_path)) as client:
        put = await client.put(
            f"/blob/sha256/{_hex(body)}",
            content=body,
            headers={**_cap(), "Content-Type": media_type},
        )
    assert put.status_code == 201, put.text


# --- #1603 review round 3 (config.py:135): the App's per-blob cap never exceeds the Runner's ----
#
# WHY: the Runner's `blob_store_from_env` reads with the default policy (DEFAULT_BLOB_MAX_BYTES),
# so an App cap above it would store a blob the Runner then refuses as `x.blob_digest_mismatch`.
# A larger cap is refused at config load instead.


def test_blob_max_bytes_accepts_the_runner_cap() -> None:
    settings = Settings.model_validate({"blob_max_bytes": DEFAULT_BLOB_MAX_BYTES})
    assert settings.blob_max_bytes == 8_000_000 == DEFAULT_BLOB_MAX_BYTES


def test_blob_max_bytes_above_the_runner_cap_is_refused() -> None:
    with pytest.raises(ValidationError, match="blob_max_bytes"):
        Settings.model_validate({"blob_max_bytes": 8_000_001})


def test_blob_max_bytes_env_var_obeys_the_same_ceiling(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("URL4_CLOUD_BLOB_MAX_BYTES", "8000000")
    assert Settings().blob_max_bytes == 8_000_000
    monkeypatch.setenv("URL4_CLOUD_BLOB_MAX_BYTES", "8000001")
    with pytest.raises(ValidationError, match="blob_max_bytes"):
        Settings()
