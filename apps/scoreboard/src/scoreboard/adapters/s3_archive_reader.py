"""`S3ArchiveReader`: the `VersionArchiveReader` of the cache-version bucket (C8b).

Mirrors `apps/aigateway/src/aigateway/core/object_store.py` by copy, not import: path-style
addressing, the same signed headers, a per-request client and sanitized errors. The difference is
the verb: this store only GETs.

FEATURE: OME-1307 (E14). INVARIANT (PB-D8): read-only. The scoreboard credentials can read
`cache-versions/` and nothing else, and no method here writes.

INVARIANT: the secret key never reaches a log line, an exception message or `last_error`. Error
messages carry the status code only.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

import httpx

from scoreboard.adapters.sigv4 import EMPTY_PAYLOAD_SHA256, Credentials, authorization_header
from scoreboard.core.publish.ports import (
    ARCHIVE_DIR,
    ENTRIES_NAME,
    MANIFEST_NAME,
    ArchiveMissing,
    ArchivePair,
    PublisherError,
)

_READ_TIMEOUT_S = 60.0  # C8 "Scoreboard: read timeout 60 s"


@dataclass(frozen=True)
class S3ArchiveConfig:
    """Where the bucket is and how to authenticate to it.

    The endpoint must be ORIGIN-shaped: the signature covers `/<bucket>/<key>` only, so a base
    path, a query or userinfo would be sent but not signed, and every GET would fail with a 403
    that reads as bad keys. Refused here, at construction, with the setting to fix.
    """

    endpoint_url: str
    bucket: str
    credentials: Credentials
    timeout_s: float = _READ_TIMEOUT_S

    def __post_init__(self) -> None:
        url = httpx.URL(self.endpoint_url)
        if url.scheme not in ("http", "https") or not url.host:
            raise ValueError(
                "archive endpoint_url must be http(s)://host — set "
                "SCOREBOARD_ARCHIVE_S3_ENDPOINT_URL to the S3 origin"
            )
        if url.path not in ("", "/") or url.query or url.fragment or url.username or url.password:
            raise ValueError(
                "archive endpoint_url must be a bare origin (no path, query or userinfo): the "
                "signature covers /<bucket>/<key> only — set SCOREBOARD_ARCHIVE_S3_ENDPOINT_URL"
                " to the S3 origin"
            )


class S3ArchiveReader:
    def __init__(
        self,
        config: S3ArchiveConfig,
        *,
        client_factory: Callable[[], httpx.AsyncClient] | None = None,
    ) -> None:
        self._config = config
        self._client_factory = client_factory or (
            lambda: httpx.AsyncClient(timeout=config.timeout_s)
        )

    async def read(self, version_id: UUID) -> ArchivePair:
        prefix = f"{ARCHIVE_DIR}/{version_id}"
        return ArchivePair(
            entries=await self._get(f"{prefix}/{ENTRIES_NAME}"),
            manifest=await self._get(f"{prefix}/{MANIFEST_NAME}"),
        )

    async def _get(self, key: str) -> bytes:
        path = f"/{self._config.bucket}/{key}"
        url = f"{self._config.endpoint_url.rstrip('/')}{path}"
        try:
            async with self._client_factory() as client:
                response = await client.get(url, headers=self._signed_headers(path))
        except httpx.HTTPError as exc:
            # WHY the class name only: the text of a transport error can carry the URL.
            raise PublisherError(
                f"GET {key} could not reach object storage ({type(exc).__name__})",
                retryable=True,
            ) from exc
        if response.status_code == 404 or b"NoSuchKey" in response.content[:500]:
            raise ArchiveMissing(f"object storage has no {key}")
        if not 200 <= response.status_code < 300:
            # A redirect is not followed either: the signature is bound to this host and path.
            raise PublisherError(
                f"object storage refused GET {key} with {response.status_code}", retryable=True
            )
        return response.content

    def _signed_headers(self, path: str) -> dict[str, str]:
        host = httpx.URL(self._config.endpoint_url).netloc.decode("ascii")
        now = datetime.now(UTC)
        headers = {
            "Host": host,
            "X-Amz-Content-Sha256": EMPTY_PAYLOAD_SHA256,
            "X-Amz-Date": now.strftime("%Y%m%dT%H%M%SZ"),
        }
        # INVARIANT: the Authorization is computed from THIS dict, and the same dict is sent, so
        # the SignedHeaders list and the wire headers cannot drift apart.
        headers["Authorization"] = authorization_header(
            credentials=self._config.credentials,
            method="GET",
            path=path,
            query="",
            headers=headers,
            payload_sha256=EMPTY_PAYLOAD_SHA256,
            now=now,
        )
        return headers
