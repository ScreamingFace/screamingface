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

from scoreboard.config import AuthMode, Settings
from scoreboard.core.auth.cloudflare_identity import (
    HEADER_USER_EMAIL,
    identity_from_headers,
    peer_in_networks,
)
from scoreboard.routes.dependencies import (
    PRIVATE_CACHE_HEADERS,
    ReadIdentity,
    turned_private,
)
from scoreboard.scores.models import Benchmark, Score
from scoreboard.scores.schemas import (
    FieldErrorDetail,
    FieldErrorResponse,
    MessageErrorResponse,
    ScoreRankingNotice,
    ScoreSchema,
    ScoreSubmission,
)
from scoreboard.scores.store import (
    BenchmarkVisibilityChanged,
    ConcurrentScoreUpdate,
    PrivateBoardRequiresIdentity,
    ScoreStore,
)

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


CONCURRENT_UPDATE_DETAIL = (
    "another request changed this submission while its authors were being corrected; retry"
)


VISIBILITY_CHANGED_DETAIL = (
    "the benchmark's visibility changed while this submission was in flight; retry"
)


def identity_is_verified(auth_mode: AuthMode) -> bool:
    """Whether `auth_mode` produces a submitter identity the server established itself.

    INVARIANT: an ALLOWLIST, deliberately. `!= "disabled"` reads the same today, but it treats any
    mode added later as verifying until someone remembers to exclude it — the fail-open direction,
    on the decision that governs whether a private board accepts a write. Naming the modes that DO
    verify means a new one has to be added here on purpose (review of PR #719).
    """
    return auth_mode == "cloudflare_headers"


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


def _submission_response(score: ScoreSchema, registered_revision: str | None) -> ScoreSchema:
    submitted_revision = score.benchmark_revision
    if registered_revision is None or submitted_revision == registered_revision:
        return score
    return score.model_copy(
        update={
            "ranking_notice": ScoreRankingNotice(
                code="benchmark_revision_mismatch",
                submitted_benchmark_revision=submitted_revision,
                registered_benchmark_revision=registered_revision,
            )
        }
    )


@router.post(
    "/scores",
    response_model=ScoreSchema,
    response_model_exclude_unset=True,
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
        # AIDEV-NOTE: `exists()` stays the existence gate rather than folding into the
        # visibility read below. It is the seam `test_post_score_store_unavailable_returns_503`
        # patches to prove an unavailable database yields 503 rather than a traceback, and that
        # guarantee is worth one extra indexed lookup on a non-hot write path.
        if not await Benchmark.exists(id=submission.benchmark_id):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=_field_error_detail(
                    "benchmark_id",
                    f"unknown benchmark_id: {submission.benchmark_id!r}",
                ),
            )

        # FEATURE (OME-909): snapshot before the write, inside the same unavailable-store
        # boundary. A read after a successful insert could fail and hide the persisted id from
        # the caller. Keep `exists()` above as the established 404/503 seam; this narrow second
        # read supplies only the submit-time comparability fact.
        benchmark = await Benchmark.filter(id=submission.benchmark_id).only("revision").first()
        registered_revision = None if benchmark is None else benchmark.revision

        # INVARIANT (OME-894): a private board cannot take a write without a VERIFIED submitter.
        # In `disabled` mode `_resolve_submitter` trusts the body's `submitted_by`, and combined
        # with per-submitter dedup that is a read primitive, not just a spoofing risk: forge a
        # participant's address, submit a matching recipe, and the dedup path hands back their
        # stored row — url4, metadata and id included. Reproduced in review of PR #719.
        #
        # WHY the decision is NOT taken here any more: this route used to read `visibility` itself
        # and refuse before calling the store. The store reads it again to decide per-submitter
        # dedup, and the WRITE is governed by that second read — so a board flipped private in
        # between passed this guard and was then persisted under private rules with an unverified
        # claim. The store now owns the whole decision at its single read, and a private write
        # still cannot reach dedup: `submit()` refuses before looking anything up.
        #
        # Reads already fail closed in this mode (D2); this keeps writes matching, so a private
        # board is inert in both directions until identity is real rather than half-open.
        settings = cast(Settings, request.app.state.settings)
        store = cast(ScoreStore, request.app.state.score_store)
        try:
            outcome = await store.submit(
                submission,
                idempotency_key=idempotency_key,
                identity_verified=identity_is_verified(settings.auth_mode),
            )
        except BenchmarkVisibilityChanged as exc:
            # The board changed under the request, so it was refused rather than completed on stale
            # rules. 409 rather than 500: nothing is wrong with the request, and retrying it gets a
            # consistent view (review of PR #719).
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=VISIBILITY_CHANGED_DETAIL,
            ) from exc
        except ConcurrentScoreUpdate as exc:
            # Same reasoning as the visibility 409 above: nothing is wrong with the request, and a
            # retry resolves the row again and re-applies the correction. Caught BEFORE the outer
            # `except OperationalError`, which would otherwise answer 503 store-unavailable for a
            # race the store handled perfectly well (OME-1054).
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=CONCURRENT_UPDATE_DETAIL,
            ) from exc
        except PrivateBoardRequiresIdentity as exc:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    "submissions to a private benchmark require a verified identity; this "
                    "deployment runs with authentication disabled"
                ),
            ) from exc
        if not outcome.created:
            # WHY: a single atomic submit() call — not a separate pre-check plus a
            # second call — so the reported status code always matches what actually
            # happened, including under a concurrent-duplicate race (found in PR
            # review, OME-391 / C28).
            response.status_code = status.HTTP_200_OK
        return _submission_response(outcome.score, registered_revision)
    except OperationalError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=STORE_UNAVAILABLE_DETAIL,
        ) from exc


