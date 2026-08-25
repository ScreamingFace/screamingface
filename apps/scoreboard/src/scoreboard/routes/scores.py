"""Public score submission and score lookup routes.

Reads are always public. Writes trust the client-supplied ``submitted_by`` free text by
default (``auth_mode=disabled``); setting ``SCOREBOARD_AUTH_MODE=cloudflare_headers``
requires and trusts the mesh-verified `X-User-Email` identity header instead (OME-404,
following OME-326). The verified_by_screamingface response field is a separate, independent
trust-tier signal: it is unrelated to how the submitter was identified, and it is never
settable by a client — it is absent from ScoreSubmission, so sending it is a 422.

Since OME-820 it defaults to True as a temporary placeholder that asserts **nothing**.
Nothing re-runs submissions (OME-414), and nothing attests where a run executed, so the
public portal states that scores are self-reported and that the column does not yet
distinguish rows. OME-821 replaces it with a real distinction.
"""

from __future__ import annotations

from typing import Annotated, Any, cast
from uuid import UUID

from fastapi import APIRouter, Header, HTTPException, Request, Response, status
from tortoise.exceptions import OperationalError

from scoreboard.config import Settings
from scoreboard.core.auth.cloudflare_identity import (
    HEADER_USER_EMAIL,
    identity_from_headers,
    peer_in_networks,
)
from scoreboard.routes.dependencies import ReadIdentity
from scoreboard.scores.models import Benchmark, Score
from scoreboard.scores.schemas import (
    FieldErrorDetail,
    FieldErrorResponse,
    MessageErrorResponse,
    ScoreSchema,
    ScoreSubmission,
)
from scoreboard.scores.store import ScoreStore

router = APIRouter(prefix="/v1", tags=["scores"])

STORE_UNAVAILABLE_DETAIL = "score store unavailable"
# INVARIANT (OME-894): one detail for a missing score AND for a private score the caller
# may not read, so the two are indistinguishable.
SCORE_NOT_FOUND_DETAIL = "score not found"
UNTRUSTED_PEER_DETAIL = (
    "This service accepts header identity only from the networks it was configured to trust."
)
MISSING_IDENTITY_DETAIL = (
    f"Missing {HEADER_USER_EMAIL} — this service resolves the submitter from the identity "
    "header the mesh gateway injects after verifying Cloudflare Access."
)


async def _resolve_submitter(request: Request, submission: ScoreSubmission) -> str | None:
    """Who actually submitted this: client-supplied free text in ``disabled`` (dev/test)
    mode, or the mesh-verified identity header in ``cloudflare_headers`` mode.

    INVARIANT: no-identity is a 401, never a silent fallback to anonymous or to the
    caller's own claim — a misconfigured mesh (Envoy bypassed, or not injecting) must not
    turn into a service that lets a caller name themselves.

    INVARIANT: the peer network is checked BEFORE the header is read, so an untrusted peer
    is refused without its identity claim ever being consulted.

    AIDEV-NOTE: deliberately a plain call at the top of `submit_score`, not a `Depends()` —
    it needs the already-parsed `submission` body for the disabled-mode fallback. This means
    a second authenticated route does NOT get this check for free the way aigateway's
    `CurrentAccount` dependency generalizes; either extract the header/peer logic into a
    proper `Depends()` at that point, or copy this call verbatim — don't add a route with a
    write path and skip it silently.
    """
    settings = cast(Settings, request.app.state.settings)
    if settings.auth_mode == "disabled":
        return submission.submitted_by
    if not peer_in_networks(
        request.client.host if request.client is not None else None,
        settings.allowed_networks,
    ):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=UNTRUSTED_PEER_DETAIL)
    email = identity_from_headers(request.headers)
    if email is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail=MISSING_IDENTITY_DETAIL
        )
    return email


