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
from typing import Annotated, Any

from fastapi import APIRouter, Path, Request, Response
from fastapi.responses import JSONResponse

from screamingface_engine import job_env
from screamingface_engine.artifacts.blobs import (
    SOURCE_NOT_FOUND,
    BlobDigestMismatch,
    BlobError,
    BlobScope,
    BlobStore,
    BlobTooLarge,
    BlobUnsupportedMediaType,
    StoredBlob,
)
from screamingface_engine.auth.dependencies import VerifiedClaims
from screamingface_engine.auth.problem import ProblemException

router = APIRouter()

_EMAIL_HEADER = "X-User-Email"
_DIGEST = Path(description="Lowercase hex sha256 of the blob's bytes.")
# Ingest refusals and their statuses (spec §4; owner decision 2026-10-28, Q3a/Q4a).
_INGEST_STATUS: dict[type[BlobError], int] = {
    BlobDigestMismatch: 422,
    BlobTooLarge: 413,
    BlobUnsupportedMediaType: 415,
}


def _scope(request: Request, claims: dict[str, object]) -> BlobScope:
    # INVARIANT: `X-User-Email` is the mesh-verified identity (Envoy strips and re-injects it,
    # see `job_env.IDENTITY_HEADER_ENV`); read through the same helper the run start uses.
    email = job_env.identity_from_headers(request.headers).get(_EMAIL_HEADER)
    return BlobScope.for_caller(email, str(claims["sub"]))


def _store(request: Request) -> BlobStore:
    # WHY direct attribute access: `create_app` always builds it; absence is a wiring bug.
    return request.app.state.blob_store


def _ticket(blob: StoredBlob) -> dict[str, Any]:
    return {
        "ref": blob.ref,
        "sha256": blob.sha256,
        "size_bytes": blob.size_bytes,
        "media_type": blob.media_type,
    }


def _problem(exc: BlobError, status: int) -> ProblemException:
    return ProblemException(
        status=status, title="Blob refused", detail=str(exc), code=exc.code, permanent=True
    )


async def _capped_body(request: Request, max_bytes: int) -> bytes:
    declared = request.headers.get("content-length")
    if declared is not None and declared.isdigit() and int(declared) > max_bytes:
        raise _problem(BlobTooLarge(f"blob exceeds the {max_bytes}-byte cap"), 413)
    chunks: list[bytes] = []
    size = 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > max_bytes:
            raise _problem(BlobTooLarge(f"blob exceeds the {max_bytes}-byte cap"), 413)
        chunks.append(chunk)
    return b"".join(chunks)


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
        "``x.blob_too_large``, ``415`` ``x.blob_unsupported_media_type``."
    ),
    status_code=201,
)
async def put_blob(
    request: Request, claims: VerifiedClaims, digest: Annotated[str, _DIGEST]
) -> JSONResponse:
    scope = _scope(request, claims)
    body = await _capped_body(request, request.app.state.settings.blob_max_bytes)
    media_type = request.headers.get("content-type", "")
    try:
        blob, created = await asyncio.to_thread(
            _store(request).ingest, scope, digest, media_type, body
        )
    except BlobError as exc:
        raise _problem(exc, _INGEST_STATUS[type(exc)]) from exc
    return JSONResponse(_ticket(blob), status_code=201 if created else 200)


@router.get(
    "/blob/sha256/{digest}",
    tags=["Blobs"],
    summary="Fetch a file from this run's blob store",
    description=(
        "The verified bytes of a blob this run holds, with its media type. ``404`` "
        "``source_not_found`` for a digest this run does not hold — including one held by "
        "another run or tenant. ``500`` ``x.blob_digest_mismatch`` when the stored bytes no "
        "longer match their digest (store corruption)."
    ),
    response_model=None,
    response_class=Response,
)
async def get_blob(
    request: Request, claims: VerifiedClaims, digest: Annotated[str, _DIGEST]
) -> Response:
    scope = _scope(request, claims)
    try:
        found = await asyncio.to_thread(_store(request).read, scope, digest)
    except BlobError as exc:
        raise _problem(exc, 500) from exc
    if found is None:
        raise ProblemException(
            status=404,
            title="Unknown blob",
            detail="this run holds no blob under that digest",
            code=SOURCE_NOT_FOUND,
            permanent=True,
        )
    blob, body = found
    return Response(
        content=body,
        media_type=blob.media_type,
        # WHY nosniff: these are user-supplied bytes served back from the engine's origin; a
        # browser must render them as their declared type, never sniff them into HTML.
        headers={"X-Content-Type-Options": "nosniff"},
    )


__all__ = ["router"]
