"""#1603 review round 2 (HupBaHa, 2026-11-04): bounded reads, a closed sidecar, atomic first write.

FEATURE: run blob store (OME-1540), epic OME-1529.
STORY: as an operator, a corrupt or hostile object in blob storage can neither exhaust the App's
memory nor make the engine serve a file under a type it never accepted; as a client, two
simultaneous first uploads of one file get exactly one 201.

INVARIANT (owner decision 2026-11-04, item 2): a backend read stops at `max_bytes + 1` bytes and
an object past the cap is permanent typed corruption — never materialised whole first.
INVARIANT (item 3): the sidecar is a CLOSED schema — exactly `media_type` + `size_bytes`, the type
in the allowed set, the size equal to the stored bytes, the signature checked when the policy says
so. Anything else is permanent typed corruption (`x.blob_digest_mismatch`), served `private,
no-store`, never a raw JSONDecodeError 500.
INVARIANT (item 5): the first write of a blob's metadata is create-exclusive, so of two racing
first uploads exactly one reports `created`.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import threading
from collections.abc import Iterator
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
    BLOB_DIGEST_MISMATCH,
    SIDECAR_MAX_BYTES,
    BlobCorrupted,
    BlobDigestMismatch,
    BlobPolicy,
    BlobScope,
    BlobStore,
    FilesystemBlobObjects,
    S3BlobObjects,
)
from screamingface_engine.artifacts.s3 import S3ArtifactStore, S3Config
from screamingface_engine.artifacts.sigv4 import Credentials
from screamingface_engine.artifacts.wiring import (
    BlobStoreNotConfigured,
    blob_objects_from_values,
    blob_reader_from_env,
)
from screamingface_engine.auth import JwtCodec
from screamingface_engine.config import Settings
from screamingface_engine.testing import InMemoryEventStream

SECRET = "blob-round2-secret-0123456789abcdef0123456789"
T0 = datetime(2026, 11, 4, 12, 0, 0, tzinfo=UTC)
RUN = "e" * 64
ALICE = "alice@example.org"
SCOPE = BlobScope.for_caller(ALICE, RUN)
PDF = b"%PDF-1.7\n" + b"round2" * 20
PDF_HEX = hashlib.sha256(PDF).hexdigest()
KEY = f"{SCOPE.key_prefix}/{PDF_HEX}"
SIDECAR = f"{KEY}.json"
GOOD_META = {"media_type": "application/pdf", "size_bytes": len(PDF)}


# --- backends ----------------------------------------------------------------------------------


class _StreamingFakeS3:
    """An S3 endpoint that streams bodies, counts what the client pulled, and honours
    `If-None-Match: *` the way AWS S3 does (412 when the key exists)."""

    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}
        self.requests: list[httpx.Request] = []
        self.bytes_pulled = 0

    def _chunks(self, body: bytes) -> Iterator[bytes]:
        for at in range(0, len(body), 1024):
            chunk = body[at : at + 1024]
            self.bytes_pulled += len(chunk)
            yield chunk

    def _put(self, key: str, request: httpx.Request) -> httpx.Response:
        if request.headers.get("if-none-match") == "*" and key in self.objects:
            return httpx.Response(412, text="PreconditionFailed")
        self.objects[key] = request.content
        return httpx.Response(200)

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        key = request.url.path.split("/", 2)[2]
        if request.method == "PUT":
            return self._put(key, request)
        body = self.objects.get(key)
        if body is None:
            return httpx.Response(404, text="NoSuchKey")
        return httpx.Response(200, stream=httpx.ByteStream(b"".join(self._chunks(body))))


class _LazyStreamingFakeS3(_StreamingFakeS3):
    """Same, but the body is a true lazy iterator: bytes count only once the client reads them."""

    def handle(self, request: httpx.Request) -> httpx.Response:
        key = request.url.path.split("/", 2)[2]
        if request.method == "GET" and key in self.objects:
            self.requests.append(request)
            return httpx.Response(200, content=self._chunks(self.objects[key]))
        return super().handle(request)


def _s3_store(fake: _StreamingFakeS3) -> S3ArtifactStore:
    config = S3Config(
        endpoint_url="http://blobs.garage.svc:3900",
        bucket="blobs",
        credentials=Credentials(access_key="GKblobs", secret_key="blobs-secret", region="garage"),
    )
    return S3ArtifactStore(
        config, client_factory=lambda: httpx.Client(transport=httpx.MockTransport(fake.handle))
    )


def _s3(fake: _StreamingFakeS3) -> S3BlobObjects:
    return S3BlobObjects(_s3_store(fake))


@pytest.fixture(params=["filesystem", "s3"])
def objects(
    request: pytest.FixtureRequest, tmp_path: Path
) -> FilesystemBlobObjects | S3BlobObjects:
    if request.param == "filesystem":
        return FilesystemBlobObjects(tmp_path / "blobs")
    return _s3(_StreamingFakeS3())


def _plant(objects: FilesystemBlobObjects | S3BlobObjects, body: bytes, meta: bytes) -> None:
    """Write a blob straight into the backend, as a hostile or corrupt store would hold it."""
    objects.put(KEY, body)
    objects.put(SIDECAR, meta)


# --- item 2: bounded backend reads -------------------------------------------------------------


def test_a_backend_read_past_the_cap_is_typed_corruption(
    objects: FilesystemBlobObjects | S3BlobObjects,
) -> None:
    objects.put(KEY, b"x" * 101)
    with pytest.raises(BlobCorrupted):
        objects.get_at_most(KEY, 100)
    assert objects.get_at_most(KEY, 101) == b"x" * 101
    assert objects.get_at_most(f"{KEY}-absent", 100) is None


def test_a_stored_object_larger_than_the_policy_is_never_served(
    objects: FilesystemBlobObjects | S3BlobObjects,
) -> None:
    # The sidecar claims a size within the cap; the data object holds more than the cap.
    big = PDF + b"\x00" * 64
    _plant(objects, big, json.dumps(GOOD_META).encode())
    store = BlobStore(objects, BlobPolicy(max_bytes=len(PDF)))
    with pytest.raises(BlobCorrupted) as caught:
        store.read(SCOPE, PDF_HEX)
    assert caught.value.code == BLOB_DIGEST_MISMATCH
    assert caught.value.permanent is True


def test_an_s3_read_stops_pulling_at_the_cap() -> None:
    """INVARIANT: streamed, never `response.content` — a hostile 1 MB object costs ~cap bytes."""
    fake = _LazyStreamingFakeS3()
    objects = _s3(fake)
    fake.objects[KEY] = b"x" * 1_000_000
    with pytest.raises(BlobCorrupted):
        objects.get_at_most(KEY, 10_000)
    # One 64 KiB read chunk of slack at most past the cap — never the whole megabyte.
    assert fake.bytes_pulled <= 10_000 + 1 + 64 * 1024
    assert fake.bytes_pulled < 1_000_000


def test_an_oversize_sidecar_is_typed_corruption(
    objects: FilesystemBlobObjects | S3BlobObjects,
) -> None:
    padded = json.dumps({**GOOD_META, "pad": "p" * SIDECAR_MAX_BYTES}).encode()
    _plant(objects, PDF, padded)
    with pytest.raises(BlobCorrupted):
        BlobStore(objects).read(SCOPE, PDF_HEX)


# --- item 3: the closed sidecar schema ---------------------------------------------------------


_BAD_SIDECARS = [
    pytest.param(b'{"media_type": "application/pdf", "size_by', id="truncated-json"),
    pytest.param(b"\xff\xfe not utf-8", id="not-utf8"),
    pytest.param(b'["application/pdf", 10]', id="not-an-object"),
    pytest.param(json.dumps({"media_type": "application/pdf"}).encode(), id="missing-size"),
    pytest.param(json.dumps({**GOOD_META, "extra": 1}).encode(), id="extra-key"),
    pytest.param(json.dumps({**GOOD_META, "size_bytes": str(len(PDF))}).encode(), id="size-str"),
    pytest.param(json.dumps({**GOOD_META, "size_bytes": True}).encode(), id="size-bool"),
    pytest.param(json.dumps({**GOOD_META, "size_bytes": -1}).encode(), id="size-negative"),
    pytest.param(json.dumps({**GOOD_META, "size_bytes": len(PDF) - 1}).encode(), id="size-wrong"),
    pytest.param(json.dumps({**GOOD_META, "media_type": 7}).encode(), id="type-not-str"),
    pytest.param(json.dumps({**GOOD_META, "media_type": "text/html"}).encode(), id="text-html"),
    pytest.param(
        json.dumps({**GOOD_META, "media_type": "APPLICATION/PDF"}).encode(), id="type-not-bare"
    ),
]


@pytest.mark.parametrize("meta", _BAD_SIDECARS)
def test_an_invalid_sidecar_is_permanent_typed_corruption(
    objects: FilesystemBlobObjects | S3BlobObjects, meta: bytes
) -> None:
    _plant(objects, PDF, meta)
    with pytest.raises(BlobCorrupted) as caught:
        BlobStore(objects).read(SCOPE, PDF_HEX)
    assert isinstance(caught.value, BlobDigestMismatch)  # the existing read-corruption family
    assert caught.value.code == BLOB_DIGEST_MISMATCH


def test_a_sidecar_type_outside_the_policy_is_refused(
    objects: FilesystemBlobObjects | S3BlobObjects,
) -> None:
    _plant(objects, PDF, json.dumps(GOOD_META).encode())
    narrowed = BlobPolicy(media_types=frozenset({"image/png"}))
    with pytest.raises(BlobCorrupted):
        BlobStore(objects, narrowed).read(SCOPE, PDF_HEX)


def test_the_signature_is_checked_on_read_when_the_policy_says_so(
    objects: FilesystemBlobObjects | S3BlobObjects,
) -> None:
    # Digest and size are right; the sidecar labels PDF bytes as a PNG.
    _plant(objects, PDF, json.dumps({"media_type": "image/png", "size_bytes": len(PDF)}).encode())
    with pytest.raises(BlobCorrupted):
        BlobStore(objects, BlobPolicy(verify_signature=True)).read(SCOPE, PDF_HEX)


def test_a_valid_sidecar_still_reads(objects: FilesystemBlobObjects | S3BlobObjects) -> None:
    _plant(objects, PDF, json.dumps(GOOD_META).encode())
    found = BlobStore(objects, BlobPolicy(verify_signature=True)).read(SCOPE, PDF_HEX)
    assert found is not None
    assert found[0].media_type == "application/pdf"
    assert found[1] == PDF


def test_a_reupload_heals_a_corrupt_sidecar(
    objects: FilesystemBlobObjects | S3BlobObjects,
) -> None:
    _plant(objects, PDF, b'{"media_type": "appl')
    store = BlobStore(objects)
    blob, _created = store.ingest(SCOPE, PDF_HEX, "application/pdf", PDF)
    assert blob.media_type == "application/pdf"
    found = store.read(SCOPE, PDF_HEX)
    assert found is not None
    assert found[1] == PDF


# --- the routes: corruption is a typed, uncached 500 -------------------------------------------


def _cap() -> dict[str, str]:
    token = JwtCodec(secret=SECRET, iat_window_s=60, capability_lifetime_s=58_800).sign(RUN, T0)
    return {"URL4-Capability": token, "X-User-Email": ALICE}


def _app(tmp_path: Path) -> FastAPI:
    settings = Settings.model_validate(
        {
            "jwt_secret": SECRET,
            "iat_window_s": 60,
            "artifacts_dir": str(tmp_path / "artifacts"),
            "blob_store": "filesystem",
            "blobs_dir": str(tmp_path / "blobs"),
        }
    )
    return create_app(
        settings, stream=InMemoryEventStream(), job_runner=RecordingJobRunner(), clock=lambda: T0
    )


def _client(app: FastAPI) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


@pytest.mark.asyncio
async def test_a_sidecar_claiming_text_html_is_refused_not_served(tmp_path: Path) -> None:
    """The review's probe: a planted `text/html` sidecar over a script body, digest correct."""
    script = b"<script>alert(document.cookie)</script>"
    digest = hashlib.sha256(script).hexdigest()
    objects = FilesystemBlobObjects(tmp_path / "blobs")
    key = f"{SCOPE.key_prefix}/{digest}"
    objects.put(key, script)
    objects.put(
        f"{key}.json", json.dumps({"media_type": "text/html", "size_bytes": len(script)}).encode()
    )

    async with _client(_app(tmp_path)) as client:
        response = await client.get(f"/blob/sha256/{digest}", headers=_cap())

    assert response.status_code == 500
    assert response.headers["content-type"] == "application/problem+json"
    assert response.headers["cache-control"] == "private, no-store"
    assert response.json()["code"] == BLOB_DIGEST_MISMATCH
    assert response.json()["permanent"] is True
    assert b"<script>" not in response.content


