"""`S3ArtifactStore` — the adapter that survives the Runner Job (OME-929).

FEATURE: an over-cap result parked by a Runner Job pod is still fetchable by the App pod
after that Job is gone.

INVARIANT (the bug this adapter exists to kill): the writer and the reader share NO
filesystem. Every test here builds them as separate instances against a fake endpoint, which
is the arrangement the previous single-`ArtifactStore` design could not express — and
therefore could not test.

The fake S3 is `httpx.MockTransport`: it asserts on the request we ACTUALLY send, so a
signing or path regression is caught here rather than as an opaque 403 in a cluster.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import ClassVar

import httpx
import pytest

from screamingface_engine.artifacts import RemoteStream
from screamingface_engine.artifacts.s3 import S3ArtifactStore, S3Config, S3StorageError
from screamingface_engine.artifacts.sigv4 import Credentials

BUCKET = "artifacts"
ENDPOINT = "http://garage.svc:3900"


def _config() -> S3Config:
    return S3Config(
        endpoint_url=ENDPOINT,
        bucket=BUCKET,
        credentials=Credentials(
            access_key="GKtestaccess", secret_key="testsecret", region="garage"
        ),
    )


class _FakeS3:
    """Objects in a dict, plus the requests it saw — a stand-in for Garage."""

    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}
        self.requests: list[httpx.Request] = []
        self.force_status: int | None = None

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.force_status is not None:
            return httpx.Response(self.force_status, text="forced")
        key = request.url.path.rsplit("/", 1)[-1]
        return self._DISPATCH[request.method](self, key, request)

    def _put(self, key: str, request: httpx.Request) -> httpx.Response:
        self.objects[key] = request.content
        return httpx.Response(200)

    def _delete(self, key: str, _request: httpx.Request) -> httpx.Response:
        self.objects.pop(key, None)
        return httpx.Response(204)

    def _head(self, key: str, _request: httpx.Request) -> httpx.Response:
        body = self.objects.get(key)
        if body is None:
            return httpx.Response(404, text="NoSuchKey")
        return httpx.Response(200, headers={"content-length": str(len(body))})

    def _get(self, key: str, _request: httpx.Request) -> httpx.Response:
        body = self.objects.get(key)
        if body is None:
            return httpx.Response(404, text="NoSuchKey")
        return httpx.Response(200, content=body)

    _DISPATCH: ClassVar[dict[str, Callable[[_FakeS3, str, httpx.Request], httpx.Response]]] = {
        "PUT": _put,
        "DELETE": _delete,
        "HEAD": _head,
        "GET": _get,
    }

    def store(self) -> S3ArtifactStore:
        """A store wired to this fake — call twice for an independent writer and reader."""
        return S3ArtifactStore(
            _config(),
            client_factory=lambda: httpx.Client(transport=httpx.MockTransport(self.handle)),
            async_client_factory=lambda: httpx.AsyncClient(
                transport=httpx.MockTransport(self.handle)
            ),
        )


async def _drain(content: RemoteStream) -> bytes:
    return b"".join([chunk async for chunk in content.stream])


# --- the acceptance test for OME-929 -----------------------------------------------------


@pytest.mark.asyncio
async def test_a_writer_and_a_reader_sharing_no_filesystem_round_trip_a_result() -> None:
    """STORY: as a researcher, my 100-case benchmark result reaches me even though the Job
    that produced it has exited and its disk is gone.

    This is the test whose absence let OME-929 ship: every prior artifact test used ONE
    store instance in ONE process, so none of them could express a writer/reader split.
    """
    fake = _FakeS3()
    runner_side = fake.store()
    app_side = fake.store()
    payload = b'{"cases":[' + b"1," * 200_000 + b"1]}"

    ticket = runner_side.write_bytes(payload)
    content = app_side.content(ticket.id)

    assert isinstance(content, RemoteStream)
    assert await _drain(content) == payload
    assert content.size_bytes == len(payload)


def test_the_ticket_is_the_content_address_and_the_real_size() -> None:
    fake = _FakeS3()
    payload = b"result-bytes"

    ticket = fake.store().write_bytes(payload)

    assert ticket.size_bytes == len(payload)
    assert ticket.id == ticket.sha256
    assert len(ticket.id) == 64


# --- the request we actually put on the wire ---------------------------------------------


def test_the_upload_targets_the_bucket_and_declares_its_payload_hash() -> None:
    """INVARIANT: `x-amz-content-sha256` IS the artifact id — one hash, computed once.

    S3 requires that header, and the value it requires is exactly the content address we
    already have, so a second hash of a multi-megabyte body would be pure waste.
    """
    fake = _FakeS3()

    ticket = fake.store().write_bytes(b"payload")

    (request,) = fake.requests
    assert request.method == "PUT"
    assert request.url.path == f"/{BUCKET}/{ticket.id}"
    assert request.headers["x-amz-content-sha256"] == ticket.id
    assert request.headers["authorization"].startswith("AWS4-HMAC-SHA256 Credential=GKtestaccess/")
    assert "SignedHeaders=host;x-amz-content-sha256;x-amz-date" in request.headers["authorization"]


def test_every_signed_header_is_actually_sent() -> None:
    """INVARIANT: the SignedHeaders list and the sent headers cannot disagree.

    Signing a header we then omit (or vice versa) is the classic SigV4 defect, and the
    server reports it as an indistinguishable 403.
    """
    fake = _FakeS3()
    fake.store().write_bytes(b"payload")

    (request,) = fake.requests
    signed = request.headers["authorization"].split("SignedHeaders=")[1].split(",")[0]
    for name in signed.split(";"):
        assert name in request.headers, f"signed {name!r} but did not send it"


# --- error paths -------------------------------------------------------------------------


def test_a_missing_object_reads_as_absent_not_as_a_failure() -> None:
    """A 404 is the honest "no such ticket" the route turns into its own 404."""
    assert _FakeS3().store().content("a" * 64) is None


def test_a_malformed_id_never_reaches_the_network() -> None:
    """INVARIANT: id validation happens before signing, so a traversal attempt cannot even
    become a request — the same guard the filesystem adapter applies to paths."""
    fake = _FakeS3()

    assert fake.store().content("../../secrets") is None
    assert fake.requests == []


def test_a_rejected_signature_raises_rather_than_reading_as_absent() -> None:
    """WHY not None: a 403 means our credentials or signing are wrong, which is an operator
    problem. Collapsing it into "artifact missing" would present a misconfiguration as a
    expired-parcel 404 — exactly the misdiagnosis that cost OME-929 its first investigation.
    """
    fake = _FakeS3()
    fake.force_status = 403

    with pytest.raises(S3StorageError, match="403"):
        fake.store().content("a" * 64)


def test_a_failed_upload_raises_instead_of_minting_a_ticket() -> None:
    """INVARIANT: a ticket is a promise that the bytes are retrievable. Returning one for a
    failed PUT converts a loud upload error into a silent 404 at redemption time — the whole
    failure shape this ticket exists to remove."""
    fake = _FakeS3()
    fake.force_status = 500

    with pytest.raises(S3StorageError, match="500"):
        fake.store().write_bytes(b"payload")


def test_a_transport_failure_surfaces_as_a_storage_error() -> None:
    """A connection refused must not escape as a bare httpx error the callers do not expect."""

    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    store = S3ArtifactStore(
        _config(),
        client_factory=lambda: httpx.Client(transport=httpx.MockTransport(refuse)),
        async_client_factory=lambda: httpx.AsyncClient(transport=httpx.MockTransport(refuse)),
    )

    with pytest.raises(S3StorageError):
        store.write_bytes(b"payload")


# --- reclamation is delegated, and says so ----------------------------------------------


def test_sweep_is_a_no_op_because_expiry_belongs_to_the_bucket() -> None:
    """WHY 0 and not a listing: sweeping would need ListObjectsV2, whose query parameters
    push the signer past the PUT/GET bound spec D5 sets on it. Object expiry is a bucket
    lifecycle rule instead — configured in the chart, enforced by the store.

    AIDEV-NOTE: this returning 0 is load-bearing, not a stub. If the bucket has no lifecycle
    rule, artifacts never expire — see the ledger's known-limitations note.
    """
    assert _FakeS3().store().sweep(ttl_seconds=1.0) == 0


def test_delete_removes_the_object() -> None:
    fake = _FakeS3()
    ticket = fake.store().write_bytes(b"payload")

    fake.store().delete(ticket.id)

    assert ticket.id not in fake.objects
