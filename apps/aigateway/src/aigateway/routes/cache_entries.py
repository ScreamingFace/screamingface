"""``GET /v1/cache/entries``: the community cache for a local engine, one page at a time.

FEATURE: community cache, available to a local engine (epic OME-1311).
STORY: as a signed-in user of a local engine, I page through the hosted cache — optionally only
my models — and load each page into my local gateway, resuming where I stopped.
Spec: ``docs/spec/2026-10-15-community-cache.md``.

A page is NDJSON: a header line (``schema``, ``revisions``, and ``remaining`` when the caller sent
``count=true``), one line per row, and a trailer line carrying ``next`` — the cursor for the next
page, or null after the last. A page without its trailer was cut off; the client discards it.

INVARIANT: any authenticated account, never anonymous. ``CurrentAccount`` answers 401 for a
caller without an identity in every auth mode. Not admin-gated: reading the cache is what an
ordinary account does on every hosted call already.
INVARIANT: no hop holds a whole page. A page of the heaviest model is ~235 MB of rows, against
~240 MiB of headroom on a gateway pod; the body is written one ``BATCH_ROWS`` batch at a time.
"""

from __future__ import annotations

import json
import zlib
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import StringConstraints

from ..core.auth.middleware import CurrentAccount
from ..core.request_cache.community_pages import (
    MAX_PAGE_ROWS,
    PAGE_SCHEMA,
    InvalidCursor,
    PageCursor,
    count_rows,
    cursor_after,
    iter_page,
)
from ..core.request_cache.revisions import active_cache_revisions

router = APIRouter(prefix="/v1/cache", tags=["Cache"])

ModelName = Annotated[str, StringConstraints(min_length=1, max_length=255)]

# gzip framing (wbits 16 + 15), so the body is what `Content-Encoding: gzip` promises.
_GZIP_WBITS = 31


def _line(value: dict[str, Any]) -> bytes:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode() + b"\n"


def _wire(row: dict[str, Any]) -> dict[str, Any]:
    return {k: v.isoformat() if isinstance(v, datetime) else v for k, v in row.items()}


def _accepts_gzip(request: Request) -> bool:
    accepted = request.headers.get("accept-encoding", "")
    return any(part.split(";")[0].strip() == "gzip" for part in accepted.split(","))


async def _gzip(lines: AsyncIterator[bytes]) -> AsyncIterator[bytes]:
    compressor = zlib.compressobj(wbits=_GZIP_WBITS)
    async for line in lines:
        chunk = compressor.compress(line)
        if chunk:
            yield chunk
    yield compressor.flush()


@router.get("/entries", response_class=StreamingResponse)
async def community_cache_entries(
    request: Request,
    _current: CurrentAccount,
    after: Annotated[str | None, Query(max_length=256)] = None,
    limit: Annotated[int, Query(ge=1, le=MAX_PAGE_ROWS)] = MAX_PAGE_ROWS,
    count: bool = False,
    model: Annotated[list[ModelName], Query()] = [],  # noqa: B006 — FastAPI copies defaults
) -> StreamingResponse:
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
        last: list[dict[str, Any]] = []
        sent = 0
        async for batch in iter_page(after=cursor, limit=limit, models=models, now=now):
            yield b"".join(_line(_wire(row)) for row in batch)
            last, sent = batch[-1:], sent + len(batch)
        next_cursor = cursor_after(last, limit=1) if sent == limit else None
        yield _line({"next": next_cursor.encode() if next_cursor else None})

    headers = {"Cache-Control": "private, no-store", "Vary": "Accept-Encoding"}
    body = lines()
    if _accepts_gzip(request):
        headers["Content-Encoding"] = "gzip"
        body = _gzip(body)
    return StreamingResponse(body, media_type="application/x-ndjson", headers=headers)


__all__ = ["router"]