@pytest.mark.asyncio
async def test_truncated_metadata_is_a_typed_uncached_500(tmp_path: Path) -> None:
    objects = FilesystemBlobObjects(tmp_path / "blobs")
    objects.put(KEY, PDF)
    objects.put(SIDECAR, b'{"media_type": "application/pdf", "size')

    async with _client(_app(tmp_path)) as client:
        response = await client.get(f"/blob/sha256/{PDF_HEX}", headers=_cap())

    assert response.status_code == 500
    assert response.headers["content-type"] == "application/problem+json"
    assert response.headers["cache-control"] == "private, no-store"
    assert response.json()["code"] == BLOB_DIGEST_MISMATCH
    assert response.json()["permanent"] is True


# --- item 5: concurrent first uploads ----------------------------------------------------------


class _RacingFilesystem(FilesystemBlobObjects):
    """Holds every first-upload existence check until both uploads have made it, so both race
    to the metadata write — the interleaving that let both answer 201."""

    def __init__(self, root: Path, parties: int) -> None:
        super().__init__(root)
        self._barrier = threading.Barrier(parties, timeout=5)
        self._held = 0
        self._lock = threading.Lock()

    def get_at_most(self, key: str, max_bytes: int) -> bytes | None:
        found = super().get_at_most(key, max_bytes)
        with self._lock:
            hold = key.endswith(".json") and self._held < self._barrier.parties
            self._held += hold
        if hold:
            self._barrier.wait()
        return found


