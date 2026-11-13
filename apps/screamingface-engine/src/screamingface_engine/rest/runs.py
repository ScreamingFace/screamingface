"""`/runs`: register, list, read and cancel a Run (E5 P1 spec §4.1, D6, D12; E5 P2 spec §4.1).
A Run's context and results are `rest.runs_objects`, its event stream `rest.runs_events`; the
shared boundary is `rest.runs_boundary` and the wire `rest.runs_wire`. The App's driver starts
a Run's Candidates (`runs.driver`).

FEATURE: first-class Runs (OME-1785) and a detached Run (OME-1837). STORY: as a researcher, I
send my evaluation once and leave, then open it from another notebook and see each Candidate's
state and cost, or cancel one still running.

INVARIANT (spec D5, §4.1): a foreign id reads exactly like an unknown one, 404 `run_not_found`,
and no answer carries the owner or the owner's email.
"""

from __future__ import annotations

import asyncio
import dataclasses
import hashlib
import logging
from datetime import datetime, timedelta
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Request, Response

from screamingface_engine.artifacts.run_results import RunResultStore, context_key
from screamingface_engine.auth import ProblemException
from screamingface_engine.rest.gateway_route import problem_responses
from screamingface_engine.rest.runs_boundary import (
    CLIENT_KEY_CONFLICT,
    INVALID_CURSOR,
    INVALID_REQUEST,
    PRIVATE_HEADERS,
    PRIVATE_HEADERS_DOC,
    RunsRoute,
    invalid_value,
    private_answer,
    private_failure,
    private_problems,
    problem,
    request_email,
    request_owner,
    request_registry,
    result_store_unavailable,
    run_not_found,
    stop_candidate,
)
from screamingface_engine.rest.runs_wire import RunBody, RunCreate, RunList
from screamingface_engine.rest.selector import X_PROFILE_PARAMETER
from screamingface_engine.runs.ids import RUN_ID_PATTERN, new_run_id
from screamingface_engine.runs.records import (
    ContextRef,
    OwnerKey,
    RunQuery,
    RunRecord,
    RunSpec,
    RunState,
    is_terminal_candidate,
)
from screamingface_engine.runs.registry import (
    ClientKeyConflict,
    InvalidCursor,
    RunRegistry,
)
from screamingface_engine.runs.stopping import make_stops

DEADLINE_TOO_LONG = "deadline_too_long"
DEADLINE_NEEDS_DETACH = "deadline_needs_detach"
CONTEXT_TOO_LARGE = "context_too_large"

_logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/runs",
    tags=["Runs"],
    route_class=RunsRoute,
    dependencies=[Depends(private_answer)],
    responses=private_problems(
        {
            400: "The request body could not be read as JSON (`malformed_body`).",
            401: "A hosted call with no verified identity (`identity_required`).",
            422: "The request does not validate: its body, path or query.",
            404: "No such Run of the caller's (`run_not_found`), or Runs are off on this Engine.",
            500: "An unexpected failure; retrying will not help.",
            503: "The Run registry could not answer; retry after `Retry-After`.",
        }
    ),
)


# --- registering a Run (E5 P2 spec §4.1) -----------------------------------------------------


def _unprocessable(detail: str, code: str) -> ProblemException:
    return problem(status=422, title="Unprocessable Content", detail=detail, code=code)


def _spec(request: Request, body: RunCreate) -> RunSpec:
    """The Run to register, its id minted here so its context can be stored under it first."""
    settings = request.app.state.settings
    if body.deadline_s is not None:
        if not body.detach:
            raise _unprocessable("a deadline needs detach", DEADLINE_NEEDS_DETACH)
        if body.deadline_s > settings.run_detached_deadline_max_s:
            limit = int(settings.run_detached_deadline_max_s)
            raise _unprocessable(f"a deadline is at most {limit} s", DEADLINE_TOO_LONG)
        # WHY here: a `timedelta` cannot hold every integer, so it is bounded before one is built.
        if body.deadline_s <= 0:
            raise _unprocessable("a deadline must be positive", INVALID_REQUEST)
    return RunSpec(
        client_key=body.client_key,
        benchmark=body.benchmark,
        case_count=body.case_count,
        candidates=tuple(c.name for c in body.candidates),
        client_version=body.client_version,
        starts=tuple(c.to_start() for c in body.candidates),
        detach=body.detach,
        deadline=None if body.deadline_s is None else timedelta(seconds=body.deadline_s),
        run_id=new_run_id(),
        owner_email=request_email(request),
    )


