"""The Case file upload route: `PUT /v1/blobs/sha256/{digest}` (OME-1970, PR 4).

FEATURE: Case files by blob reference (OME-1970). A **Case** is one Benchmark question; its
pictures and PDFs used to ride every model call inline as base64, so a 5-member Fusion sent an
18.35 MB PDF six times. Now the Engine uploads each file here ONCE per run, and each model call
carries a **blob reference**, `blob:sha256/<64 hex>`, which the chat route (PR 5) looks up in
`MediaStore` inside the call's upstream slot.

WHY an upload and not a fetch: the Engine already calls the gateway on port 9105, and the network
rules allow no connection the other way, so the gateway never fetches a file from anyone.
WHY this path: `/v1/` like every caller-facing gateway route, `blobs` because the stored thing is
url4's blob, and `sha256/{digest}` spells the path the way the reference spells the file
(`blob:sha256/<hex>`) and the Engine App spells its own blob upload (`PUT /blob/sha256/{digest}`),
so a reader maps one to the other with no lookup table.

INVARIANT (decision 3): a file is stored under the caller AND the run's token. A SHA-256 alone
never reaches it; see `core/media_store.py` for why.
INVARIANT (decision 4): this route is exempt from the app-wide 12 MiB body cap and enforces its
own 15,000,000-byte cap while streaming; `main.py` lists `BLOB_ROUTE_PREFIX` as the exemption.
INVARIANT: no log line and no refusal carries the token, its hash or the file's bytes.
"""

from __future__ import annotations

import asyncio
import base64
import logging
import re
from typing import Any

from fastapi import APIRouter, HTTPException, Request

from ..core.auth.middleware import CurrentAccount
from ..core.blob_upload import (
    MAX_BLOB_UPLOAD_BYTES,
    BlobDigestMismatch,
    BlobTooLarge,
    BlobUnsupportedMediaType,
    ReceivedFile,
    receive_upload,
)
from ..core.media_store import BlobScope, MediaStore, StoredMedia

logger = logging.getLogger(__name__)

router = APIRouter()

# The header carrying the random per-run token, named like the gateway's other request headers
# (`X-AIGW-Frozen-Copy`, `X-AIGW-Cache`). The Engine sends the same value on the upload and on
# every model call of the run (PR 7).
RUN_TOKEN_HEADER = "X-AIGW-Run-Token"
# The path prefix the body cap leaves to this route (`main.py`).
BLOB_ROUTE_PREFIX = "/v1/blobs/"

# WHY lowercase only: the reference spells the digest in lowercase hex, so one file has one name;
# accepting uppercase too would store the same file under two keys.
_DIGEST = re.compile(r"[0-9a-f]{64}")
# WHY 32 to 256 URL-safe characters: the Engine mints `secrets.token_urlsafe(32)`, 43 characters,
# 256 bits; 32 is the least that still carries 192 bits, so a short guessable token is refused,
# and 256 bounds what a header can make the gateway hash.
_RUN_TOKEN = re.compile(r"[A-Za-z0-9_-]{32,256}")


def _declared_length(request: Request) -> int | None:
    """The body length the caller declared, or ``None`` when absent or unreadable."""
    raw: str | None = request.headers.get("content-length")
    if raw is None:
        return None
    try:
        return int(raw)
    except ValueError:
        # WHY ignore, not refuse: the counted bytes are the authority either way.
        return None


def _too_large() -> HTTPException:
    """The 413 for a file over the per-file cap, closing the connection behind it.

    WHY `Connection: close`: the refusal can come before the body is complete; on keep-alive the
    server would otherwise keep reading the caller's remainder (the same rule as the body cap's).
    """
    return HTTPException(
        status_code=413,
        detail={
            "code": "blob_too_large",
            "limit_bytes": MAX_BLOB_UPLOAD_BYTES,
            "message": f"A file carries at most {MAX_BLOB_UPLOAD_BYTES:,} bytes.",
        },
        headers={"Connection": "close"},
    )


