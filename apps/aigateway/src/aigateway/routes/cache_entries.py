"""``GET /v1/cache/entries``: the community cache for a local engine, one page at a time.

FEATURE: community cache, available to a local engine (epic OME-1311).
STORY: as a signed-in user of a local engine, I page through the hosted cache — optionally only
my models — and load each page into my local gateway, resuming where I stopped.
Spec: ``docs/spec/2026-10-15-community-cache.md``.

A page is NDJSON: a header line (``schema``, ``revisions``, and ``remaining`` when the caller sent
``count=true``), one line per row, and a trailer line carrying ``next`` — the cursor for the next
page, or null when no eligible row follows this page's last. A page without its trailer was cut
off; the client discards it.

INVARIANT: any authenticated account, never anonymous. ``CurrentAccount`` answers 401 for a
caller without an identity in every mode that authenticates (``jwt``, ``cloudflare_headers``).
Not admin-gated: reading the cache is what an ordinary account does on every hosted call already.
INVARIANT (hosted BYOM, owner decision of 2026-10-27): no endpoint-grant filter. A configured
endpoint's eligible rows are listed to every authenticated account like any other row, with their
provider and model IDs, stored responses and cache metadata. Grants govern the working catalog and
new upstream calls; they do not make identifiers in published cache entries confidential.
AIDEV-NOTE: ``AIGW_AUTH_MODE=disabled`` is the exception: ``CurrentAccount`` returns the anonymous
account, so every caller may read. That mode is loopback-only (``AuthDisabledLocalOnlyMiddleware``),
the same footing the admin routes give it.
INVARIANT: no hop holds a whole page. A page of the heaviest model is ~235 MB of rows, against
~240 MiB of headroom on a gateway pod; the body is written one batch at a time, and a batch is
bounded by bytes as well as rows (``community_pages.BATCH_BYTES``).
"""

from __future__ import annotations

import json
import re
import zlib
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import StreamingResponse
from pydantic import StringConstraints

from ..core.auth.middleware import CurrentAccount
from ..core.request_cache.community_pages import (
    MAX_PAGE_ROWS,
    PAGE_SCHEMA,
    InvalidCursor,
    PageCursor,
    PageScan,
    count_rows,
    has_rows_after,
    iter_page,
)
from ..core.request_cache.revisions import active_cache_revisions

router = APIRouter(prefix="/v1/cache", tags=["Cache"])

ModelName = Annotated[str, StringConstraints(min_length=1, max_length=255)]

# gzip framing (wbits 16 + 15), so the body is what `Content-Encoding: gzip` promises.
_GZIP_WBITS = 31
# RFC 9110 §12.4.2 qvalue: "0" with up to three decimals, or "1" with up to three zeros.
_QVALUE = re.compile(r"0(\.[0-9]{0,3})?|1(\.0{0,3})?")


def _line(value: dict[str, Any]) -> bytes:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode() + b"\n"


def _wire(row: dict[str, Any]) -> dict[str, Any]:
    return {k: v.isoformat() if isinstance(v, datetime) else v for k, v in row.items()}


def _rows(batch: list[dict[str, Any]]) -> bytes:
    return b"".join(_line(_wire(row)) for row in batch)


def _coding(request: Request) -> str | None:
    """``gzip`` or ``identity``, whichever the caller accepts (gzip first), or None for neither.

    RFC 9110 §12.5.3: codings are case-insensitive, `q=0` refuses one, and `*` stands for every
    coding not listed by name. A malformed weight refuses. Identity is acceptable unless refused
    by name or by `*;q=0`; gzip only when asked for, by name or by `*`.
    """
    weights: dict[str, float] = {}
    for part in request.headers.get("accept-encoding", "").split(","):
        coding, *params = (piece.strip() for piece in part.split(";"))
        if coding:
            weights[coding.lower()] = _weight(params)
    if weights.get("gzip", weights.get("*", 0.0)) > 0:
        return "gzip"
    if weights.get("identity", weights.get("*", 1.0)) > 0:
        return "identity"
    return None


def _weight(params: list[str]) -> float:
    for param in params:
        name, _, value = param.partition("=")
        if name.strip().lower() == "q":
            value = value.strip()
            return float(value) if _QVALUE.fullmatch(value) else 0.0
    return 1.0


async def _gzip(lines: AsyncIterator[bytes]) -> AsyncIterator[bytes]:
    # INVARIANT: compression runs in a worker thread, never on the event loop (see
    # ``_rows``). One compressor is used by one request at a time, so moving it between
    # threads is safe.
    compressor = zlib.compressobj(wbits=_GZIP_WBITS)
    async for line in lines:
        chunk = await run_in_threadpool(compressor.compress, line)
        if chunk:
            yield chunk
    yield await run_in_threadpool(compressor.flush)


@router.get("/entries", response_class=StreamingResponse)
async def community_cache_entries(
    request: Request,
    _current: CurrentAccount,
    after: Annotated[str | None, Query(max_length=256)] = None,
    limit: Annotated[int, Query(ge=1, le=MAX_PAGE_ROWS)] = MAX_PAGE_ROWS,
    count: bool = False,
    model: Annotated[list[ModelName], Query()] = [],  # noqa: B006 — FastAPI copies defaults
) -> StreamingResponse:
    coding = _coding(request)
    if coding is None:
        raise HTTPException(
            status_code=406,
            detail="no acceptable content coding: accept gzip or identity",
            headers={"Cache-Control": "private, no-store", "Vary": "Accept-Encoding"},
        )
    try:
        cursor = PageCursor.decode(after) if after is not None else None
    except InvalidCursor as exc:
        raise HTTPException(status_code=422, detail=f"after: {exc}") from exc
    models = tuple(model)
    now = datetime.now(UTC)

    header: dict[str, Any] = {"schema": PAGE_SCHEMA, "revisions": active_cache_revisions()}
    if count:
        # WHY on request only: a count scans every remaining row; a client asks once per
        # session (fresh or resumed), not on each of ~120 pages.
        header["remaining"] = await count_rows(after=cursor, models=models, now=now)

    async def lines() -> AsyncIterator[bytes]:
        yield _line(header)
        scan = PageScan()
        async for batch in iter_page(after=cursor, limit=limit, models=models, now=now, scan=scan):
            # WHY a worker thread: a batch is up to ``BATCH_BYTES`` of rows, and encoding it
            # (then gzip, ~57 ms per 1,000 rows) on the loop would stall every other request on
            # the pod, cache hits included.
            yield await run_in_threadpool(_rows, batch)
        # WHY the scan, not the last row sent: a row rewritten or deleted mid-page was scanned but
        # not sent, and the next page must still start after it.
        # WHY look ahead rather than compare the row count with ``limit``: a page of exactly
        # ``limit`` rows that ends the cache must say so, or the client asks for an empty page.
        last = scan.cursor
        more = last is not None and await has_rows_after(after=last, models=models, now=now)
        yield _line({"next": last.encode() if more and last is not None else None})

    headers = {"Cache-Control": "private, no-store", "Vary": "Accept-Encoding"}
    body = lines()
    if coding == "gzip":
        headers["Content-Encoding"] = "gzip"
        body = _gzip(body)
    return StreamingResponse(body, media_type="application/x-ndjson", headers=headers)


__all__ = ["router"]
