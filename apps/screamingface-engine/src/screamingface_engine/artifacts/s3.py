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
from collections.abc import AsyncIterator, Callable, Iterator
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
# WHY 512: enough for the store's error XML to name its cause (`<Code>SlowDown</Code>`), and a
# fixed cost however large a hostile store or proxy makes the body (#1603 review round 3).
_ERROR_PREFIX_BYTES = 512
_ERROR_DETAIL_CHARS = 200
_IDENTITY_ENCODINGS = frozenset({"", "identity"})


class S3ObjectTooLarge(Exception):
    """An object holds more bytes than the caller's cap: the store's CONTENT is wrong.

    INVARIANT: not an `S3StorageError` — a sick store is retryable (503), an object past its
    cap is permanent corruption, and the blob store renders the two differently.
    """


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
        # sent — the same seam `world.connector.build_aigateway_world` uses.
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

    # --- keyed objects (the run blob store, OME-1540) ------------------------------------

    def put_object(self, key: str, data: bytes) -> None:
        """Store `data` under an explicit `key`, acknowledged before returning.

        FEATURE: the run blob store (OME-1540) keys objects by tenant + run + digest, so it
        cannot use the content-hash-only key of `write_bytes`.

        AIDEV-NOTE: `key` is signed and sent unencoded (see `sigv4.canonical_request`), so the
        caller must pass only `[A-Za-z0-9._/-]` — `artifacts.blobs` builds every key it sends.
        """
        self._request("PUT", key, payload_sha256=hashlib.sha256(data).hexdigest(), content=data)

    def put_object_if_absent(self, key: str, data: bytes) -> bool:
        """Create `key` only if no object holds it yet; True when this call created it.

        FEATURE: #1603 review round 2 (owner decision 2026-11-04, item 5) — the blob store's
        first metadata write, so two racing first uploads cannot both report "created".

        WHY `If-None-Match: *`: the S3 conditional write (AWS S3 since 2024-08; MinIO and most
        S3-compatibles); a 412 means another writer got there first. The header is SIGNED (it is
        in the dict the signature is computed from), so it cannot be stripped in transit.

        AIDEV-NOTE: Garage v2.3.0 (the bundled store) IGNORES the condition — probed 2026-11-04:
        a second conditional PUT on an existing key returned 200 and overwrote it. On Garage
        the caller's prior existence check is the only guard, so two uploads racing inside the
        same few milliseconds can both see `True`. Harmless for the blob store (the data is
        content-addressed and verified on read; the sidecar is rewritten with the same shape),
        but it is NOT the exactly-once guarantee a conforming S3 gives.
        """
        digest = hashlib.sha256(data).hexdigest()
        response = self._request(
            "PUT",
            key,
            payload_sha256=digest,
            content=data,
            extra_headers={"If-None-Match": "*"},
            allow_precondition_failed=True,
        )
        return response is not None

    def get_object_at_most(self, key: str, max_bytes: int) -> bytes | None:
        """The object under `key`, read as a STREAM that stops past `max_bytes`; None when absent.

        FEATURE: #1603 review round 2 (owner decision 2026-11-04, item 2) — a corrupt or hostile
        object can never be materialised whole: at most `max_bytes + 1` bytes (plus one network
        chunk) are pulled before refusing.

        Raises:
            S3ObjectTooLarge: the object holds more than `max_bytes` bytes.
            S3StorageError: the store could not serve the request.
        """
        headers = self._signed_headers("GET", key, payload_sha256=EMPTY_PAYLOAD_SHA256)
        url = f"{self._config.endpoint_url.rstrip('/')}{self._url_path(key)}"
        try:
            with self._client_factory() as client, client.stream("GET", url, headers=headers) as r:
                if r.status_code == 404:
                    return None
                if r.status_code >= 400:
                    # INVARIANT: a bounded prefix, never `r.read()` — the cap holds on errors too.
                    raise S3StorageError(
                        f"object storage refused GET {key} with {r.status_code}: "
                        f"{_read_error_detail(r)}"
                    )
                _refuse_encoded(r, f"GET {key}")
                declared = r.headers.get("content-length", "")
                if declared.isdigit() and int(declared) > max_bytes:
                    raise S3ObjectTooLarge(f"{key} holds {declared} bytes; the cap is {max_bytes}")
                chunks: list[bytes] = []
                size = 0
                # INVARIANT (#1603 review round 4): RAW bytes. `iter_bytes` decodes any
                # Content-Encoding BEFORE chunking, so a tiny gzip body would inflate past the
                # cap before the first size check; `_refuse_encoded` makes raw == stored.
                for chunk in _raw_chunks(r, _STREAM_CHUNK_BYTES):
                    size += len(chunk)
                    if size > max_bytes:
                        raise S3ObjectTooLarge(f"{key} holds more than {max_bytes} bytes")
                    chunks.append(chunk)
                return b"".join(chunks)
        except httpx.HTTPError as exc:
            raise S3StorageError(f"GET {key} could not reach object storage: {exc}") from exc

    # --- one signed request --------------------------------------------------------------

    def _url_path(self, key: str) -> str:
        return f"/{self._config.bucket}/{key}"

    def _signed_headers(
        self,
        method: str,
        key: str,
        *,
        payload_sha256: str,
        extra_headers: dict[str, str] | None = None,
    ) -> dict[str, str]:
        host = httpx.URL(self._config.endpoint_url).netloc.decode("ascii")
        now = datetime.now(UTC)
        headers = {
            "Host": host,
            "X-Amz-Content-Sha256": payload_sha256,
            "X-Amz-Date": now.strftime("%Y%m%dT%H%M%SZ"),
            **(extra_headers or {}),
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
        extra_headers: dict[str, str] | None = None,
        allow_precondition_failed: bool = False,
    ) -> httpx.Response | None:
        """One signed round trip. `None` only when `allow_missing` and the object is absent, or
        when `allow_precondition_failed` and the store answered 412."""
        headers = self._signed_headers(
            method, key, payload_sha256=payload_sha256, extra_headers=extra_headers
        )
        url = f"{self._config.endpoint_url.rstrip('/')}{self._url_path(key)}"
        # INVARIANT (#1603 review round 3): STREAMED, so no response body is ever buffered whole.
        # Callers use only the status and headers; an error body costs at most the diagnostic
        # prefix, and a 404/412 body is never read at all. The headers survive the close.
        try:
            with (
                self._client_factory() as client,
                client.stream(method, url, headers=headers, content=content) as response,
            ):
                if allow_missing and response.status_code == 404:
                    return None
                if allow_precondition_failed and response.status_code == 412:
                    return None
                if response.status_code >= 400:
                    # AIDEV-NOTE: the body is the store's own error XML, not ours; it names the
                    # real cause (SignatureDoesNotMatch, NoSuchBucket, AccessDenied) and is what
                    # turns an opaque 403 into an actionable one. No credential material.
                    raise S3StorageError(
                        f"object storage refused {method} {key} with {response.status_code}: "
                        f"{_read_error_detail(response)}"
                    )
                return response
        except httpx.HTTPError as exc:
            # WHY wrapped: callers handle `S3StorageError`; a bare httpx error crossing this
            # boundary would surface as an unhandled exception mid-run.
            raise S3StorageError(f"{method} {key} could not reach object storage: {exc}") from exc

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
                        # INVARIANT: a bounded RAW prefix, never `aread()` or `aiter_bytes()`
                        # (#1603 review rounds 3 and 4); an encoded body is not read at all.
                        detail = _encoded_body_note(response)
                        if detail is None:
                            prefix = b""
                            async for prefix in _araw_chunks(response, _ERROR_PREFIX_BYTES):
                                break
                            detail = _error_detail(prefix)
                        await response.aclose()
                        raise S3StorageError(
                            f"object storage refused GET {key} with {response.status_code}: "
                            f"{detail}"
                        )
                    _refuse_encoded(response, f"GET {key}")
                    async for chunk in _araw_chunks(response, _STREAM_CHUNK_BYTES):
                        yield chunk
        except httpx.HTTPError as exc:
            raise S3StorageError(f"GET {key} could not reach object storage: {exc}") from exc


