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

import logging
from typing import Annotated, Any, cast
from uuid import UUID

from fastapi import APIRouter, Header, HTTPException, Request, Response, status
from tortoise.exceptions import OperationalError

from scoreboard.config import AuthMode, Settings

# The two identity details moved to `routes/dependencies.py` with the shared check. They are
# re-exported here because callers and tests import them from this module.
from scoreboard.routes.dependencies import (
    MISSING_IDENTITY_DETAIL as MISSING_IDENTITY_DETAIL,
)
from scoreboard.routes.dependencies import (
    PRIVATE_CACHE_HEADERS,
    ReadIdentity,
    VerifiedIdentity,
    turned_private,
    verified_identity,
)
from scoreboard.routes.dependencies import (
    UNTRUSTED_PEER_DETAIL as UNTRUSTED_PEER_DETAIL,
)
from scoreboard.scores.models import Benchmark, Score
from scoreboard.scores.schemas import (
    CodedErrorResponse,
    FieldErrorDetail,
    FieldErrorResponse,
    MessageErrorResponse,
    ReproductionSchema,
    ReproductionSubmission,
    ScoreMetadataEventSchema,
    ScoreMetadataPatch,
    ScoreRankingNotice,
    ScoreSchema,
    ScoreSubmission,
    ValidationErrorResponse,
)
from scoreboard.scores.store import (
    BenchmarkVisibilityChanged,
    ConcurrentScoreUpdate,
    PrivateBoardRequiresIdentity,
    ReproductionRunIdConflict,
    ScoreStore,
)

router = APIRouter(prefix="/v1", tags=["scores"])
logger = logging.getLogger(__name__)