def _context_bytes(request: Request, context: str) -> bytes:
    try:
        data = context.encode()
    except UnicodeEncodeError:
        # A lone surrogate, which JSON can escape and UTF-8 cannot hold.
        raise _unprocessable("the context is not valid text", INVALID_REQUEST) from None
    limit = request.app.state.settings.run_context_max_bytes
    if len(data) > limit:
        raise _unprocessable(f"the context is over {limit} bytes", CONTEXT_TOO_LARGE)
    return data


async def _store_context(request: Request, key: str, data: bytes) -> ContextRef:
    """Write the context before its Run exists (spec D9b): a Run is never registered without
    the context it names. A store that is missing or refuses answers 503, and nothing is
    registered."""
    store: RunResultStore | None = getattr(request.app.state, "run_results", None)
    if store is None:
        raise result_store_unavailable(None)
    try:
        await asyncio.to_thread(store.put, key, data)
    except Exception as exc:
        raise result_store_unavailable(exc) from None
    return ContextRef(hashlib.sha256(data).hexdigest(), len(data))


async def _drop_context(request: Request, key: str) -> None:
    """Delete a context written for a Run that was not registered. Best effort: what is left is
    removed by age with the rest of what no Run names (spec R13)."""
    store: RunResultStore | None = getattr(request.app.state, "run_results", None)
    if store is None:
        return
    try:
        await asyncio.to_thread(store.delete, [key])
    except Exception:
        _logger.warning("could not delete an unregistered Run's context; age removes it")


async def _register(
    request: Request, registry: RunRegistry, owner: OwnerKey, spec: RunSpec, context: str | None
) -> tuple[RunRecord, bool]:
    if context is None:
        return await registry.register(owner, spec)
    assert spec.run_id is not None
    key = context_key(spec.run_id)
    data = _context_bytes(request, context)
    ref = await _store_context(request, key, data)
    try:
        record, created = await registry.register(owner, dataclasses.replace(spec, context=ref))
    except BaseException:
        # WHY ask: a register that failed may still have committed (its answer was lost), and
        # that Run names this context. It is deleted only when no such Run exists.
        if await _unregistered(registry, owner, spec.run_id):
            await _drop_context(request, key)
        raise
    # INVARIANT: a context is kept only under a Run that names it. A repeated `client_key`
    # finds the first Run, which keeps its own.
    if not created:
        await _drop_context(request, key)
    return record, created


async def _unregistered(registry: RunRegistry, owner: OwnerKey, run_id: str) -> bool:
    """Whether the registry says no such Run exists. False when it cannot say: the context
    then stays, and age removes it if nothing names it (spec R13)."""
    try:
        return await registry.summary(owner, run_id) is None
    except Exception:
        return False


async def _read(
    registry: RunRegistry, owner: OwnerKey, run_id: str, *, full: bool = True
) -> RunRecord:
    read = registry.get if full else registry.summary
    record = await read(owner, run_id) if RUN_ID_PATTERN.fullmatch(run_id) else None
    if record is None:
        raise run_not_found(run_id)
    return record


async def _stop_owed(request: Request, registry: RunRegistry, owner: OwnerKey, run_id: str) -> None:
    """Stop every owed topic, `STOP_CONCURRENCY` at a time, and clear each obligation once its
    stop succeeded (spec D12). Every stop is tried even when one fails; a failure whose topic is
    still owed is then raised as a private 503, and a retried cancel stops what is still owed."""
    topics = await registry.owed_stops(owner, run_id)
    failed = await make_stops(registry, lambda topic: stop_candidate(request, topic), topics)
    if not failed:
        return
    # WHY recheck: a concurrent cancel may have completed the same stop, so this one's failure
    # leaves nothing owed and is not the caller's to retry.
    try:
        still_owed = set(await registry.owed_stops(owner, run_id))
    except Exception:
        still_owed = {topic for topic, _ in failed}
    for topic, result in failed:
        if topic in still_owed:
            raise private_failure(result) from result


# --- the routes --------------------------------------------------------------------------


