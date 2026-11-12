"""`/runs`: register, list, read and cancel a Run (E5 P1 spec §4.1, D6, D12). Binding a start to
its Run's Candidate (R2) is `rest.runs_start`; the shared boundary is `rest.runs_boundary`.

FEATURE: first-class Runs (OME-1785). STORY: as a researcher, I open last week's evaluation from
another notebook and see each Candidate's state and cost, or cancel one still running.

INVARIANT (spec D5, §4.1): a foreign id reads exactly like an unknown one, 404 `run_not_found`,
and no answer carries the owner.
"""

from __future__ import annotations

import logging
from datetime import datetime
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, ConfigDict, PlainSerializer, StrictInt

from screamingface_engine.rest.gateway_route import problem_responses
from screamingface_engine.rest.runs_boundary import (
    CLIENT_KEY_CONFLICT,
    INVALID_CURSOR,
    PRIVATE_HEADERS,
    PRIVATE_HEADERS_DOC,
    RunsRoute,
    invalid_value,
    private_answer,
    private_failure,
    private_problems,
    problem,
    request_owner,
    request_registry,
    run_not_found,
    stop_candidate,
)
from screamingface_engine.runs.ids import RUN_ID_PATTERN
from screamingface_engine.runs.records import (
    CandidateState,
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


# --- the wire ----------------------------------------------------------------------------


class RunCreate(BaseModel):
    # WHY forbid: a field this Engine does not know is refused, not silently dropped.
    model_config = ConfigDict(extra="forbid")

    client_key: str
    benchmark: str
    case_count: StrictInt
    candidates: list[str]
    client_version: str


def _cost_text(cost: Decimal | None) -> str | None:
    """A cost in plain positional form, without trailing zeros. WHY: Postgres returns a `NUMERIC`
    at its column's full scale and SQLite does not, so one cost would read `0.5` on one database
    and `0.500000000000` on the other; and `str()` would write a tiny cost as `1E-12`."""
    return None if cost is None else f"{cost.normalize():f}"


class CandidateBody(BaseModel):
    name: str
    state: CandidateState
    attempt_id: str | None
    started_at: datetime | None
    finished_at: datetime | None
    # Exact: a decimal string, as cost travels everywhere else on the wire.
    cost_usd: Annotated[Decimal | None, PlainSerializer(_cost_text, return_type=str | None)]
    error_code: str | None


class RunBody(BaseModel):
    id: str
    state: RunState
    created_at: datetime
    finished_at: datetime | None
    benchmark: str
    case_count: int
    candidates: list[CandidateBody]

    @classmethod
    def of(cls, record: RunRecord) -> RunBody:
        return cls(
            id=record.id,
            state=record.state,
            created_at=record.created_at,
            finished_at=record.finished_at,
            benchmark=record.benchmark,
            case_count=record.case_count,
            candidates=[
                CandidateBody(
                    name=c.name,
                    state=c.state,
                    attempt_id=c.attempt_id,
                    started_at=c.started_at,
                    finished_at=c.finished_at,
                    cost_usd=c.cost_usd,
                    error_code=c.error_code,
                )
                for c in record.candidates
            ],
        )


class RunList(BaseModel):
    runs: list[RunBody]
    next_cursor: str | None


async def _read(registry: RunRegistry, owner: OwnerKey, run_id: str) -> RunRecord:
    record = await registry.get(owner, run_id) if RUN_ID_PATTERN.fullmatch(run_id) else None
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
    responses={
        201: {"description": "The new Run.", "headers": PRIVATE_HEADERS_DOC},
        200: {
            "description": "The caller's Run with this `client_key`, already registered.",
            "model": RunBody,
            "headers": PRIVATE_HEADERS_DOC,
        },
        **private_problems(
            {
                409: "That `client_key` names another evaluation (`client_key_conflict`).",
                422: "An invalid Run.",
            }
        ),
    },
)
async def create_run(request: Request, response: Response, body: RunCreate) -> RunBody:
    """201 with the new Run, or 200 with the caller's Run of the same `client_key`; 409
    `client_key_conflict` when that Run names another evaluation."""
    registry = request_registry(request)
    owner = request_owner(request)
    try:
        spec = RunSpec(
            client_key=body.client_key,
            benchmark=body.benchmark,
            case_count=body.case_count,
            candidates=tuple(body.candidates),
            client_version=body.client_version,
        )
    except ValueError as exc:
        raise invalid_value(exc) from exc
    try:
        record, created = await registry.register(owner, spec)
    except ClientKeyConflict as exc:
        raise problem(
            status=409, title="Conflict", detail=str(exc), code=CLIENT_KEY_CONFLICT
        ) from exc
    if not created:
        response.status_code = 200
    return RunBody.of(record)


@router.get(
    "",
    summary="List Runs, newest first",
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
    responses={200: {"description": "The Run.", "headers": PRIVATE_HEADERS_DOC}},
)
async def get_run(request: Request, run_id: str) -> RunBody:
    registry = request_registry(request)
    return RunBody.of(await _read(registry, request_owner(request), run_id))


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
    record = await _read(registry, owner, run_id)
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