def _raw_chunks(response: httpx.Response, size: int) -> Iterator[bytes]:
    """The body's raw (undecoded) bytes in `size` chunks.

    WHY the `is_stream_consumed` branch: a response built in memory (`httpx.Response(content=)`,
    as a mock transport or a buffering transport returns) is already read, and `iter_raw` would
    raise `StreamConsumed`. Its bytes are already materialised, so slicing them costs nothing
    the response has not already spent. On the wire, `client.stream` never pre-reads.
    """
    if response.is_stream_consumed:
        body = response.content
        for at in range(0, len(body), size):
            yield body[at : at + size]
        return
    yield from response.iter_raw(size)


async def _araw_chunks(response: httpx.Response, size: int) -> AsyncIterator[bytes]:
    """The async twin of `_raw_chunks`."""
    if response.is_stream_consumed:
        for chunk in _raw_chunks(response, size):
            yield chunk
        return
    async for chunk in response.aiter_raw(size):
        yield chunk


def _content_encoding(response: httpx.Response) -> str | None:
    """The response's Content-Encoding when it is anything but identity, else None."""
    raw = response.headers.get("content-encoding", "")
    tokens = {token.strip().lower() for token in raw.split(",")}
    return None if tokens <= _IDENTITY_ENCODINGS else raw.strip()


def _encoded_body_note(response: httpx.Response) -> str | None:
    """A diagnostic standing in for an encoded error body that is deliberately left unread."""
    encoding = _content_encoding(response)
    return None if encoding is None else f"<{encoding}-encoded body not read>"


def _refuse_encoded(response: httpx.Response, what: str) -> None:
    """Refuse an object body the store (or a proxy) sent with a non-identity Content-Encoding.

    FEATURE: #1603 review round 4 — HTTPX would inflate it before any cap applies.

    WHY refuse rather than decode: an object store returns the stored bytes and this client
    never asks for compression, so an encoded body is a misbehaving store or proxy. Decoding it
    under a cap would mean a decompressor with its own output bound; refusing needs none.
    """
    encoding = _content_encoding(response)
    if encoding is not None:
        raise S3StorageError(
            f"object storage answered {what} with Content-Encoding {encoding!r}; "
            "object bytes must arrive unencoded"
        )


def _read_error_detail(response: httpx.Response) -> str:
    """The error text from at most `_ERROR_PREFIX_BYTES` of a STREAMED body, then close it.

    INVARIANT (#1603 review round 4): RAW bytes only, and an encoded body is not read at all —
    `iter_bytes` would inflate a compressed body before the prefix limit applied.
    """
    detail = _encoded_body_note(response)
    if detail is None:
        prefix = b""
        for prefix in _raw_chunks(response, _ERROR_PREFIX_BYTES):
            break
        detail = _error_detail(prefix)
    response.close()
    return detail


def _error_detail(prefix: bytes) -> str:
    """The store's error text from a bounded body prefix; bad UTF-8 never raises."""
    text = prefix[:_ERROR_PREFIX_BYTES].decode("utf-8", errors="replace")
    return text[:_ERROR_DETAIL_CHARS]


__all__ = ["S3ArtifactStore", "S3Config", "S3ObjectTooLarge", "S3StorageError"]
