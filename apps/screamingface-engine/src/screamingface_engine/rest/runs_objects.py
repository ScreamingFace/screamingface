"""A Run's objects in the run-results store (E5 P2 spec §4.1, D9a, D9b): its context and each
Candidate's result, streamed to the Run's owner.

FEATURE: a detached Run (OME-1837). STORY: as a researcher on a second machine, I build my Run's
Report from the context I sent and each Candidate's result, with nothing saved locally.

INVARIANT (spec D9a): a result is read only from the key built from the Run's id, the Candidate's
index and the checksum in its record, so no request names a key of its own.
"""

from __future__ import annotations

import asyncio
import re
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Path, Request, Response

from screamingface_engine.artifacts.ports import ArtifactContent
from screamingface_engine.artifacts.run_results import (
    RunResultStore,
    context_key,
    result_key,
    result_prefix,
)
from screamingface_engine.auth import ProblemException
from screamingface_engine.rest.artifacts import content_response
from screamingface_engine.rest.runs_boundary import (
    PRIVATE_HEADERS,
    PRIVATE_HEADERS_DOC,
    RunsRoute,
    private_answer,
    private_problems,
    problem,
    request_owner,
    request_registry,
    result_store_unavailable,
    run_not_found,
)
from screamingface_engine.runs.ids import RUN_ID_PATTERN
from screamingface_engine.runs.records import MAX_CANDIDATES

CONTEXT_NOT_FOUND = "context_not_found"
RESULT_NOT_FOUND = "result_not_found"
_CONTEXT_MEDIA_TYPE = "text/plain; charset=utf-8"
_OCTETS = "application/octet-stream"
# A media type as a runner records it. WHY checked: it becomes a response header, so anything
# else (a control character, say) is served as plain bytes instead.
_MEDIA_TYPE = re.compile(r"[\w.+-]{1,64}/[\w.+-]{1,64}(?:; ?[\w.+-]+=[\w.+\"-]{1,64}){0,3}")

router = APIRouter(
    prefix="/runs",
    tags=["Runs"],
    route_class=RunsRoute,
    dependencies=[Depends(private_answer)],
    responses=private_problems(
        {
            401: "A hosted call with no verified identity (`identity_required`).",
            404: "No such Run of the caller's (`run_not_found`), or Runs are off (`runs_off`).",
            503: "The run-results store could not answer (`result_store_unavailable`); retry.",
        }
    ),
)


def _not_found(detail: str, code: str) -> ProblemException:
    return problem(status=404, title="Not Found", detail=detail, code=code)


async def _open(request: Request, key: str) -> ArtifactContent | None:
    store: RunResultStore | None = getattr(request.app.state, "run_results", None)
    if store is None:
        return None
    try:
        return await asyncio.to_thread(store.open, key)
    except Exception as exc:
        raise result_store_unavailable(exc) from None


def _result_of(run_id: str, index: int, record: Any) -> tuple[str, str] | None:
    """The key and media type of the result a Candidate's record names, if it names one."""
    result = record.get("result") if isinstance(record, dict) else None
    if not isinstance(result, dict) or not isinstance(result.get("sha256"), str):
        return None
    try:
        key = result_key(result_prefix(run_id, index), result["sha256"])
    except ValueError:
        return None
    media_type = result.get("media_type")
    if not isinstance(media_type, str) or _MEDIA_TYPE.fullmatch(media_type) is None:
        media_type = _OCTETS
    return key, media_type


@router.get(
    "/{run_id}/context",
    summary="Read a Run's context",
    response_class=Response,
    responses={
        200: {
            "description": "The context as it was sent; its sha256 is the Run's `context`.",
            "content": {_CONTEXT_MEDIA_TYPE: {}},
            "headers": PRIVATE_HEADERS_DOC,
        },
        **private_problems({404: "The Run has no context, or no longer (`context_not_found`)."}),
    },
)
async def get_context(request: Request, run_id: str) -> Response:
    registry = request_registry(request)
    owner = request_owner(request)
    run = await registry.summary(owner, run_id) if RUN_ID_PATTERN.fullmatch(run_id) else None
    if run is None:
        raise run_not_found(run_id)
    content = None if run.context is None else await _open(request, context_key(run_id))
    if content is None:
        raise _not_found("this Run has no context to serve", CONTEXT_NOT_FOUND)
    return content_response(content, _CONTEXT_MEDIA_TYPE, PRIVATE_HEADERS)


@router.get(
    "/{run_id}/candidates/{index}/result",
    summary="Read a Candidate's result",
    response_class=Response,
    responses={
        200: {
            "description": "The result's bytes, with the media type its record names.",
            "content": {_OCTETS: {}},
            "headers": PRIVATE_HEADERS_DOC,
        },
        **private_problems(
            {
                404: "The Candidate has not ended, has no result, or its result is past "
                "retention (`result_not_found`).",
                422: "An invalid index (`invalid_request`).",
            }
        ),
    },
)
async def get_result(
    request: Request,
    run_id: str,
    index: Annotated[int, Path(ge=0, lt=MAX_CANDIDATES)],
) -> Response:
    registry = request_registry(request)
    owner = request_owner(request)
    records = (
        await registry.records(owner, run_id, [index]) if RUN_ID_PATTERN.fullmatch(run_id) else None
    )
    if records is None:
        raise run_not_found(run_id)
    named = _result_of(run_id, index, records.get(index))
    content = None if named is None else await _open(request, named[0])
    if named is None or content is None:
        raise _not_found(f"Candidate {index} of this Run has no result", RESULT_NOT_FOUND)
    return content_response(content, named[1], PRIVATE_HEADERS)


__all__ = ["router"]