def test_two_racing_first_uploads_create_exactly_once(tmp_path: Path) -> None:
    store = BlobStore(_RacingFilesystem(tmp_path / "blobs", parties=2))
    results: list[bool] = []

    def upload() -> None:
        results.append(store.ingest(SCOPE, PDF_HEX, "application/pdf", PDF)[1])

    threads = [threading.Thread(target=upload) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)

    assert sorted(results) == [False, True]
    assert store.read(SCOPE, PDF_HEX) is not None


@pytest.mark.asyncio
async def test_two_racing_first_upload_requests_get_one_201(tmp_path: Path) -> None:
    app = _app(tmp_path)
    app.state.blob_store = BlobStore(
        _RacingFilesystem(tmp_path / "blobs", parties=2), BlobPolicy(verify_signature=True)
    )
    headers = {**_cap(), "Content-Type": "application/pdf"}
    async with _client(app) as client:
        first, second = await asyncio.gather(
            client.put(f"/blob/sha256/{PDF_HEX}", content=PDF, headers=headers),
            client.put(f"/blob/sha256/{PDF_HEX}", content=PDF, headers=headers),
        )
    assert sorted((first.status_code, second.status_code)) == [200, 201]
    assert first.json() == second.json()


def test_the_s3_metadata_write_is_conditional() -> None:
    fake = _StreamingFakeS3()
    store = BlobStore(_s3(fake))
    store.ingest(SCOPE, PDF_HEX, "application/pdf", PDF)
    (sidecar_put,) = [
        r for r in fake.requests if r.method == "PUT" and r.url.path.endswith(".json")
    ]
    assert sidecar_put.headers["if-none-match"] == "*"
    # INVARIANT: the condition is SIGNED, so it cannot be stripped in transit undetected.
    assert "if-none-match" in sidecar_put.headers["authorization"]


