"""Fetch one parked picture or file from the engine's result store, by its sha256 (OME-1271)."""

from __future__ import annotations

import hashlib
from collections.abc import Callable

import httpx

from screamingface.case_result import _SHA256_RE
from screamingface.errors import EngineUnavailableError, MediaUnavailableError
from screamingface.media import CaseMedia

_CHUNK_BYTES = 65536


def fetch_media_bytes(http: httpx.Client, media: CaseMedia, mint: Callable[[], str]) -> bytes:
    """The bytes ``media`` names, fetched from ``GET /artifacts/{sha256}`` and checked.

    Stage 1 — refuse a sha256 that is not 64 hex digits before any request, so a malformed
        placeholder can never steer the fetch to another path.
    Stage 2 — mint a capability token and stream the item, refusing more bytes than the
        placeholder's size as they arrive.
    Stage 3 — check the size and sha256 of what arrived against the placeholder.

    e.g. ``CaseMedia(sha256="9f86…", size=307200)`` → the 307,200 bytes whose sha256 is ``9f86…``.

    Raises:
        MediaUnavailableError: ``media_reference_invalid``, ``media_not_kept`` (404 or 410: the
            store's expiry removed it), ``media_integrity_mismatch``, or ``media_fetch_failed``.
        EngineUnavailableError: the engine could not be reached.
    """

    # Stage 1 — a well-formed ticket.
    if _SHA256_RE.fullmatch(media.sha256) is None:
        raise MediaUnavailableError(
            f"{media} has no valid sha256 to fetch it by",
            code="media_reference_invalid",
            permanent=True,
        )
    # Stage 2 — fetch, never past the placeholder's size.
    chunks: list[bytes] = []
    received: int = 0
    try:
        with http.stream(
            "GET",
            f"/artifacts/{media.sha256}",
            headers={"URL4-Capability": mint(), "Accept-Encoding": "identity"},
        ) as response:
            if response.status_code in (404, 410):
                raise MediaUnavailableError(
                    f"The engine no longer holds {media}; a local engine drops parked pictures "
                    "and files after a while (48 hours by default). Run the Case again to see it.",
                    code="media_not_kept",
                    permanent=True,
                )
            if not response.is_success:
                raise MediaUnavailableError(
                    f"The engine answered HTTP {response.status_code} for {media}",
                    code="media_fetch_failed",
                    status=response.status_code,
                )
            for chunk in response.iter_bytes(chunk_size=_CHUNK_BYTES):
                received += len(chunk)
                if received > media.size:
                    _mismatch(media, received)
                chunks.append(chunk)
    except httpx.HTTPError as exc:
        raise EngineUnavailableError(
            f"Could not reach the SF Engine to fetch {media}", engine_url=str(http.base_url)
        ) from exc
    # Stage 3 — the bytes the placeholder names, or nothing.
    data: bytes = b"".join(chunks)
    if len(data) != media.size or hashlib.sha256(data).hexdigest() != media.sha256:
        _mismatch(media, len(data))
    return data


def _mismatch(media: CaseMedia, received: int) -> None:
    """Refuse bytes that are not the ones the placeholder names."""

    raise MediaUnavailableError(
        f"The engine sent {received} bytes that are not {media}",
        code="media_integrity_mismatch",
        permanent=True,
    )


__all__ = ["fetch_media_bytes"]
