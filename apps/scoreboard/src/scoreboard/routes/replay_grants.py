"""`POST /v1/replay-grants` (C6): a signed grant to replay one pinned run.

FEATURE: OME-1307 (E14) replay grants. STORY: as Bruno I pin Ana's public run and get a grant the
gateway accepts for exactly that cache version, so my replay costs no provider call.

INVARIANT (OME-894): every 404 has the same body and the same headers, whatever the cause (unknown
name, unknown id, a private result of another user, a gated result, no version, unknown board). The
answer never confirms that a private result exists.
INVARIANT (OME-894): a grant for a non-owner is a public-derived answer, so `turned_private` is the
LAST await before `signer.sign`; the resolver's single board read may be stale by then.
INVARIANT: `signer.sign` runs only after the resolver returned. Nothing is minted for a pin that
does not resolve, and the route writes nothing.
INVARIANT: every response, errors included, carries `PRIVATE_CACHE_HEADERS`: the answer depends on
who asks.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any, cast

from fastapi import APIRouter, HTTPException, Request, Response
from tortoise.exceptions import OperationalError

from scoreboard.config import Settings
from scoreboard.core.registry import InvalidPin, PinNotFound
from scoreboard.core.replay.grants import (
    GrantSigner,
    PinBenchmarkMismatch,
    PinWithdrawn,
    ResolvedReplay,
    build_grant_claims,
)
from scoreboard.core.replay.pins import ReplayPin, parse_replay_pin
from scoreboard.metrics import Metrics
from scoreboard.routes.dependencies import PRIVATE_CACHE_HEADERS, turned_private
from scoreboard.routes.errors import STORE_UNAVAILABLE_DETAIL, UNPROCESSABLE, coded_error
from scoreboard.routes.scores import identity_is_verified
from scoreboard.routes.write_identity import write_identity
from scoreboard.scores.replay_resolver import ReplayPinResolver
from scoreboard.scores.schemas import (
    CodedErrorResponse,
    MessageErrorResponse,
    ReplayGrantRequest,
    ReplayGrantResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1", tags=["replay"])


REPLAY_GRANT_RESPONSES: dict[int | str, dict[str, Any]] = {
    401: {
        "model": CodedErrorResponse,
        "description": "identity_not_verified (cloudflare_headers).",
    },
    403: {"model": MessageErrorResponse, "description": "The peer is not a trusted network."},
    404: {"model": CodedErrorResponse, "description": "replay_pin_not_found, for every cause."},
    410: {"model": CodedErrorResponse, "description": "cache_version_withdrawn."},
    UNPROCESSABLE: {
        "model": CodedErrorResponse,
        "description": "invalid_replay_pin or replay_benchmark_mismatch.",
    },
    503: {
        "model": CodedErrorResponse,
        "description": "replay_unavailable (no signing key), or the score store is unavailable.",
    },
}

# INVARIANT: one message for every 404, so the bodies are byte-equal.
_NOT_FOUND_MESSAGE = "the pin names no run you may replay"


def _refusal(metrics: Metrics, label: str, error: HTTPException) -> HTTPException:
    """Count the outcome and return `error` with the private cache headers."""
    metrics.replay_grants.labels(result=label).inc()
    return HTTPException(error.status_code, error.detail, headers=PRIVATE_CACHE_HEADERS)


async def _caller(request: Request, metrics: Metrics) -> str | None:
    """The verified caller (D5). A plain call and not the `WriteIdentity` dependency: a dependency
    raises before the handler sets the private headers, so its refusal would miss them.
    """
    try:
        return await write_identity(request)
    except HTTPException as exc:
        raise _refusal(metrics, "unauthenticated", exc) from exc


def _resolution_error(metrics: Metrics, exc: Exception) -> HTTPException:
    if isinstance(exc, PinWithdrawn):
        return _refusal(
            metrics,
            "withdrawn",
            coded_error(
                410, "cache_version_withdrawn", "the cache version of this run is withdrawn"
            ),
        )
    if isinstance(exc, PinBenchmarkMismatch):
        return _refusal(
            metrics,
            "mismatch",
            coded_error(
                UNPROCESSABLE,
                "replay_benchmark_mismatch",
                "the pinned run belongs to another benchmark",
            ),
        )
    return _refusal(
        metrics,
        "not_found",
        coded_error(404, "replay_pin_not_found", _NOT_FOUND_MESSAGE),
    )


async def _resolve(
    state: Any, body: ReplayGrantRequest, pin: ReplayPin, identity: str | None, metrics: Metrics
) -> ResolvedReplay:
    """Resolve the pin once, then re-prove a non-owner's public board (OME-894)."""
    settings = cast(Settings, state.settings)
    try:
        resolved = await cast(ReplayPinResolver, state.replay_resolver).resolve(
            pin,
            body.pin,
            benchmark_id=body.benchmark_id,
            caller=identity,
            identity_verified=identity_is_verified(settings.auth_mode),
        )
        # WHY inside the try: a refusal and a store failure map as the resolver's do (404 / 503).
        if not resolved.via_owner and await turned_private(body.benchmark_id):
            raise PinNotFound(body.pin)
    except (PinNotFound, PinWithdrawn, PinBenchmarkMismatch) as exc:
        raise _resolution_error(metrics, exc) from exc
    except OperationalError as exc:
        raise HTTPException(503, STORE_UNAVAILABLE_DETAIL, headers=PRIVATE_CACHE_HEADERS) from exc
    return resolved


@router.post(
    "/replay-grants",
    response_model=ReplayGrantResponse,
    responses=REPLAY_GRANT_RESPONSES,
)
async def issue_replay_grant(
    body: ReplayGrantRequest, request: Request, response: Response
) -> ReplayGrantResponse:
    """Resolve the pin once, apply the replay access rule and sign a 12 h grant (C6)."""
    response.headers.update(PRIVATE_CACHE_HEADERS)
    state = request.app.state
    metrics = cast(Metrics, state.metrics)
    identity = await _caller(request, metrics)
    signer = cast(GrantSigner | None, state.grant_signer)
    if signer is None:
        raise _refusal(
            metrics,
            "unavailable",
            coded_error(503, "replay_unavailable", "replay grants are not configured"),
        )
    try:
        pin = parse_replay_pin(body.pin)
    except InvalidPin as exc:
        raise _refusal(
            metrics, "invalid", coded_error(UNPROCESSABLE, exc.code, exc.message)
        ) from exc
    now = cast(datetime, state.clock())
    resolved = await _resolve(state, body, pin, identity, metrics)
    claims = build_grant_claims(
        subject=identity,
        cache_version_id=resolved.cache_version_id,
        result_id=resolved.result_id,
        now=now,
    )
    grant = signer.sign(claims)
    metrics.replay_grants.labels(result="issued").inc()
    # WHY only ids: the grant, the key and the caller email are never logged.
    logger.info("replay grant issued result_id=%s", resolved.result_id)
    return ReplayGrantResponse(
        grant=grant,
        result_id=resolved.result_id,
        score_id=resolved.score_id,
        cache_version_id=resolved.cache_version_id,
        expires_at=datetime.fromtimestamp(cast(int, claims["exp"]), UTC),
    )
