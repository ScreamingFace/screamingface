"""Admin route that sets `Benchmark.redistributable` (E14, OME-1307, D6).

FEATURE: OME-1307 (E14) D6, STORY: as an admin, I mark a benchmark redistributable after I check
its licence, so its owners can publish a cache version. The call is audited like the withdraw
route (`AdminAuditRoute`) and works only in `cloudflare_headers` (`require_admin`, D5).

INVARIANT: this route changes one column of a row that exists. It never creates a benchmark (the
same rule as `ScoreStore.set_visibility`, OME-904).
"""

from __future__ import annotations

from typing import Annotated, cast

from fastapi import APIRouter, Depends, Path, Request

from scoreboard.routes.admin import AdminAuditRoute, require_admin
from scoreboard.routes.errors import coded_error
from scoreboard.scores.schemas import RedistributableRequest, RedistributableResponse
from scoreboard.scores.store import ScoreStore

router = APIRouter(
    prefix="/v1/admin/benchmarks",
    tags=["Admin"],
    route_class=AdminAuditRoute,
    dependencies=[Depends(require_admin)],
)


@router.put("/{benchmark_id}/redistributable", response_model=RedistributableResponse)
async def set_benchmark_redistributable(
    benchmark_id: Annotated[str, Path(min_length=1, max_length=64)],
    body: RedistributableRequest,
    request: Request,
) -> RedistributableResponse:
    """Set the flag. The same value again is 200 with `changed: false` (idempotent)."""
    # WHY before the store call: a 404 must also log the reason and the change.
    request.state.admin_reason = body.reason
    request.state.admin_change = f"redistributable={'true' if body.redistributable else 'false'}"
    store = cast(ScoreStore, request.app.state.score_store)
    changed = await store.set_redistributable(benchmark_id, body.redistributable)
    if changed is None:
        raise coded_error(404, "benchmark_not_found", "benchmark not found")
    return RedistributableResponse(
        benchmark_id=benchmark_id, redistributable=body.redistributable, changed=changed
    )
