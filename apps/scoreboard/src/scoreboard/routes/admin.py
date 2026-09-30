"""Admin routes (E14, OME-1307): takedown of a published cache version.

FEATURE: OME-1307 (E14), STORY: as an admin, I withdraw a cache version whose license or content
must not stay public, and the release disappears from GitHub while the score stays on the board.

`require_admin` and `AdminAuditRoute` are public on purpose: unit WIRING (D6) reuses both for its
audited `Benchmark.redistributable` route.

INVARIANT: the peer network is checked BEFORE the identity header is read (`write_identity`), and
the allowlist works only in `cloudflare_headers` mode (D5, OD-4): the `disabled` fallback reads no
identity, so it answers 503 `admin_unavailable`.
INVARIANT: every admin attempt leaves one audit line, refusals included. A run of 403s is what an
attempt from outside the allowlist looks like, and it is invisible if only successes are logged.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Coroutine, Mapping
from typing import Any, cast
from urllib.parse import quote
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.exceptions import RequestValidationError
from fastapi.routing import APIRoute

from scoreboard.config import Settings
from scoreboard.core.auth.admin import AdminPrincipal, email_is_admin
from scoreboard.core.publish.release_body import escape_markdown
from scoreboard.routes.errors import coded_error
from scoreboard.routes.write_identity import write_identity
from scoreboard.scores.models import CacheVersionPublication, ReportedResult
from scoreboard.scores.publication_store import PublicationStore
from scoreboard.scores.schemas import PublishStateResponse, WithdrawRequest

logger = logging.getLogger(__name__)

_REASON_LOG_MAX = 120


def _unavailable() -> HTTPException:
    return coded_error(
        status.HTTP_503_SERVICE_UNAVAILABLE,
        "admin_unavailable",
        "the admin API is not available on this deployment",
    )


async def require_admin(request: Request) -> AdminPrincipal:
    """The calling administrator, or a refusal. The order of the checks is load-bearing.

    1. Empty allowlist: 503. 2. Not `cloudflare_headers`: 503. 3. and 4. `write_identity`: an
    untrusted peer is 403 (never reads the header), no header is 401. 5. Not on the list: 403.
    `request.state.admin_actor` is set before step 5, so the audit line names a refused caller.
    """
    settings = cast(Settings, request.app.state.settings)
    if not settings.admin_emails or settings.auth_mode != "cloudflare_headers":
        raise _unavailable()
    # WHY the cast: `write_identity` is None only for a mode that does not verify a caller, and
    # the check above already refused every such mode.
    actor = cast(str, await write_identity(request))
    request.state.admin_actor = actor
    if not email_is_admin(actor, settings.admin_emails):
        raise coded_error(
            status.HTTP_403_FORBIDDEN, "admin_required", "this account is not an administrator"
        )
    return AdminPrincipal(email=actor)


def _audit_target(path_params: Mapping[str, str]) -> str:
    """'result_id=<id>' or 'benchmark_id=<id>'; '<none>' when neither is there.

    INVARIANT: the value is caller text (Starlette percent-decodes it, and the audit line is
    written before the `Path` length rule runs), so it is percent-encoded and cut before it is
    logged. A newline or a space cannot forge a second line or a second field. A UUID and an
    ordinary benchmark id stay byte-for-byte the same.
    """
    for name in ("result_id", "benchmark_id"):
        if name in path_params:
            return f"{name}={quote(str(path_params[name]), safe='')[:_REASON_LOG_MAX]}"
    return "<none>"


def _audit(request: Request, outcome: int) -> None:
    """One INFO line per attempt: actor, target, reason, outcome, and the change (PRD section 4)."""
    actor = getattr(request.state, "admin_actor", None)
    reason = getattr(request.state, "admin_reason", None)
    change = getattr(request.state, "admin_change", None)
    who = actor if actor is not None else "<unidentified>"
    target = _audit_target(request.path_params)
    # INVARIANT: the reason is caller text. It is escaped (no control character survives, so it
    # cannot forge a second line) and cut, before it reaches the log.
    shown = escape_markdown(reason)[:_REASON_LOG_MAX] if reason is not None else "<none>"
    # WHY the change comes last and only when set: the withdraw line stays byte-for-byte the same.
    suffix = f" change={change}" if change is not None else ""
    logger.info(
        "admin_action actor=%s %s reason=%s outcome=%d%s", who, target, shown, outcome, suffix
    )
    before = getattr(request.state, "admin_before", None)
    after = getattr(request.state, "admin_after", None)
    # INVARIANT (MRA-2, C10): a successful change leaves the value before and after it. It is a
    # second line, not a longer `admin_action` line, because the `admin_action` line is pinned by
    # prior tests. `before` and `after` are server values (a state, a flag), never caller text.
    if outcome < status.HTTP_400_BAD_REQUEST and before is not None and after is not None:
        logger.info(
            "admin_change actor=%s %s before=%s after=%s reason=%s",
            who,
            target,
            before,
            after,
            shown,
        )


class AdminAuditRoute(APIRoute):
    def get_route_handler(self) -> Callable[[Request], Coroutine[Any, Any, Response]]:
        original_handler = super().get_route_handler()

        async def audited_handler(request: Request) -> Response:
            try:
                response = await original_handler(request)
            except HTTPException as exc:
                _audit(request, exc.status_code)
                raise
            except RequestValidationError:
                _audit(request, 422)
                raise
            except Exception:
                _audit(request, 500)
                raise
            _audit(request, response.status_code)
            return response

        return audited_handler


router = APIRouter(
    prefix="/v1/admin",
    tags=["Admin"],
    route_class=AdminAuditRoute,
    dependencies=[Depends(require_admin)],
)


@router.post("/results/{result_id}/withdraw", response_model=PublishStateResponse)
async def withdraw_result(
    result_id: UUID,
    body: WithdrawRequest,
    request: Request,
    admin: AdminPrincipal = Depends(require_admin),
) -> PublishStateResponse:
    """Withdraw the publication of a result. The row and the head stay, with the marker (PB-H4)."""
    request.state.admin_reason = body.reason
    if await ReportedResult.get_or_none(id=result_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="result not found")
    if await CacheVersionPublication.get_or_none(result_id=result_id) is None:
        raise coded_error(
            status.HTTP_409_CONFLICT,
            "not_publishable",
            "this result has no cache version to withdraw",
            reason="no_cache_version",
        )
    store = cast(PublicationStore, request.app.state.publication_store)

    def record_before(previous: str) -> None:
        request.state.admin_before = previous

    state = await store.withdraw(
        result_id,
        actor=admin.email,
        reason=body.reason,
        now=request.app.state.clock(),
        on_previous=record_before,
    )
    request.state.admin_after = state
    return PublishStateResponse(state=state)