def test_an_s3_412_on_the_metadata_write_means_another_upload_won() -> None:
    """The S3 race: our existence check saw nothing, then another upload's sidecar landed."""
    fake = _StreamingFakeS3()
    winner = {"media_type": "application/pdf", "size_bytes": len(PDF)}

    class _LateWinner(S3BlobObjects):
        planted = False

        def put(self, key: str, data: bytes) -> None:
            super().put(key, data)
            if key == KEY and not self.planted:
                self.planted = True
                fake.objects[SIDECAR] = json.dumps(winner).encode()

    racing = _LateWinner(_s3_store(fake))
    blob, created = BlobStore(racing).ingest(SCOPE, PDF_HEX, "application/pdf", PDF)
    assert created is False
    assert blob.media_type == "application/pdf"


# --- item 1: no blob store of its own → blob upload and fetch are off -------------------------


_ARTIFACT_S3_ENV = {
    job_env.ARTIFACT_STORE: "s3",
    job_env.ARTIFACT_S3_ENDPOINT_URL: "http://results.garage.svc:3900",
    job_env.ARTIFACT_S3_BUCKET: "paid-results",
    job_env.ARTIFACT_S3_ACCESS_KEY: "GKresults",
    job_env.ARTIFACT_S3_SECRET_KEY: "results-secret",
}


