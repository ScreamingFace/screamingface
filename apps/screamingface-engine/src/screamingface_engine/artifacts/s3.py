"""Content-addressed spill store on an S3-compatible endpoint.

FEATURE: over-cap results survive the Runner Job on a multi-pod deployment (OME-929).

WHY this exists: the filesystem adapter is correct only where the writer and the reader are
one process. On the hosted Engine the Runner is a Job pod whose disk dies with it, so a
~3 MiB result written there is unreachable by the App that must serve it — a 404 after the
whole run's spend was paid. Object storage is the shared ground the two pods actually have.

WHY self-hosted (spec D2): the deployment bundles its own Garage instance, so this needs no
cloud account, no managed-service credentials, and no cloud coupling — while speaking a wire
protocol that a managed S3 could later answer unchanged.

INVARIANT: the object key IS the sha256 of the content, exactly as the filename was on the
filesystem. So the id remains its own integrity check, and a well-formed id cannot address
anything outside this bucket.

AIDEV-NOTE: reclamation is NOT done here. `sweep` is a deliberate no-op — object expiry is a
bucket lifecycle rule, because listing objects would need query-string signing and push the
signer past the bound spec D5 sets on it. A bucket with no lifecycle rule never expires
artifacts.

AIDEV-NOTE: objects are addressed PATH-STYLE (`{endpoint}/{bucket}/{key}`). Garage, MinIO,
SeaweedFS, Ceph RGW and Cloudflare R2 all accept that. AWS S3 proper has deprecated path-style in
favour of virtual-hosted-style (`bucket.s3.region.amazonaws.com`), so this adapter may not reach
real AWS S3 — and the failure looks like a signing or credential problem rather than an addressing
one. Supporting it means choosing the style per endpoint, not patching `_url_path`.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from datetime import UTC, datetime

import httpx

from screamingface_engine.artifacts.ports import ArtifactContent, RemoteStream
from screamingface_engine.artifacts.sigv4 import (
    EMPTY_PAYLOAD_SHA256,
    Credentials,
    authorization_header,
)
from url4.streaming.protocol.signals import ResultArtifact

_ARTIFACT_ID = re.compile(r"^[0-9a-f]{64}$")
_STREAM_CHUNK_BYTES = 64 * 1024
_DEFAULT_TIMEOUT_S = 30.0


class S3StorageError(RuntimeError):
    """The object store could not serve a request.

    INVARIANT: distinct from "the artifact is absent", which is `None`. Collapsing the two
    would present a misconfiguration (bad credentials, unreachable endpoint) as an expired
    parcel — the misdiagnosis that sent the OME-929 investigation down a dead end.
    """


@dataclass(frozen=True)
class S3Config:
    """Where the bucket is and how to authenticate to it.

    A plain value object rather than a read of `Settings`: `artifacts` is a shared leaf of the
    layering gate, and `config` belongs to the control plane. Each half builds this from its
    own configuration source — the App from `Settings`, the Runner from `job_env`.
    """

    endpoint_url: str
    bucket: str
    credentials: Credentials
    timeout_s: float = _DEFAULT_TIMEOUT_S


class S3ArtifactStore:
    """Flat bucket of objects keyed by the lowercase sha256 hex of their content."""

    def __init__(
        self,
        config: S3Config,
        *,
        client_factory: Callable[[], httpx.Client] | None = None,
        async_client_factory: Callable[[], httpx.AsyncClient] | None = None,
    ) -> None:
        # WHY factories rather than clients: the write side runs inside `asyncio.to_thread`
        # (see `ports.ArtifactWriter`) and the read side streams on the event loop, so the two
        # cannot share one client. Injectable so tests can assert on the request actually
        # sent — the same seam `runner.connector.build_aigateway_world` uses.
        self._config = config
        self._client_factory = client_factory or self._default_client
        self._async_client_factory = async_client_factory or self._default_async_client

    # --- construction seams --------------------------------------------------------------

    def _default_client(self) -> httpx.Client:
        return httpx.Client(timeout=self._config.timeout_s)

    def _default_async_client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(timeout=self._config.timeout_s)

    # --- ArtifactWriter -----------------------------------------------------------------

    def write_text(self, body: str) -> ResultArtifact:
        """Persist `body` and return its claim ticket. See `write_bytes`."""
        return self.write_bytes(body.encode("utf-8"))

    def write_bytes(self, encoded: bytes) -> ResultArtifact:
        """Persist already-encoded content and return its claim ticket. Idempotent.

        Idempotent for free: the key is the content hash, so re-uploading identical bytes
        overwrites an identical object.

        INVARIANT: a ticket is only returned once the object store has ACKNOWLEDGED the
        write. A ticket for a failed upload would turn a loud error here into a silent 404
        at redemption — the exact failure shape OME-929 exists to remove.
        """
        digest = hashlib.sha256(encoded).hexdigest()
        self._request("PUT", digest, payload_sha256=digest, content=encoded)
        return ResultArtifact(id=digest, size_bytes=len(encoded), sha256=digest)

    # --- ArtifactReader -----------------------------------------------------------------

    def content(self, artifact_id: str) -> ArtifactContent | None:
        """The stored content for `artifact_id`, or None when absent or malformed.

        HEADs first to learn existence and length, then hands back a stream that fetches the
        body when the route iterates it. The HEAD is what lets the route answer 404 without
        having opened a multi-megabyte body it may not need.
        """
        if _ARTIFACT_ID.fullmatch(artifact_id) is None:
            # INVARIANT: validated before signing, so a traversal attempt never becomes a
            # request at all — the same guard the filesystem adapter applies to paths.
            return None
        head = self._request("HEAD", artifact_id, allow_missing=True)
        if head is None:
            return None
        return RemoteStream(
            stream=self._stream(artifact_id),
            size_bytes=int(head.headers.get("content-length", 0)),
        )

    def delete(self, artifact_id: str) -> None:
        """Remove an object. Absence is not an error — deletes race lifecycle expiry."""
        if _ARTIFACT_ID.fullmatch(artifact_id) is None:
            return
        self._request("DELETE", artifact_id, allow_missing=True)

    def sweep(self, ttl_seconds: float, *, now: float | None = None) -> int:
        """Always 0 — expiry is the bucket's lifecycle rule, not ours.

        WHY not a real sweep: listing objects means signing a query string, which pushes the
        signer past the PUT/GET-of-one-object bound spec D5 places on it. The store expires
        objects on its own schedule instead.

        AIDEV-NOTE: load-bearing, not a stub. A bucket configured with no lifecycle rule
        never expires artifacts, and nothing here will notice.
        """
        return 0

    # --- one signed request --------------------------------------------------------------

    def _url_path(self, key: str) -> str:
        return f"/{self._config.bucket}/{key}"

    def _signed_headers(self, method: str, key: str, *, payload_sha256: str) -> dict[str, str]:
        host = httpx.URL(self._config.endpoint_url).netloc.decode("ascii")
        now = datetime.now(UTC)
        headers = {
            "Host": host,
            "X-Amz-Content-Sha256": payload_sha256,
            "X-Amz-Date": now.strftime("%Y%m%dT%H%M%SZ"),
        }
        # INVARIANT: the Authorization is computed from THIS dict, and the same dict is what
        # gets sent — so the SignedHeaders list and the wire headers cannot drift apart.
        headers["Authorization"] = authorization_header(
            credentials=self._config.credentials,
            method=method,
            path=self._url_path(key),
            query="",
            headers=headers,
            payload_sha256=payload_sha256,
            now=now,
        )
        return headers

    def _request(
        self,
        method: str,
        key: str,
        *,
        payload_sha256: str = EMPTY_PAYLOAD_SHA256,
        content: bytes | None = None,
        allow_missing: bool = False,
    ) -> httpx.Response | None:
        """One signed round trip. `None` only when `allow_missing` and the object is absent."""
        headers = self._signed_headers(method, key, payload_sha256=payload_sha256)
        url = f"{self._config.endpoint_url.rstrip('/')}{self._url_path(key)}"
        try:
            with self._client_factory() as client:
                response = client.request(method, url, headers=headers, content=content)
        except httpx.HTTPError as exc:
            # WHY wrapped: callers handle `S3StorageError`; a bare httpx error crossing this
            # boundary would surface as an unhandled exception mid-run.
            raise S3StorageError(f"{method} {key} could not reach object storage: {exc}") from exc
        if allow_missing and response.status_code == 404:
            return None
        if response.status_code >= 400:
            # AIDEV-NOTE: the body is the store's own error XML, not ours; it names the real
            # cause (SignatureDoesNotMatch, NoSuchBucket, AccessDenied) and is what turns an
            # opaque 403 into an actionable one. It carries no credential material.
            raise S3StorageError(
                f"object storage refused {method} {key} with {response.status_code}: "
                f"{response.text[:200]}"
            )
        return response

    async def _stream(self, key: str) -> AsyncIterator[bytes]:
        """Stream one object's body.

        Opens its own client per fetch: redemptions are rare (once per over-cap run) and a
        per-fetch client needs no shutdown wiring in the app lifespan, which a shared one
        would. Signed at iteration time so the request is never older than its signature.
        """
        headers = self._signed_headers("GET", key, payload_sha256=EMPTY_PAYLOAD_SHA256)
        url = f"{self._config.endpoint_url.rstrip('/')}{self._url_path(key)}"
        try:
            async with self._async_client_factory() as client:
                async with client.stream("GET", url, headers=headers) as response:
                    if response.status_code >= 400:
                        await response.aread()
                        raise S3StorageError(
                            f"object storage refused GET {key} with {response.status_code}"
                        )
                    async for chunk in response.aiter_bytes(_STREAM_CHUNK_BYTES):
                        yield chunk
        except httpx.HTTPError as exc:
            raise S3StorageError(f"GET {key} could not reach object storage: {exc}") from exc


__all__ = ["S3ArtifactStore", "S3Config", "S3StorageError"]