@router.post(
    "",
    status_code=201,
    summary="Register a Run",
    response_model_exclude_unset=True,
    responses={
        201: {"description": "The new Run.", "headers": PRIVATE_HEADERS_DOC},
        200: {
            "description": "The caller's Run with this `client_key`, already registered.",
            "model": RunBody,
            "headers": PRIVATE_HEADERS_DOC,
        },
        **private_problems(
            {
                400: "A stated `X-Profile` (`x_profile_unsupported`); no Run was registered.",
                409: "That `client_key` names another evaluation (`client_key_conflict`).",
                413: "The body is over `run_request_max_bytes` (`request_too_large`).",
                422: "An invalid Run (`invalid_request`), a deadline past the cap "
                "(`deadline_too_long`) or without `detach` (`deadline_needs_detach`), or a "
                "context over `run_context_max_bytes` (`context_too_large`).",
                503: "The context could not be stored (`result_store_unavailable`), or the Run "
                "registry could not answer; no Run was registered. Retry after `Retry-After`.",
            }
        ),
    },
)
async def create_run(
    request: Request,
    response: Response,
    body: RunCreate,
    # Documents the refusal in OpenAPI; `RunsRoute` is what decides.
    _x_profile: Annotated[str | None, X_PROFILE_PARAMETER] = None,
) -> RunBody:
    """201 with the new Run, or 200 with the caller's Run of the same `client_key`; 409
    `client_key_conflict` when that Run names another evaluation."""
    registry = request_registry(request)
    owner = request_owner(request)
    try:
        spec = _spec(request, body)
    except ValueError as exc:
        raise invalid_value(exc) from exc
    try:
        record, created = await _register(request, registry, owner, spec, body.context)
    except ClientKeyConflict as exc:
        raise problem(
            status=409, title="Conflict", detail=str(exc), code=CLIENT_KEY_CONFLICT
        ) from exc
    if not created:
        response.status_code = 200
    else:
        # R1: the driver ticks now rather than at its next interval.
        drivers = getattr(request.app.state, "run_drivers", None)
        if drivers is not None:
            drivers.wake()
    return RunBody.of(record)


@router.get(
    "",
    summary="List Runs, newest first",
    response_model_exclude_unset=True,
    responses={
        200: {"description": "A page of the caller's Runs.", "headers": PRIVATE_HEADERS_DOC},
        **private_problems(
            {422: "An invalid query, or a cursor that names no Run of yours (`invalid_cursor`)."}
        ),
    },
)
async def list_runs(
    request: Request,
    state: RunState | None = None,
    since: datetime | None = None,
    limit: int = 50,
    cursor: str | None = None,
) -> RunList:
    registry = request_registry(request)
    owner = request_owner(request)
    try:
        query = RunQuery(state=state, since=since, limit=limit, cursor=cursor)
    except ValueError as exc:
        raise invalid_value(exc) from exc
    try:
        page = await registry.list(owner, query)
    except InvalidCursor as exc:
        raise problem(
            status=422,
            title="Unprocessable Content",
            detail=f"the cursor {exc} names no run of yours",
            code=INVALID_CURSOR,
        ) from exc
    return RunList(runs=[RunBody.of(r) for r in page.runs], next_cursor=page.next_cursor)


@router.get(
    "/{run_id}",
    summary="Read a Run",
    response_model_exclude_unset=True,
    responses={
        200: {
            "description": "The Run, with each Candidate's `start` and `record`; with "
            "`view=summary`, without them.",
            "headers": PRIVATE_HEADERS_DOC,
        }
    },
)
async def get_run(request: Request, run_id: str, view: Literal["summary"] | None = None) -> RunBody:
    registry = request_registry(request)
    owner = request_owner(request)
    if view == "summary":
        return RunBody.of(await _read(registry, owner, run_id, full=False))
    return RunBody.of(await _read(registry, owner, run_id), full=True)


@router.delete(
    "/{run_id}",
    status_code=202,
    summary="Cancel a Run",
    # No body on either success: the answer is the status.
    response_class=Response,
    responses={
        202: {
            "description": "Canceled; its live Candidates were stopped.",
            "headers": PRIVATE_HEADERS_DOC,
        },
        204: {
            "description": "Every Candidate had already ended; nothing changed.",
            "headers": PRIVATE_HEADERS_DOC,
        },
        503: {
            **problem_responses({503: "The run queue could not be read; retry."})[503],
            "headers": {"Retry-After": {"schema": {"type": "integer"}}, **PRIVATE_HEADERS_DOC},
        },
    },
)
async def cancel_run(request: Request, run_id: str) -> Response:
    """Spec D12: 202 while any Candidate is not terminal, after stopping every live topic; 204,
    changing nothing, once every Candidate is terminal."""
    registry = request_registry(request)
    owner = request_owner(request)
    record = await _read(registry, owner, run_id, full=False)
    changed = False
    if not all(is_terminal_candidate(c.state) for c in record.candidates):
        canceled = await registry.cancel(owner, run_id)
        if canceled is None:
            raise run_not_found(run_id)
        # The cancel changed something only if it flagged the Run: the last outcome may have
        # landed first, and a retried cancel finds the flag already set.
        changed = canceled.canceled and not record.canceled
        record = canceled
    # WHY owed and not derived from state: a stop that failed leaves its Candidate `stopped`
    # (or still running), and only the stored obligation tells it from one that ended on its own.
    await _stop_owed(request, registry, owner, run_id)
    if changed or not all(is_terminal_candidate(c.state) for c in record.candidates):
        return Response(status_code=202, headers=PRIVATE_HEADERS)
    return Response(status_code=204, headers=PRIVATE_HEADERS)


__all__ = ["router"]
