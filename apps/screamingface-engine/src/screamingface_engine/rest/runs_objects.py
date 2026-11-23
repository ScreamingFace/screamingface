"""A Run's objects in the run-results store (E5 P2 spec §4.1, D9a, D9b): its context and each
Candidate's result, streamed to the Run's owner.

FEATURE: a detached Run (OME-1837). STORY: as a researcher on a second machine, I build my Run's
Report from the context I sent and each Candidate's result, with nothing saved locally.

INVARIANT (spec D9a): a result is read only from the key built from the Run's id, the Candidate's
index and the checksum in its record, so no request names a key of its own.
"""

from __future__ import annotations

import asyncio
import logging
import re
from collections.abc import AsyncIterator
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Path, Request, Response

from screamingface_engine.artifacts.ports import ArtifactContent, LocalFile, RemoteStream
from screamingface_engine.artifacts.run_results import (
    RunResultStore,
    context_key,
    recorded_result_key,
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

_logger = logging.getLogger(__name__)
CONTEXT_NOT_FOUND = "context_not_found"
RESULT_NOT_FOUND = "result_not_found"
_CONTEXT_MEDIA_TYPE = "text/plain; charset=utf-8"
_OCTETS = "application/octet-stream"
# A media type as a runner records it. WHY checked: it becomes a response header, so anything
# else (a control character, say) is served as plain bytes instead. WHY ASCII: a header is
# latin-1, and `\w` alone admits letters it cannot encode.
_MEDIA_TYPE = re.compile(
    r"[\w.+-]{1,64}/[\w.+-]{1,64}(?:; ?[\w.+-]+=[\w.+\"-]{1,64}){0,3}", re.ASCII
)

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


def _result_of(run_id: str, index: int, record: Any) -> tuple[str, str, int] | None:
    """The key, media type and size of the result a Candidate's record names, if it names one
    with a size."""
    key = recorded_result_key(run_id, index, record)
    if key is None:
        return None
    size = record["result"].get("size_bytes")
    if not isinstance(size, int) or isinstance(size, bool) or size < 0:
        return None
    media_type = record["result"].get("media_type")
    if not isinstance(media_type, str) or _MEDIA_TYPE.fullmatch(media_type) is None:
        media_type = _OCTETS
    return key, media_type, size


def _as_recorded(content: ArtifactContent, size: int, what: str) -> ArtifactContent | None:
    """``content`` if it is the ``size`` bytes the Run recorded, its stream cut at that size;
    else None, and the object ``what`` names is served as absent, with a warning.

    WHY (#1759 review): the store's own length is the object's, so an object damaged or replaced
    in the store would be served past the size the Run bounds. The Client checks the checksum.
    The warning tells a damaged object from one past retention, which both answer 404.
    """
    found: int | None
    if isinstance(content, LocalFile):
        try:
            found = content.path.stat().st_size
        except OSError:
            found = None  # gone since it was opened: absent, with nothing to warn of
    else:
        found = content.size_bytes
    if found != size:
        if found is not None:
            _logger.warning(
                "The stored %s is %d bytes, not the %d its Run recorded; it is served as absent",
                what,
                found,
                size,
            )
        return None
    if isinstance(content, LocalFile):
        return content
    return RemoteStream(_at_most(content.stream, size), size)


async def _at_most(stream: AsyncIterator[bytes], size: int) -> AsyncIterator[bytes]:
    """``stream`` cut at ``size`` bytes. WHY: an object replaced between the read of its length
    and its body must not send more than its `Content-Length` says."""
    left = size
    try:
        async for chunk in stream:
            if len(chunk) >= left:
                if left:
                    yield chunk[:left]
                return
            left -= len(chunk)
            yield chunk
    finally:
        close = getattr(stream, "aclose", None)
        if close is not None:
            await close()


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
    if content is not None and run.context is not None:
        content = _as_recorded(content, run.context.size_bytes, f"context of Run {run_id}")
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
    if named is not None and content is not None:
        content = _as_recorded(content, named[2], f"result of Candidate {index} of Run {run_id}")
    if named is None or content is None:
        raise _not_found(f"Candidate {index} of this Run has no result", RESULT_NOT_FOUND)
    return content_response(content, named[1], PRIVATE_HEADERS)


__all__ = ["router"]
