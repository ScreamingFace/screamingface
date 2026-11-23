"""`PUT|GET /blob/sha256/<hex>` — upload to and fetch from the run blob store (OME-1540).

FEATURE: image and PDF inputs (epic OME-1529; spec OME-1535 F1, F3, §4).
STORY: as a url4 client I mint a capability token, upload a picture with it, get back
`blob:sha256/<hex>`, and start `GET /?q=` with the same token naming that ref.

INVARIANT (owner decision 2026-10-28, Q1a/Q2a): both routes need `URL4-Capability`. The scope is
the token's topic (the run) plus the caller's verified `X-User-Email` (or `anonymous`) — never
anything the ref or the body says. A digest outside that scope is 404 `source_not_found`, the
same answer, byte for byte, as a digest nobody uploaded.
INVARIANT (Q3a): the client states the digest; bytes that do not hash to it are 422
`x.blob_digest_mismatch` and nothing is stored. A repeat upload is 200 with the same ref.

AIDEV-NOTE: the body is read with a running cap, so an oversize upload is refused once it passes
the limit rather than after it has been buffered whole.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Annotated, Any

from fastapi import APIRouter, Path, Request, Response
from fastapi.responses import JSONResponse

from screamingface_engine import job_env
from screamingface_engine.artifacts.blobs import (
    SOURCE_NOT_FOUND,
    BlobContentMismatch,
    BlobDigestMismatch,
    BlobError,
    BlobScope,
    BlobStore,
    BlobTooLarge,
    BlobUnsupportedMediaType,
    StoredBlob,
)
from screamingface_engine.artifacts.s3 import S3StorageError
from screamingface_engine.auth.dependencies import VerifiedClaims
from screamingface_engine.auth.problem import ProblemException
from screamingface_engine.rest.capped_body import BodyTooLarge, capped_body

_logger = logging.getLogger(__name__)

router = APIRouter()

_EMAIL_HEADER = "X-User-Email"
_DIGEST = Path(description="Lowercase hex sha256 of the blob's bytes.")
# Ingest refusals and their statuses (spec §4; owner decision 2026-10-28, Q3a/Q4a).
_INGEST_STATUS: dict[type[BlobError], int] = {
    BlobDigestMismatch: 422,
    BlobTooLarge: 413,
    BlobUnsupportedMediaType: 415,
    BlobContentMismatch: 415,
}
# FEATURE: #1603 review (Khoa, 2026-11-02). WHY `private, no-store`: the scope rides a header
# (`URL4-Capability`), not the URL, so a shared cache keying on the URL alone could hand one
# run's file to another caller. Sent on every GET answer — a 404 says what a run does not hold.
_NO_STORE = {"Cache-Control": "private, no-store"}
# WHY 5 s, the run queue's broker-down value (`rest.routes.QUEUE_UNAVAILABLE_RETRY_AFTER_S`): an
# unreachable endpoint is a reconnect in flight, and a full disk is an operator action away —
# there is no estimate to derive a better number from, and 1 s spends retries inside the outage.
BLOB_STORAGE_RETRY_AFTER_S = 5
# The failures that mean "the store is sick", not "this blob is wrong": the S3 adapter's typed
# error, and any OS-level failure of the filesystem backend (ENOSPC, EACCES, EIO, ...).
_STORAGE_FAILURES = (S3StorageError, OSError)


def _scope(request: Request, claims: dict[str, object]) -> BlobScope:
    # INVARIANT: `X-User-Email` is the mesh-verified identity (Envoy strips and re-injects it,
    # see `job_env.IDENTITY_HEADER_ENV`); read through the same helper the run start uses.
    email = job_env.identity_from_headers(request.headers).get(_EMAIL_HEADER)
    return BlobScope.for_caller(email, str(claims["sub"]))


def _store(request: Request) -> BlobStore:
    """The App's blob store, or a 503 problem when none of its own is configured.

    FEATURE: #1603 review round 2 (owner decision 2026-11-04, item 1) — fail closed. With no
    `URL4_CLOUD_BLOB_STORE`, `create_app` leaves `blob_store` None (never the artifact store),
    and both routes refuse with the engine's unconfigured-dependency shape (cf. `rest.catalog`).
    WHY permanent and no Retry-After: only an operator's configuration change ends this state.
    """
    store: BlobStore | None = getattr(request.app.state, "blob_store", None)
    if store is None:
        raise ProblemException(
            status=503,
            title="Service Unavailable",
            detail=f"blob storage is not configured on this Engine ({job_env.BLOB_STORE})",
            headers=_NO_STORE,
            permanent=True,
        )
    return store


def _ticket(blob: StoredBlob) -> dict[str, Any]:
    return {
        "ref": blob.ref,
        "sha256": blob.sha256,
        "size_bytes": blob.size_bytes,
        "media_type": blob.media_type,
    }


def _problem(
    exc: BlobError, status: int, headers: dict[str, str] | None = None
) -> ProblemException:
    return ProblemException(
        status=status,
        title="Blob refused",
        detail=str(exc),
        headers=headers,
        code=exc.code,
        permanent=True,
    )


def _unavailable(exc: Exception, op: str) -> ProblemException:
    # INVARIANT: the client never sees the backend's message (it can name paths or endpoints),
    # and the log never carries the bytes, the email or the run id (a bearer secret).
    _logger.warning("blob storage unavailable during %s: %s", op, type(exc).__name__)
    return ProblemException(
        status=503,
        title="Service Unavailable",
        detail="blob storage is temporarily unavailable; retry",
        headers={"Retry-After": str(BLOB_STORAGE_RETRY_AFTER_S), **_NO_STORE},
        permanent=False,
    )


async def _capped_body(request: Request, max_bytes: int) -> bytes:
    try:
        return await capped_body(request, max_bytes)
    except BodyTooLarge:
        raise _problem(BlobTooLarge(f"blob exceeds the {max_bytes}-byte cap"), 413) from None


@router.put(
    "/blob/sha256/{digest}",
    tags=["Blobs"],
    summary="Upload a file to this run's blob store",
    description=(
        "Store the request body under its sha256 for the run named by the capability token. "
        "``Content-Type`` is the blob's media type (png, jpeg, gif, webp or pdf). Returns the "
        "ref to name in a url4 expression (``blob:sha256/<hex>`` or ``/blob/sha256/<hex>``): "
        "``201`` when stored, ``200`` when this run already held it. ``422`` "
        "``x.blob_digest_mismatch`` when the bytes do not hash to the path digest, ``413`` "
        "``x.blob_too_large``, ``415`` ``x.blob_unsupported_media_type`` (also when the bytes "
        "do not open with the declared type's signature), ``503`` with ``Retry-After`` when "
        "blob storage is unavailable, ``503`` without it when this Engine has no blob store "
        "configured."
    ),
    status_code=201,
)
async def put_blob(
    request: Request, claims: VerifiedClaims, digest: Annotated[str, _DIGEST]
) -> JSONResponse:
    scope = _scope(request, claims)
    store = _store(request)
    body = await _capped_body(request, request.app.state.settings.blob_max_bytes)
    media_type = request.headers.get("content-type", "")
    try:
        blob, created = await asyncio.to_thread(store.ingest, scope, digest, media_type, body)
    except BlobError as exc:
        # WHY the 500 default: the only other BlobError here is `BlobCorrupted` — the copy this
        # run already holds is corrupt (#1603 review round 2), a store fault, not a bad request.
        raise _problem(exc, _INGEST_STATUS.get(type(exc), 500)) from exc
    except _STORAGE_FAILURES as exc:
        raise _unavailable(exc, "upload") from exc
    return JSONResponse(_ticket(blob), status_code=201 if created else 200)


@router.get(
    "/blob/sha256/{digest}",
    tags=["Blobs"],
    summary="Fetch a file from this run's blob store",
    description=(
        "The verified bytes of a blob this run holds, with its media type. ``404`` "
        "``source_not_found`` for a digest this run does not hold — including one held by "
        "another run or tenant. ``500`` ``x.blob_digest_mismatch`` when the stored copy is "
        "corrupt: its bytes no longer match their digest, or its metadata or size break the "
        "store's contract. ``503`` with ``Retry-After`` when blob "
        "storage is unavailable, without it when none is configured. Every answer is "
        "``Cache-Control: private, no-store``."
    ),
    response_model=None,
    response_class=Response,
)
async def get_blob(
    request: Request, claims: VerifiedClaims, digest: Annotated[str, _DIGEST]
) -> Response:
    scope = _scope(request, claims)
    store = _store(request)
    try:
        found = await asyncio.to_thread(store.read, scope, digest)
    except BlobError as exc:
        raise _problem(exc, 500, _NO_STORE) from exc
    except _STORAGE_FAILURES as exc:
        raise _unavailable(exc, "fetch") from exc
    if found is None:
        raise ProblemException(
            status=404,
            title="Unknown blob",
            detail="this run holds no blob under that digest",
            headers=_NO_STORE,
            code=SOURCE_NOT_FOUND,
            permanent=True,
        )
    blob, body = found
    return Response(
        content=body,
        media_type=blob.media_type,
        # WHY nosniff: these are user-supplied bytes served back from the engine's origin; a
        # browser must render them as their declared type, never sniff them into HTML.
        headers={"X-Content-Type-Options": "nosniff", **_NO_STORE},
    )


__all__ = ["router"]
