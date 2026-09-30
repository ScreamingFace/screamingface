"""Edit the metadata of a submission: authors and paper URL (E14a, OME-1307).

FEATURE: OME-1307 (E14a) — `PATCH /v1/scores/{id}` lets the owner of a submission add authors and
a paper link after submit, and `GET /v1/scores/{id}/metadata-history` lists the edits. This module
is the inbound adapter: every FastAPI concern lives here, every Tortoise one in
`scores/metadata_store.py`.

INVARIANT (D5): production runs `cloudflare_headers`, so the owner check and the event `actor` use
the verified `X-User-Email` (`WriteIdentity`). `disabled` is a dev/local fallback only.
"""

from __future__ import annotations

import logging
import re
from typing import Annotated, Any, cast
from uuid import UUID

from fastapi import APIRouter, Body, Header, Query, Request, Response, status
from pydantic import ValidationError
from tortoise.exceptions import OperationalError

from scoreboard.routes.dependencies import PRIVATE_CACHE_HEADERS, ReadIdentity, turned_private
from scoreboard.routes.errors import UNPROCESSABLE, coded_error, score_not_found, store_unavailable
from scoreboard.routes.write_identity import WriteIdentity
from scoreboard.scores.metadata_store import (
    MetadataRevisionConflict,
    NotSubmissionOwner,
    ScoreMetadataStore,
    ScoreNotFound,
)
from scoreboard.scores.schemas import (
    CodedErrorResponse,
    MessageErrorResponse,
    MetadataHistoryResponse,
    ScoreMetadataPatch,
    ScoreSchema,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1", tags=["scores"])

_EDITABLE_FIELDS = frozenset(ScoreMetadataPatch.model_fields)
# A strong ETag of the revision, as the API sends it: `"3"`. Revisions start at 1.
_IF_MATCH_PATTERN = re.compile(r'^"([1-9][0-9]{0,9})"$')
_CURSOR_PATTERN = re.compile(r"^[1-9][0-9]{0,9}$")
# WHY 0: revisions start at 1, so 0 never matches a stored row. A value the route cannot parse is
# passed to the store as 0 and comes back as a 412 with the current state, except for the MD-D4
# resend of equal values, which the store answers 200 before it checks the revision.
_NEVER_A_REVISION = 0

PATCH_METADATA_RESPONSES: dict[int | str, dict[str, Any]] = {
    status.HTTP_401_UNAUTHORIZED: {
        "model": CodedErrorResponse,
        "description": "identity_not_verified: no X-User-Email (cloudflare_headers mode).",
    },
    status.HTTP_403_FORBIDDEN: {
        "model": CodedErrorResponse,
        "description": "not_submission_owner, or an untrusted peer network.",
    },
    status.HTTP_404_NOT_FOUND: {
        "model": MessageErrorResponse,
        "description": "Score not found, or private and not yours.",
    },
    status.HTTP_412_PRECONDITION_FAILED: {
        "model": CodedErrorResponse,
        "description": "metadata_revision_conflict: the body holds the current state.",
    },
    UNPROCESSABLE: {
        "model": CodedErrorResponse,
        "description": "field_not_editable or invalid_metadata.",
    },
    status.HTTP_428_PRECONDITION_REQUIRED: {
        "model": CodedErrorResponse,
        "description": "precondition_required: If-Match is missing, blank or `*`.",
    },
    status.HTTP_503_SERVICE_UNAVAILABLE: {
        "model": MessageErrorResponse,
        "description": "Score store unavailable.",
    },
}

METADATA_HISTORY_RESPONSES: dict[int | str, dict[str, Any]] = {
    status.HTTP_404_NOT_FOUND: PATCH_METADATA_RESPONSES[status.HTTP_404_NOT_FOUND],
    UNPROCESSABLE: {
        "model": CodedErrorResponse,
        "description": "invalid_cursor.",
    },
    status.HTTP_503_SERVICE_UNAVAILABLE: PATCH_METADATA_RESPONSES[
        status.HTTP_503_SERVICE_UNAVAILABLE
    ],
}


def _expected_revision(if_match: str | None) -> int:
    if if_match is None or if_match.strip() in ("", "*"):
        raise coded_error(
            status.HTTP_428_PRECONDITION_REQUIRED,
            "precondition_required",
            'send If-Match with the metadata_revision you read, for example If-Match: "1"',
        )
    matched = _IF_MATCH_PATTERN.match(if_match)
    return int(matched.group(1)) if matched else _NEVER_A_REVISION


def _parse_patch(payload: dict[str, Any]) -> ScoreMetadataPatch:
    extra = sorted(set(payload) - _EDITABLE_FIELDS)
    if extra:
        raise coded_error(
            UNPROCESSABLE,
            "field_not_editable",
            "only authors and paper_url can be edited",
            fields=extra,
        )
    try:
        return ScoreMetadataPatch.model_validate(payload)
    except ValidationError as exc:
        raise coded_error(
            UNPROCESSABLE,
            "invalid_metadata",
            "authors or paper_url is not valid",
            errors=[
                {
                    "field": str(error["loc"][0]),
                    "message": error["msg"].removeprefix("Value error, "),
                }
                for error in exc.errors()
            ],
        ) from exc


def _conflict_detail(current: ScoreSchema) -> dict[str, Any]:
    published = current.model_dump(mode="json")
    return {
        "metadata_revision": published["metadata_revision"],
        "authors": published["authors"],
        "paper_url": published.get("paper_url"),
    }


@router.patch("/scores/{score_id}", response_model=ScoreSchema, responses=PATCH_METADATA_RESPONSES)
async def update_score_metadata(
    score_id: UUID,
    request: Request,
    response: Response,
    editor: WriteIdentity,
    payload: Annotated[dict[str, Any], Body()],
    if_match: Annotated[str | None, Header(alias="If-Match")] = None,
) -> ScoreSchema:
    """Edit `authors` and/or `paper_url` of a submission you own. Send `If-Match: "<revision>"`.

    A key you omit is untouched; an explicit `null` clears it (`authors: null` falls back to the
    submitter). A resend of values that already hold is a `200` with the current state.
    """
    # Order of checks: identity (the `editor` dependency, before the body), If-Match, keys, values.
    # None of them needs the database.
    expected_revision = _expected_revision(if_match)
    patch = _parse_patch(payload)
    changes = {key: getattr(patch, key) for key in patch.model_fields_set}
    store = cast(ScoreMetadataStore, request.app.state.metadata_store)
    try:
        outcome = await store.update_metadata(
            score_id, changes=changes, expected_revision=expected_revision, editor=editor
        )
    except ScoreNotFound as exc:
        raise score_not_found() from exc
    except NotSubmissionOwner as exc:
        raise coded_error(
            status.HTTP_403_FORBIDDEN,
            "not_submission_owner",
            "only the submitter of this score can edit its metadata",
        ) from exc
    except MetadataRevisionConflict as exc:
        raise coded_error(
            status.HTTP_412_PRECONDITION_FAILED,
            "metadata_revision_conflict",
            "the metadata changed since you read it; re-read and retry",
            current=_conflict_detail(exc.current),
        ) from exc
    except OperationalError as exc:
        raise store_unavailable() from exc
    if outcome.changed:
        # INVARIANT (PRD §4): counts only. An author list is PII and an email is never logged.
        logger.info(
            "score metadata edited",
            extra={
                "score_id": str(score_id),
                "actor_is_owner": True,
                "author_count": len(outcome.score.authors or []),
            },
        )
    response.headers["ETag"] = f'"{outcome.score.metadata_revision}"'
    return outcome.score


@router.get(
    "/scores/{score_id}/metadata-history",
    response_model=MetadataHistoryResponse,
    responses=METADATA_HISTORY_RESPONSES,
)
async def score_metadata_history(
    score_id: UUID,
    request: Request,
    response: Response,
    identity: ReadIdentity,
    cursor: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=50)] = 50,
) -> MetadataHistoryResponse:
    """The edits of a submission's metadata, newest first, 50 to a page.

    Readable like `GET /v1/scores/{id}`: anyone for a public board, only the owner for a private
    one. `next_cursor` is the `to_revision` of the last event; pass it back as `cursor`.
    """
    if cursor is not None and not _CURSOR_PATTERN.match(cursor):
        raise coded_error(
            UNPROCESSABLE,
            "invalid_cursor",
            "cursor must be the next_cursor of a previous page",
        )
    store = cast(ScoreMetadataStore, request.app.state.metadata_store)
    try:
        page = await store.metadata_history(
            score_id,
            reader=identity,
            before_revision=None if cursor is None else int(cursor),
            limit=limit,
        )
        # INVARIANT (OME-894): the store decided from a visibility read and then queried the
        # events, and the seed job can flip a board in between. Same rule as `get_score`: a private
        # answer is marked private, a public one is re-checked, and this is the last await before
        # the response.
        if page.private:
            response.headers.update(PRIVATE_CACHE_HEADERS)
        elif await turned_private(page.benchmark_id):
            raise score_not_found()
    except ScoreNotFound as exc:
        raise score_not_found() from exc
    except OperationalError as exc:
        raise store_unavailable() from exc
    return MetadataHistoryResponse(
        events=page.events,
        next_cursor=None if page.next_revision is None else str(page.next_revision),
    )