SUBMIT_SCORE_RESPONSES: dict[int | str, dict[str, Any]] = {
    status.HTTP_200_OK: {
        "model": ScoreSchema,
        "description": "Idempotency hit; returns the original persisted score.",
    },
    status.HTTP_400_BAD_REQUEST: {
        "model": FieldErrorResponse,
        "description": "Field-specific validation error.",
    },
    status.HTTP_401_UNAUTHORIZED: {
        "model": MessageErrorResponse,
        "description": "Missing X-User-Email identity header (cloudflare_headers mode only).",
    },
    status.HTTP_403_FORBIDDEN: {
        "model": MessageErrorResponse,
        "description": "Caller's peer network is not trusted to present identity headers.",
    },
    status.HTTP_404_NOT_FOUND: {
        "model": FieldErrorResponse,
        "description": "Unknown benchmark_id.",
    },
    status.HTTP_503_SERVICE_UNAVAILABLE: {
        "model": MessageErrorResponse,
        "description": "Score store unavailable.",
    },
}
GET_SCORE_RESPONSES: dict[int | str, dict[str, Any]] = {
    status.HTTP_404_NOT_FOUND: {
        "model": MessageErrorResponse,
        "description": "Score not found.",
    },
    status.HTTP_503_SERVICE_UNAVAILABLE: SUBMIT_SCORE_RESPONSES[
        status.HTTP_503_SERVICE_UNAVAILABLE
    ],
}


def _field_error_detail(field: str, message: str) -> dict[str, str]:
    return FieldErrorDetail(field=field, message=message).model_dump()


@router.post(
    "/scores",
    response_model=ScoreSchema,
    status_code=status.HTTP_201_CREATED,
    responses=SUBMIT_SCORE_RESPONSES,
)
async def submit_score(
    submission: ScoreSubmission,
    request: Request,
    response: Response,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> ScoreSchema:
    """Create a score submission; submitter identity depends on SCOREBOARD_AUTH_MODE."""

    # WHY resolved before any business-rule validation: the old shared-key gate ran as a
    # FastAPI Depends(), so it always executed before this function's body — an
    # unauthenticated/untrusted caller was rejected before ever learning anything about
    # its payload. Keeping identity resolution first preserves that ordering now that it's
    # a plain call instead of a dependency.
    submitted_by = await _resolve_submitter(request, submission)
    submission = submission.model_copy(update={"submitted_by": submitted_by})

    # INVARIANT (OME-866): the Engine benchmark is the sole scoring authority. The old
    # ±0.01 accuracy-vs-correct/total cross-check was DELETED here, not replaced — the
    # Scoreboard never recomputes, normalizes or second-guesses the submitted score.

    try:
        if not await Benchmark.exists(id=submission.benchmark_id):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=_field_error_detail(
                    "benchmark_id",
                    f"unknown benchmark_id: {submission.benchmark_id!r}",
                ),
            )

        store = cast(ScoreStore, request.app.state.score_store)
        outcome = await store.submit(submission, idempotency_key=idempotency_key)
        if not outcome.created:
            # WHY: a single atomic submit() call — not a separate pre-check plus a
            # second call — so the reported status code always matches what actually
            # happened, including under a concurrent-duplicate race (found in PR
            # review, OME-391 / C28).
            response.status_code = status.HTTP_200_OK
        return outcome.score
    except OperationalError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=STORE_UNAVAILABLE_DETAIL,
        ) from exc


@router.get("/scores/{score_id}", response_model=ScoreSchema, responses=GET_SCORE_RESPONSES)
async def get_score(score_id: UUID, identity: ReadIdentity) -> ScoreSchema:
    """Return a public score by id.

    ``verified_by_screamingface`` carries no verification claim yet: nothing re-runs
    submissions and nothing attests execution provenance (OME-820, OME-821).
    """

    try:
        score = await Score.get_or_none(id=score_id)
    except OperationalError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=STORE_UNAVAILABLE_DETAIL,
        ) from exc

    if score is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=SCORE_NOT_FOUND_DETAIL)

    # FEATURE: OME-894 — a private benchmark's submissions belong to their submitter alone. This
    # route is a score-bearing read path like the four on the leaderboard, and score UUIDs are
    # handed out by the submission response and by per-spec history, so leaving it open would
    # publish a private run's url4_expression and metadata to anyone holding an id.
    # INVARIANT: the SAME 404 an unknown id gets, so holding a real id is not confirmable.
    # `benchmark_id` is the foreign key's shadow column and is not a declared attribute, so it
    # is read the same way scores/store.py reads it.
    benchmark = await Benchmark.get_or_none(id=cast(str, getattr(score, "benchmark_id")))
    private = benchmark is None or benchmark.visibility == "private"
    if private and (identity is None or score.submitted_by != identity):
        # `benchmark is None` cannot happen behind the RESTRICT foreign key; it fails closed
        # rather than serving a score whose visibility could not be established.
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=SCORE_NOT_FOUND_DETAIL)

    return ScoreSchema.model_validate(score, from_attributes=True)