@router.get("/scores/{score_id}", response_model=ScoreSchema, responses=GET_SCORE_RESPONSES)
async def get_score(score_id: UUID, response: Response, identity: ReadIdentity) -> ScoreSchema:
    """Return a public score by id.

    ``verified_by_screamingface`` carries no verification claim yet: nothing re-runs
    submissions and nothing attests execution provenance (OME-820, OME-821).
    """

    try:
        score = await Score.get_or_none(id=score_id)
        # FEATURE: OME-894 — a private benchmark's submissions belong to their submitter alone.
        # This route is a score-bearing read path like the four on the leaderboard, and score
        # UUIDs are handed out by the submission response and by per-spec history, so leaving it
        # open would publish a private run's url4_expression and metadata to anyone holding an id.
        # `benchmark_id` is the foreign key's shadow column and is not a declared attribute, so
        # it is read the same way scores/store.py reads it.
        #
        # INVARIANT: this second read sits INSIDE the same error boundary as the first. It used to
        # follow the try block, so a transient disconnect between the two reads escaped as an
        # unhandled 500 on an endpoint that documents 503 (found in review of PR #719).
        benchmark = (
            None
            if score is None
            else await Benchmark.get_or_none(id=cast(str, getattr(score, "benchmark_id")))
        )
    except OperationalError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=STORE_UNAVAILABLE_DETAIL,
        ) from exc

    if score is None:
        # INVARIANT: carries the private policy even though nothing private is involved. The
        # refusal below is byte-identical BY DESIGN, and a header only one of the two emits is
        # itself the discriminator — it confirms a real private score id exists (review of #719).
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=SCORE_NOT_FOUND_DETAIL,
            headers=PRIVATE_CACHE_HEADERS,
        )

    # INVARIANT: the SAME 404 an unknown id gets, so holding a real id is not confirmable.
    private = benchmark is None or benchmark.visibility == "private"
    if private:
        # Identity-scoped, so it must not be shared-cacheable — including the refusal, which is
        # equally identity-dependent (OME-894, raised in review of PR #719).
        response.headers.update(PRIVATE_CACHE_HEADERS)
    if private and (identity is None or score.submitted_by != identity):
        # `benchmark is None` cannot happen behind the RESTRICT foreign key; it fails closed
        # rather than serving a score whose visibility could not be established.
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=SCORE_NOT_FOUND_DETAIL,
            headers=PRIVATE_CACHE_HEADERS,
        )

    # The window here is read -> serialise rather than read -> query, since nothing else is fetched
    # after the visibility read. Closed anyway, so every score-bearing read answers from one view
    # of `visibility` rather than three of them agreeing by luck (review of PR #719).
    if not private and await turned_private(cast(str, getattr(score, "benchmark_id"))):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=SCORE_NOT_FOUND_DETAIL,
            headers=PRIVATE_CACHE_HEADERS,
        )

    return ScoreSchema.model_validate(score, from_attributes=True)
