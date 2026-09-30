"""`POST /v1/results/{result_id}/publish` (C10): the owner asks to publish a cache version.

FEATURE: OME-1307 (E14), STORY: as the owner of a result on a public, redistributable board, I
publish its cache version to GitHub so that anyone can replay my run.

INVARIANT (OME-894): a missing result and a private-board result of another caller answer with the
SAME 404 body, so holding a real id is not confirmable.
INVARIANT: the checks run in the fixed order of the plan (4.2). The state changes only in the last
step, so every refusal leaves it as it was.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import cast
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request, Response, status

from scoreboard.core.publish.eligibility import publish_refusal
from scoreboard.core.publish.state import TransitionRejected
from scoreboard.core.replay_access import is_owner
from scoreboard.routes.dependencies import turned_private
from scoreboard.routes.errors import coded_error
from scoreboard.routes.write_identity import WriteIdentity
from scoreboard.scores.models import Benchmark, CacheVersionPublication, ReportedResult, Score
from scoreboard.scores.publication_store import PublicationStore
from scoreboard.scores.schemas import PublishStateResponse

router = APIRouter(prefix="/v1", tags=["publish"])

_NOT_FOUND = "result not found"


@dataclass(frozen=True, slots=True)
class _Loaded:
    result: ReportedResult
    board_id: str
    board_visibility: str | None
    redistributable: bool
    publication: CacheVersionPublication | None


def _unavailable() -> HTTPException:
    return coded_error(
        status.HTTP_503_SERVICE_UNAVAILABLE,
        "publish_unavailable",
        "publishing is not available on this deployment",
    )


async def _load(result_id: UUID) -> _Loaded | None:
    result = await ReportedResult.get_or_none(id=result_id)
    if result is None:
        return None
    head = await Score.get_or_none(id=cast(UUID, getattr(result, "head_id")))
    benchmark = (
        None
        if head is None
        else await Benchmark.get_or_none(id=cast(str, getattr(head, "benchmark_id")))
    )
    if head is None or benchmark is None:
        return None
    publication = await CacheVersionPublication.get_or_none(result_id=result_id)
    return _Loaded(
        result=result,
        board_id=benchmark.id,
        board_visibility=benchmark.visibility,
        redistributable=benchmark.redistributable,
        publication=publication,
    )


def _check_owner(loaded: _Loaded, caller: str) -> None:
    """Steps 3 and 4: a private board hides the result from a non-owner, else 403."""
    if is_owner(caller, loaded.result.reporter, identity_verified=True):
        return
    if loaded.board_visibility != "public":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=_NOT_FOUND)
    raise coded_error(
        status.HTTP_403_FORBIDDEN, "not_result_owner", "only the reporter may publish this result"
    )


def _check_publishable(loaded: _Loaded) -> CacheVersionPublication:
    """Steps 5 and 6: the row must exist, must not be withdrawn, and must pass the rules."""
    publication = loaded.publication
    if publication is None:
        raise _not_publishable("no_cache_version")
    if publication.state == "withdrawn":
        raise _withdrawn()
    reason = publish_refusal(
        board_visibility=loaded.board_visibility,
        redistributable=loaded.redistributable,
        has_version=loaded.result.cache_version_id is not None,
        state=publication.state,
        last_error=publication.last_error,
    )
    if reason is not None:
        raise _not_publishable(reason)
    return publication


def _withdrawn() -> HTTPException:
    return coded_error(
        status.HTTP_409_CONFLICT, "withdrawn", "this publication was withdrawn by an admin"
    )


def _not_publishable(reason: str) -> HTTPException:
    return coded_error(
        status.HTTP_409_CONFLICT,
        "not_publishable",
        "this result cannot be published",
        reason=reason,
    )


@router.post(
    "/results/{result_id}/publish",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=PublishStateResponse,
)
async def publish_result(
    result_id: UUID, request: Request, response: Response, caller: WriteIdentity
) -> PublishStateResponse:
    # WHY `caller is None`: `write_identity` returns None exactly when the auth mode does not
    # verify a caller (the `disabled` dev/local fallback). Publishing is never anonymous (D5).
    if caller is None:
        raise _unavailable()
    loaded = await _load(result_id)
    if loaded is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=_NOT_FOUND)
    _check_owner(loaded, caller)
    publication = _check_publishable(loaded)
    # INVARIANT: the board may have turned private since `_load` read it. Re-check before anything
    # is requested, because the worker will copy this result's cache to a public repository.
    if await turned_private(loaded.board_id):
        raise _not_publishable("private_board")
    state = request.app.state
    if state.release_publisher_factory is None or state.archive_reader is None:
        raise _unavailable()
    store = cast(PublicationStore, state.publication_store)
    try:
        new_state, changed = await store.request_publish(
            result_id, requested_by=caller, now=state.clock()
        )
    except TransitionRejected as exc:
        # An admin withdrew the result between `_load` and the row lock.
        raise _withdrawn() from exc
    if not changed:
        response.status_code = status.HTTP_200_OK
    return PublishStateResponse(
        state=new_state,
        release_url=publication.release_url if new_state == "published" else None,
    )
