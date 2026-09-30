"""`GET /v1/scores/{score_id}/results` (C10): the reported runs of one head.

FEATURE: OME-1307 (E14) — a head clusters every run of the same system (`POST /v1/scores`), and
this route lists them, newest first, with a cursor.

INVARIANT (OME-894): the privacy rules are `get_score`'s. A missing head and a private head that the
caller does not own answer with the SAME bytes and the private cache policy. A public answer is
re-checked against fresh visibility before it leaves (SC-D9).
"""

from __future__ import annotations

from typing import Annotated, Any, cast
from uuid import UUID

from fastapi import APIRouter, Query, Request, Response, status
from tortoise.exceptions import OperationalError

from scoreboard.core.paging import Cursor, InvalidCursor, decode_cursor, encode_cursor
from scoreboard.routes.dependencies import PRIVATE_CACHE_HEADERS, ReadIdentity, turned_private
from scoreboard.routes.errors import (
    UNPROCESSABLE,
    coded_http_error,
    score_not_found,
    store_unavailable,
)
from scoreboard.scores.cluster_rules import result_schema
from scoreboard.scores.cluster_store import ClusterStore
from scoreboard.scores.models import Benchmark, Score
from scoreboard.scores.schemas import (
    CodedErrorResponse,
    MessageErrorResponse,
    ReportedResultsPage,
)

router = APIRouter(prefix="/v1", tags=["scores"])

LIST_RESULTS_RESPONSES: dict[int | str, dict[str, Any]] = {
    status.HTTP_404_NOT_FOUND: {
        "model": MessageErrorResponse,
        "description": "Score not found, or private and not yours.",
    },
    UNPROCESSABLE: {
        "model": CodedErrorResponse,
        "description": "invalid_cursor. A limit outside 1..200 keeps the standard FastAPI shape.",
    },
    status.HTTP_503_SERVICE_UNAVAILABLE: {
        "model": MessageErrorResponse,
        "description": "Score store unavailable.",
    },
}


async def _readable_head(
    score_id: UUID, identity: str | None, response: Response
) -> tuple[Score, bool]:
    """The head and whether its board is private, or the 404 of a missing or unreadable one."""
    try:
        head = await Score.get_or_none(id=score_id)
        benchmark = (
            None
            if head is None
            else await Benchmark.get_or_none(id=cast(str, getattr(head, "benchmark_id")))
        )
    except OperationalError as exc:
        raise store_unavailable() from exc
    if head is None:
        raise score_not_found()
    # Fails closed: a head whose board cannot be established is treated as private.
    private = benchmark is None or benchmark.visibility == "private"
    if private:
        response.headers.update(PRIVATE_CACHE_HEADERS)
        if identity is None or head.submitted_by != identity:
            raise score_not_found()
    return head, private


def _after(cursor: str | None) -> Cursor | None:
    if cursor is None:
        return None
    try:
        return decode_cursor(cursor)
    except InvalidCursor as exc:
        raise coded_http_error(exc) from exc


@router.get(
    "/scores/{score_id}/results",
    response_model=ReportedResultsPage,
    responses=LIST_RESULTS_RESPONSES,
)
async def list_results(
    score_id: UUID,
    request: Request,
    response: Response,
    identity: ReadIdentity,
    cursor: Annotated[str | None, Query(description="Opaque cursor from `next_cursor`.")] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> ReportedResultsPage:
    """List the reported results of a head, newest first: `(submitted_at, id)` descending."""
    head, private = await _readable_head(score_id, identity, response)
    board_id = cast(str, getattr(head, "benchmark_id"))
    # INVARIANT: the cursor is read AFTER the privacy check, so a private head is never told apart
    # from a missing one by a 422.
    after = _after(cursor)
    store = cast(ClusterStore, request.app.state.cluster_store)
    try:
        rows = await store.results_page(score_id, after=after, limit=limit)
        states = await store.publication_states([row.id for row in rows[:limit]])
    except OperationalError as exc:
        raise store_unavailable() from exc
    page = rows[:limit]
    if not private and await turned_private(board_id):
        # The board went private while the page was read: answer as a private board does.
        response.headers.update(PRIVATE_CACHE_HEADERS)
        raise score_not_found()
    return ReportedResultsPage(
        results=[result_schema(row, states.get(str(row.id))) for row in page],
        next_cursor=_next_cursor(rows, limit),
    )


def _next_cursor(rows: list[Any], limit: int) -> str | None:
    if len(rows) <= limit:
        return None
    last = rows[limit - 1]
    return encode_cursor(Cursor(submitted_at=last.submitted_at, id=last.id))