@pytest.mark.parametrize(
    "values",
    [
        pytest.param({}, id="nothing"),
        pytest.param({job_env.BLOB_STORE: "  "}, id="blank"),
        pytest.param(_ARTIFACT_S3_ENV, id="artifact-s3-only"),
        pytest.param({job_env.ARTIFACTS_DIR: "/tmp/artifacts"}, id="artifact-dir-only"),
    ],
)
def test_an_unset_blob_store_never_follows_the_artifact_store(values: dict[str, str]) -> None:
    """The review's reproduction: `artifact_bucket=blob_bucket=paid-results` must be impossible."""
    with pytest.raises(BlobStoreNotConfigured, match=job_env.BLOB_STORE):
        blob_objects_from_values(values)


def test_the_runner_refuses_a_blob_reader_without_a_blob_store() -> None:
    env = {job_env.TOPIC: RUN, **_ARTIFACT_S3_ENV}
    with pytest.raises(BlobStoreNotConfigured):
        blob_reader_from_env(env)


def _unconfigured_app(tmp_path: Path) -> FastAPI:
    settings = Settings.model_validate(
        {"jwt_secret": SECRET, "iat_window_s": 60, "artifacts_dir": str(tmp_path / "artifacts")}
    )
    return create_app(
        settings, stream=InMemoryEventStream(), job_runner=RecordingJobRunner(), clock=lambda: T0
    )


def test_an_app_without_a_blob_store_starts_with_blobs_off(tmp_path: Path) -> None:
    assert _unconfigured_app(tmp_path).state.blob_store is None


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["PUT", "GET"])
async def test_the_blob_routes_answer_a_typed_503_without_a_blob_store(
    tmp_path: Path, method: str
) -> None:
    async with _client(_unconfigured_app(tmp_path)) as client:
        response = await client.request(
            method,
            f"/blob/sha256/{PDF_HEX}",
            content=PDF if method == "PUT" else None,
            headers={**_cap(), "Content-Type": "application/pdf"},
        )
    assert response.status_code == 503, response.text
    assert response.headers["content-type"] == "application/problem+json"
    assert response.headers["cache-control"] == "private, no-store"
    # WHY no Retry-After and permanent: only an operator's configuration change ends this state.
    assert "retry-after" not in response.headers
    assert response.json()["permanent"] is True
    assert job_env.BLOB_STORE in response.json()["detail"]
    # INVARIANT: nothing landed in the artifact (paid-results) store.
    assert not [p for p in (tmp_path / "artifacts").rglob("*") if p.is_file()]


@pytest.mark.asyncio
async def test_an_unconfigured_blob_store_still_needs_a_capability_token(tmp_path: Path) -> None:
    async with _client(_unconfigured_app(tmp_path)) as client:
        response = await client.get(f"/blob/sha256/{PDF_HEX}")
    assert response.status_code == 401