@router.put("/v1/blobs/sha256/{digest}", status_code=201)
async def upload_blob(digest: str, request: Request, current: CurrentAccount) -> dict[str, Any]:
    """Store one Case file under this caller, this run's token and its SHA-256.

    In one line: check the name and the token, read the body under the cap while hashing and
    type-checking it, encode it as base64 once, and keep that text in memory for this run.

    Stages, in execution order (the caller is already authenticated by `CurrentAccount`, so an
    unknown caller is refused before a byte of the body is read):

    1. Name: ``digest`` must be 64 lowercase hex characters, else 400 ``invalid_request``.
    2. Token: the ``X-AIGW-Run-Token`` header must be 32-256 URL-safe characters, else 400
       ``invalid_request``. The refusal never repeats what was sent.
    3. Declared size: a ``Content-Length`` over 15,000,000 is refused with 413 ``blob_too_large``
       before the body is read.
    4. Read: ``receive_upload`` streams the body. Over the cap mid-stream → 413
       ``blob_too_large``; leading bytes none of png/jpeg/gif/webp/pdf → 415
       ``blob_unsupported_media_type``; bytes that do not hash to ``digest`` → 422
       ``blob_digest_mismatch``. Nothing is stored on any refusal.
    5. Encode: the bytes become base64 text once, in a worker thread (a 15 MB file takes tens
       of milliseconds, which the event loop should not wait for).
    6. Store: ``MediaStore.put`` under (caller, SHA-256 of the token, digest), dropping the least
       recently used files if the budget needs room. Uploading a file the run already stored is
       accepted and replaces it — the Engine re-uploads after the gateway dropped one (PR 8).

    Example: a 13,760,000-byte PDF with SHA-256 ``ab12…`` and token ``Zq…`` (43 characters) →
    201 ``{"ref": "blob:sha256/ab12…", "media_type": "application/pdf", "size_bytes": 13760000}``
    and 18,346,668 bytes of base64 held under that run's scope.

    Args:
        digest: the SHA-256 the Engine labelled the file with (from the path).
        request: the upload; its body is the file's raw bytes, any content type.
        current: the authenticated caller; its account id is the first part of the scope.

    Returns:
        The file's reference, its type as its leading bytes name it, and its size in bytes —
        what the Engine puts in a reference part (`x_media_type`, `x_size`).
    """
    # Stage 1 — the name.
    if not _DIGEST.fullmatch(digest):
        raise HTTPException(
            status_code=400,
            detail={
                "code": "invalid_request",
                "message": "the path names a file by 64 lowercase hex characters of its SHA-256",
            },
        )
    # Stage 2 — the run token. INVARIANT: the message names the rule, never the value sent.
    token: str | None = request.headers.get(RUN_TOKEN_HEADER)
    if token is None or not _RUN_TOKEN.fullmatch(token):
        raise HTTPException(
            status_code=400,
            detail={
                "code": "invalid_request",
                "message": (
                    f"an upload carries its run's token in {RUN_TOKEN_HEADER}: "
                    "32 to 256 characters of A-Z, a-z, 0-9, '-' or '_'"
                ),
            },
        )
    scope: BlobScope | None = BlobScope.of(current.id, token)
    if scope is None:  # pragma: no cover - the pattern above admits no empty token
        raise AssertionError("a token that matched the pattern named no scope")
    # Stage 3 — the declared size, refused before reading.
    declared: int | None = _declared_length(request)
    if declared is not None and declared > MAX_BLOB_UPLOAD_BYTES:
        logger.info("blob upload refused: blob_too_large (declared %d bytes)", declared)
        raise _too_large()
    # Stage 4 — read under the cap, hashing and type-checking as it arrives.
    try:
        received: ReceivedFile = await receive_upload(request.stream(), digest=digest)
    except BlobTooLarge:
        logger.info("blob upload refused: blob_too_large (while reading)")
        raise _too_large() from None
    except BlobUnsupportedMediaType:
        logger.info("blob upload refused: blob_unsupported_media_type")
        raise HTTPException(
            status_code=415,
            detail={
                "code": "blob_unsupported_media_type",
                "message": "a file must be a png, jpeg, gif, webp or pdf, by its leading bytes",
            },
        ) from None
    except BlobDigestMismatch:
        logger.info("blob upload refused: blob_digest_mismatch (sha256 %s…)", digest[:12])
        raise HTTPException(
            status_code=422,
            detail={
                "code": "blob_digest_mismatch",
                "message": "the uploaded bytes do not hash to the SHA-256 in the path",
            },
        ) from None
    # Stage 5 — encode once, off the event loop.
    encoded: bytes = await asyncio.to_thread(base64.b64encode, received.data)
    media = StoredMedia(
        media_type=received.media_type,
        size_bytes=len(received.data),
        base64_text=encoded.decode("ascii"),
    )
    # Stage 6 — keep it for this run.
    store: MediaStore = request.app.state.media_store
    store.put(scope, digest, media)
    logger.info(
        "blob stored: sha256 %s… %s, %d bytes (store holds %d of %d base64 bytes)",
        digest[:12],
        media.media_type,
        media.size_bytes,
        store.held_bytes,
        store.max_bytes,
    )
    return {
        "ref": f"blob:sha256/{digest}",
        "media_type": media.media_type,
        "size_bytes": media.size_bytes,
    }


__all__ = ["BLOB_ROUTE_PREFIX", "RUN_TOKEN_HEADER", "router", "upload_blob"]
