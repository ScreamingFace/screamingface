"""PUT-only S3-compatible object store for cache snapshots (OME-1021).

Mirrors the Engine's `artifacts/s3.py` shape (OME-929) by copy, not import: same path-style
addressing, same signed headers, same per-request client, same sanitized errors. The one
deliberate difference is the body: snapshots are tens of MiB, so the file is streamed with
an explicit `Content-Length` and a full-payload sha256 — plain transfer, no aws-chunked
encoding, so the signer stays inside the bound `sigv4` documents (chunked payload SIGNING
would be the signal to take a real client).

WHY PUT-only: retention is keep-all and expiry is a bucket lifecycle rule (locked decision
3) — there is no LIST, DELETE or GET in this store, so the SigV4 slice never grows past the
one operation that is cheap to sign correctly.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import httpx

from .sigv4 import Credentials, authorization_header

logger = logging.getLogger(__name__)

_STREAM_CHUNK_BYTES = 64 * 1024
_DEFAULT_TIMEOUT_S = 30.0


class S3StorageError(RuntimeError):
    """The object store could not serve a request; the message carries no credentials."""


@dataclass(frozen=True)
class S3ObjectStoreConfig:
    """Where the snapshot bucket is and how to authenticate to it."""

    endpoint_url: str
    bucket: str
    credentials: Credentials
    timeout_s: float = _DEFAULT_TIMEOUT_S


class _FileStream(httpx.AsyncByteStream):
    """Stream one file's bytes, reading off the event loop in bounded chunks."""

    def __init__(self, path: Path, chunk: int = _STREAM_CHUNK_BYTES) -> None:
        self._path = path
        self._chunk = chunk

    async def __aiter__(self) -> AsyncIterator[bytes]:
        with self._path.open("rb") as handle:
            while True:
                # File I/O is blocking; keep it off the loop the gateway serves on.
                chunk = await asyncio.to_thread(handle.read, self._chunk)
                if not chunk:
                    return
                yield chunk


class S3ObjectStore:
    """PUT a single object to one S3-compatible bucket, signed in full."""

    def __init__(
        self,
        config: S3ObjectStoreConfig,
        *,
        client_factory: Callable[[], httpx.AsyncClient] | None = None,
    ) -> None:
        self._config = config
        self._client_factory = client_factory or (
            lambda: httpx.AsyncClient(timeout=config.timeout_s)
        )

    async def put(self, key: str, path: Path, *, sha256_hex: str) -> None:
        """Upload `path` as object `key` under a full-payload signature.

        ``sha256_hex`` is the sha256 of the file's bytes — the exporter computed it while
        writing, so signing costs nothing extra. The PUT either completes or raises
        :class:`S3StorageError`; no partial object is ever reported as stored.
        """
        size = path.stat().st_size
        headers = self._signed_headers(key, sha256_hex=sha256_hex)
        headers["Content-Length"] = str(size)
        url = f"{self._config.endpoint_url.rstrip('/')}/{self._config.bucket}/{key}"
        body = _FileStream(path)
        try:
            async with self._client_factory() as client:
                response = await client.put(url, headers=headers, content=body)
        except httpx.HTTPError as exc:
            raise S3StorageError(f"PUT {key} could not reach object storage: {exc}") from exc
        if response.status_code >= 400:
            # The body is the store's own error XML, not ours; it names the real cause
            # (SignatureDoesNotMatch, NoSuchBucket, AccessDenied) and carries no credential
            # material — it is what turns an opaque 403 into an actionable one.
            raise S3StorageError(
                f"object storage refused PUT {key} with {response.status_code}: "
                f"{response.text[:200]}"
            )

    def _url_path(self, key: str) -> str:
        return f"/{self._config.bucket}/{key}"

    def _signed_headers(self, key: str, *, sha256_hex: str) -> dict[str, str]:
        host = httpx.URL(self._config.endpoint_url).netloc.decode("ascii")
        now = datetime.now(UTC)
        headers = {
            "Host": host,
            "X-Amz-Content-Sha256": sha256_hex,
            "X-Amz-Date": now.strftime("%Y%m%dT%H%M%SZ"),
        }
        # INVARIANT: the Authorization is computed from THIS dict, and the same dict is what
        # gets sent — so the SignedHeaders list and the wire headers cannot drift apart.
        headers["Authorization"] = authorization_header(
            credentials=self._config.credentials,
            method="PUT",
            path=self._url_path(key),
            query="",
            headers=headers,
            payload_sha256=sha256_hex,
            now=now,
        )
        return headers


__all__ = ["S3ObjectStore", "S3ObjectStoreConfig", "S3StorageError"]