STORE_UNAVAILABLE_DETAIL = "score store unavailable"
# INVARIANT (OME-894): one detail for a missing score AND for a private score the caller
# may not read, so the two are indistinguishable.
SCORE_NOT_FOUND_DETAIL = "score not found"


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
    it needs the already-parsed `submission` body for the disabled-mode fallback. The header and
    peer decision itself is `verified_identity` in `routes/dependencies.py`; every other
    authenticated write route takes `VerifiedIdentity` and gets that check for free. Don't add a
    route with a write path and skip it silently.
    """
    settings = cast(Settings, request.app.state.settings)
    if settings.auth_mode == "disabled":
        return submission.submitted_by
    return await verified_identity(request)


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


OWNER_ONLY_RESPONSES: dict[int | str, dict[str, Any]] = {
    status.HTTP_401_UNAUTHORIZED: {
        "model": MessageErrorResponse,
        "description": (
            "Missing X-User-Email identity header. Returned in BOTH auth modes: these routes read "
            "the header even when SCOREBOARD_AUTH_MODE is `disabled`."
        ),
    },
    status.HTTP_403_FORBIDDEN: {
        "model": MessageErrorResponse | CodedErrorResponse,
        "description": (
            "Two shapes. An untrusted peer network (cloudflare_headers mode) is a string `detail` "
            "(`MessageErrorResponse`). A visible score that is not the caller's is "
            "`{code: not_score_owner, message}` (`CodedErrorResponse`)."
        ),
    },
    status.HTTP_404_NOT_FOUND: {
        "model": MessageErrorResponse,
        "description": "Score not found, or a private-board score that is not the caller's.",
    },
    status.HTTP_409_CONFLICT: {
        "model": MessageErrorResponse,
        "description": "The board's visibility changed while the request was in flight; retry.",
    },
    status.HTTP_503_SERVICE_UNAVAILABLE: SUBMIT_SCORE_RESPONSES[
        status.HTTP_503_SERVICE_UNAVAILABLE
    ],
}
PATCH_SCORE_RESPONSES: dict[int | str, dict[str, Any]] = {
    **OWNER_ONLY_RESPONSES,
    status.HTTP_200_OK: {
        "model": ScoreSchema,
        "description": "The score after the edit (unchanged values write no event).",
    },
}
RECORD_REPRODUCTION_RESPONSES: dict[int | str, dict[str, Any]] = {
    status.HTTP_200_OK: {
        "model": ReproductionSchema,
        "description": "You already recorded this run_id for the score; returns that row.",
    },
    status.HTTP_401_UNAUTHORIZED: OWNER_ONLY_RESPONSES[status.HTTP_401_UNAUTHORIZED],
    status.HTTP_403_FORBIDDEN: SUBMIT_SCORE_RESPONSES[status.HTTP_403_FORBIDDEN],
    status.HTTP_404_NOT_FOUND: OWNER_ONLY_RESPONSES[status.HTTP_404_NOT_FOUND],
    status.HTTP_409_CONFLICT: {
        "model": CodedErrorResponse | MessageErrorResponse,
        "description": (
            "Two shapes. `{code: not_reproducible}`: the score is not `complete`, so there is "
            "nothing to replay. `{code: run_id_conflict}`: another identity already recorded this "
            "run_id for the score (nothing about that row is returned; use a new run_id). A string "
            "`detail` (`MessageErrorResponse`): the board's visibility changed mid-request; retry."
        ),
    },
    422: {
        "model": CodedErrorResponse | ValidationErrorResponse,
        "description": (
            "Two shapes. `{code: not_exact}` (`CodedErrorResponse`): the score, total_questions or "
            "cache_revision differs from the stored score. A list `detail` "
            "(`ValidationErrorResponse`): the body failed validation."
        ),
    },
    status.HTTP_503_SERVICE_UNAVAILABLE: SUBMIT_SCORE_RESPONSES[
        status.HTTP_503_SERVICE_UNAVAILABLE
    ],
}
GET_METADATA_EVENTS_RESPONSES: dict[int | str, dict[str, Any]] = {
    **OWNER_ONLY_RESPONSES,
    status.HTTP_200_OK: {
        "model": list[ScoreMetadataEventSchema],
        "description": "The score's edit log, newest first.",
    },
}


def _score_not_found() -> HTTPException:
    # Identity-scoped, so the refusal carries the private cache policy (see `get_score`).
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=SCORE_NOT_FOUND_DETAIL,
        headers=PRIVATE_CACHE_HEADERS,
    )


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
async def get_score(
    score_id: UUID, request: Request, response: Response, identity: ReadIdentity
) -> ScoreSchema:
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
        # FEATURE: OME-1307 — one aggregate (COUNT, MAX) over the recorded reproductions, read with
        # the other two so the store-unavailable boundary covers it. Fetched before the access
        # decision below and used only if the score is served; the refusals never carry it.
        reproductions = (
            (0, None)
            if score is None
            else await cast(ScoreStore, request.app.state.score_store).reproduction_aggregate(
                score_id
            )
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
        raise _score_not_found()

    # INVARIANT: the SAME 404 an unknown id gets, so holding a real id is not confirmable.
    private = benchmark is None or benchmark.visibility == "private"
    if private:
        # Identity-scoped, so it must not be shared-cacheable — including the refusal, which is
        # equally identity-dependent (OME-894, raised in review of PR #719).
        response.headers.update(PRIVATE_CACHE_HEADERS)
    if private and (identity is None or score.submitted_by != identity):
        # `benchmark is None` cannot happen behind the RESTRICT foreign key; it fails closed
        # rather than serving a score whose visibility could not be established.
        raise _score_not_found()

    # The window here is read -> serialise rather than read -> query, since nothing else is fetched
    # after the visibility read. Closed anyway, so every score-bearing read answers from one view
    # of `visibility` rather than three of them agreeing by luck (review of PR #719).
    if not private and await turned_private(cast(str, getattr(score, "benchmark_id"))):
        raise _score_not_found()

    count, last_reproduced_at = reproductions
    return ScoreSchema.model_validate(score, from_attributes=True).model_copy(
        update={"reproduction_count": count, "last_reproduced_at": last_reproduced_at}
    )


async def _load_visible_score(
    request: Request, score_id: UUID, identity: str
) -> tuple[Score, bool]:
    """The score ``identity`` may see and whether its board is private, or the 503 / 404 refusal.

    Shared by the owner-only routes and the reproduction record. The flag is what this decision
    ASSUMED about the board; a write path re-proves it inside its transaction.

    INVARIANT: a missing score and a private-board score the caller may not see are the SAME 404,
    so holding a real id is not confirmable (OME-894).

    INVARIANT: on a private board the owner match counts only when the identity is VERIFIED. In
    `disabled` mode `X-User-Email` is an unverified claim, and honouring it would let anyone read
    or edit a private row by naming its owner — `read_identity` ignores it for the same reason.

    INVARIANT: a board row that cannot be found counts as private, as in `get_score`. That cannot
    happen behind the RESTRICT foreign key, so this fails closed rather than answering from a
    state nobody established.

    WHY the privacy decision ends in `turned_private`: it reads the board's state fresh,
    immediately before the answer that depends on it, so there is no earlier copy to go stale
    between the read and any answer that would otherwise confirm the id exists.
    """
    try:
        score = await Score.get_or_none(id=score_id)
        if score is None:
            private = False
        else:
            board_id = cast(str, getattr(score, "benchmark_id"))
            private = not await Benchmark.exists(id=board_id) or await turned_private(board_id)
    except OperationalError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=STORE_UNAVAILABLE_DETAIL,
        ) from exc
    if score is None:
        raise _score_not_found()

    settings = cast(Settings, request.app.state.settings)
    owner = score.submitted_by == identity
    if private and not (owner and identity_is_verified(settings.auth_mode)):
        raise _score_not_found()
    return score, private


async def _load_owned_score(request: Request, score_id: UUID, identity: str) -> tuple[Score, bool]:
    """The score ``identity`` submitted and whether its board is private, or the refusal.

    The shared checks run first (`_load_visible_score`), so a score the caller may see but did not
    submit is the only thing left to answer 403 `not_score_owner`.
    """
    score, private = await _load_visible_score(request, score_id, identity)
    if score.submitted_by == identity:
        return score, private
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail={
            "code": "not_score_owner",
            "message": "only the verified submitter of a score can edit it or read its edit log",
        },
        headers=PRIVATE_CACHE_HEADERS,
    )


@router.patch(
    "/scores/{score_id}",
    response_model=ScoreSchema,
    responses=PATCH_SCORE_RESPONSES,
)
async def patch_score(
    score_id: UUID,
    patch: ScoreMetadataPatch,
    request: Request,
    response: Response,
    identity: VerifiedIdentity,
) -> ScoreSchema:
    """Edit the authors and paper link of a score you submitted (E14 A1).

    An absent key leaves the field unchanged; `paper_url: null` clears the link. Every change is
    logged (`GET /v1/scores/{id}/metadata-events`); a request that changes nothing is a no-op.
    """
    score, private = await _load_owned_score(request, score_id, identity)
    if private:
        # Identity-scoped, so it must not be shared-cacheable (as `get_score` does for the board).
        response.headers.update(PRIVATE_CACHE_HEADERS)
    store = cast(ScoreStore, request.app.state.score_store)
    try:
        updated = await store.patch_metadata(
            score_id,
            edited_by=identity,
            # `model_fields_set`, not a default dump: it is what tells an absent key from null.
            changes=patch.model_dump(include=patch.model_fields_set),
            benchmark_id=cast(str, getattr(score, "benchmark_id")),
            expect_private=private,
        )
    except BenchmarkVisibilityChanged as exc:
        # The board changed between the check above and the locked write. Same answer as the
        # resubmit path: nothing is wrong with the request, and a retry sees one consistent view.
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=VISIBILITY_CHANGED_DETAIL,
        ) from exc
    except OperationalError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=STORE_UNAVAILABLE_DETAIL,
        ) from exc
    if updated is None:
        # Deleted between the ownership check and the lock.
        raise _score_not_found()
    return updated


@router.get(
    "/scores/{score_id}/metadata-events",
    response_model=list[ScoreMetadataEventSchema],
    responses=GET_METADATA_EVENTS_RESPONSES,
)
async def get_metadata_events(
    score_id: UUID,
    request: Request,
    response: Response,
    identity: VerifiedIdentity,
) -> list[ScoreMetadataEventSchema]:
    """The edit log of a score you submitted, newest first. Never public: it holds author emails."""
    await _load_owned_score(request, score_id, identity)  # the refusal; the flag is not needed
    # INVARIANT: identity-scoped and sensitive, so no shared cache may keep it.
    response.headers.update(PRIVATE_CACHE_HEADERS)
    store = cast(ScoreStore, request.app.state.score_store)
    try:
        return await store.metadata_events(score_id)
    except OperationalError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=STORE_UNAVAILABLE_DETAIL,
        ) from exc


def _refuse_unless_exact(score: Score, body: ReproductionSubmission) -> None:
    """409 when the score is not `complete`, then 422 when the body is not the stored result."""
    if score.reproducible != "complete":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "not_reproducible",
                "message": "only a score whose run is fully in the cache can be reproduced",
            },
            headers=PRIVATE_CACHE_HEADERS,
        )
    # INVARIANT: exact equality, the same value the board stores. A replay that differs by one ulp
    # is a different result, and the board never rounds it into agreement.
    if (
        body.score != score.score
        or body.total_questions != score.total_questions
        or body.cache_revision != score.cache_revision
    ):
        raise HTTPException(
            status_code=422,
            detail={
                "code": "not_exact",
                "message": "score, total_questions and cache_revision must equal the stored score",
            },
            headers=PRIVATE_CACHE_HEADERS,
        )


@router.post(
    "/scores/{score_id}/reproductions",
    response_model=ReproductionSchema,
    status_code=status.HTTP_201_CREATED,
    responses=RECORD_REPRODUCTION_RESPONSES,
)
async def record_reproduction(
    score_id: UUID,
    body: ReproductionSubmission,
    request: Request,
    response: Response,
    identity: VerifiedIdentity,
) -> ReproductionSchema:
    """Record one exact replay of a `complete` score (E14 B4); any verified identity may.

    The checks run in a fixed order: identity (401/403), the score exists (404), a private board
    that is not the caller's (the same 404), `reproducible` is not `complete` (409
    `not_reproducible`), then the score, total_questions or cache_revision differ from the stored
    row (422 `not_exact`). A run_id this identity already recorded answers 200 with that row; one
    another identity recorded answers 409 `run_id_conflict`.
    """
    # INVARIANT: identity-scoped on every answer: the body names the caller's email, and each
    # refusal depends on who asked. No shared cache may keep any of them.
    response.headers.update(PRIVATE_CACHE_HEADERS)
    score, private = await _load_visible_score(request, score_id, identity)
    _refuse_unless_exact(score, body)
    store = cast(ScoreStore, request.app.state.score_store)
    try:
        outcome = await store.record_reproduction(
            score_id,
            reproduced_by=identity,
            submission=body,
            benchmark_id=cast(str, getattr(score, "benchmark_id")),
            expect_private=private,
        )
    except BenchmarkVisibilityChanged as exc:
        # The board changed between the check above and the locked insert. Nothing is wrong with the
        # request, and a retry sees one consistent view (the same answer as the resubmit path).
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=VISIBILITY_CHANGED_DETAIL,
            headers=PRIVATE_CACHE_HEADERS,
        ) from exc
    except ReproductionRunIdConflict as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "run_id_conflict",
                "message": "this run_id was already recorded for the score; send a new run_id",
            },
            headers=PRIVATE_CACHE_HEADERS,
        ) from exc
    except OperationalError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=STORE_UNAVAILABLE_DETAIL,
        ) from exc
    if outcome is None:
        # Deleted between the read above and the insert.
        raise _score_not_found()
    reproduction, created = outcome
    if not created:
        response.status_code = status.HTTP_200_OK
    return reproduction
