"""`/runs`: register, list, read and cancel a Run (E5 P1 spec §4.1, D6, D12), and bind a start to
its Run's Candidate (R2).

FEATURE: first-class Runs (OME-1785). STORY: as a researcher, I open last week's evaluation from
another notebook and see each Candidate's state and cost, or cancel one still running.

INVARIANT (spec D5, §4.1): a foreign id reads exactly like an unknown one, 404 `run_not_found`,
and no answer carries the owner.
"""

from __future__ import annotations

import asyncio
import functools
import logging
from collections.abc import Awaitable, Callable
from datetime import datetime
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, ConfigDict, PlainSerializer, StrictInt

from screamingface_engine import job_env
from screamingface_engine.auth import ProblemException
from screamingface_engine.rest.stopping import stop_topic
from screamingface_engine.runs.ids import RUN_ID_PATTERN
from screamingface_engine.runs.records import (
    CandidateState,
    OwnerKey,
    RunQuery,
    RunRecord,
    RunSpec,
    RunState,
    is_terminal_candidate,
    owner_key,
)
from screamingface_engine.runs.registry import (
    CandidateAlreadyStarted,
    ClientKeyConflict,
    InvalidCursor,
    RunCanceled,
    RunNotFound,
    RunRegistry,
    UnknownCandidate,
)
from screamingface_engine.world.wire import MALFORMED_HEADER

_logger = logging.getLogger(__name__)

RUN_NOT_FOUND = "run_not_found"
RUN_CANCELED = "run_canceled"
CANDIDATE_ALREADY_STARTED = "candidate_already_started"
CLIENT_KEY_CONFLICT = "client_key_conflict"
INVALID_CURSOR = "invalid_cursor"
RUN_HEADER = "X-SF-Run"
CANDIDATE_HEADER = "X-SF-Run-Candidate"
# The verified identity that owns a hosted Run (spec D6). Local mode is single-user.
_OWNER_HEADER = "X-User-Email"
_LOCAL_OWNER = "local"
# The Candidate states a cancel must stop on the runner: `pending` ones it stops itself.
_ON_THE_RUNNER = ("scheduled", "running")
# How many of a Run's topics a cancel stops at once: each stop may wait on the runner's control
# asks, so one at a time would take N times as long; unbounded, a 256-Candidate Run would open
# 256 asks on the broker together.
_STOP_CONCURRENCY = 16


def _private(response: Response) -> None:
    """INVARIANT (spec D5, D6): a Run answer is its owner's alone, so a shared cache in front of
    the Engine never serves it to another caller."""
    response.headers["Cache-Control"] = "private, no-store"
    response.headers["Vary"] = _OWNER_HEADER


router = APIRouter(prefix="/runs", tags=["Runs"], dependencies=[Depends(_private)])


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


# --- who is asking -----------------------------------------------------------------------


def _registry(request: Request) -> RunRegistry:
    """The registry, or a plain 404 while Runs are off (spec D2): the answer an Engine without
    `/runs` gives, so the Client falls back (D7)."""
    # `getattr`: an App assembled without `install_runs` has Runs off.
    registry = getattr(request.app.state, "run_registry", None)
    if registry is None:
        raise ProblemException(status=404, title="Not Found", detail="Runs are off on this Engine")
    return registry


def _caller(request: Request) -> OwnerKey | None:
    """The caller's owner key (spec D6), or None when a hosted request carries no identity."""
    if not getattr(request.app.state, "runs_require_identity", True):
        return owner_key(_LOCAL_OWNER)
    email = job_env.identity_from_headers(request.headers).get(_OWNER_HEADER)
    return None if email is None else owner_key(email)


def _owner(request: Request) -> OwnerKey:
    owner = _caller(request)
    if owner is None:
        raise ProblemException(
            status=401,
            title="Unauthorized",
            detail="a verified caller identity is required",
            code="identity_required",
        )
    return owner


def _not_found(run_id: str) -> ProblemException:
    return ProblemException(
        status=404, title="Not Found", detail=f"no run {run_id}", code=RUN_NOT_FOUND
    )


def _invalid(exc: ValueError) -> ProblemException:
    return ProblemException(status=422, title="Unprocessable Content", detail=str(exc))


async def _read(registry: RunRegistry, owner: OwnerKey, run_id: str) -> RunRecord:
    record = await registry.get(owner, run_id) if RUN_ID_PATTERN.fullmatch(run_id) else None
    if record is None:
        raise _not_found(run_id)
    return record


async def _stop(request: Request, topic: str) -> None:
    job_runner = request.app.state.job_runner
    # No runner: this App schedules nothing, so nothing of the Run is on one.
    if job_runner is not None:
        await stop_topic(job_runner, request.app.state.stream, topic)


async def _stop_all(request: Request, topics: list[str]) -> None:
    """Stop every topic, `_STOP_CONCURRENCY` at a time. Every stop is tried even when one fails;
    the first failure is then raised (a 503 on an unreadable queue), and a retried cancel stops
    what is still live."""
    gate = asyncio.Semaphore(_STOP_CONCURRENCY)

    async def stop_one(topic: str) -> None:
        async with gate:
            await _stop(request, topic)

    results = await asyncio.gather(*(stop_one(t) for t in topics), return_exceptions=True)
    for result in results:
        if isinstance(result, BaseException):
            raise result


# --- the routes --------------------------------------------------------------------------


@router.post("", status_code=201, summary="Register a Run")
async def create_run(request: Request, response: Response, body: RunCreate) -> RunBody:
    """201 with the new Run, or 200 with the caller's Run of the same `client_key`; 409
    `client_key_conflict` when that Run names another evaluation."""
    registry = _registry(request)
    owner = _owner(request)
    try:
        spec = RunSpec(
            client_key=body.client_key,
            benchmark=body.benchmark,
            case_count=body.case_count,
            candidates=tuple(body.candidates),
            client_version=body.client_version,
        )
    except ValueError as exc:
        raise _invalid(exc) from exc
    try:
        record, created = await registry.register(owner, spec)
    except ClientKeyConflict as exc:
        raise ProblemException(
            status=409, title="Conflict", detail=str(exc), code=CLIENT_KEY_CONFLICT
        ) from exc
    if not created:
        response.status_code = 200
    return RunBody.of(record)


@router.get("", summary="List Runs, newest first")
async def list_runs(
    request: Request,
    state: RunState | None = None,
    since: datetime | None = None,
    limit: int = 50,
    cursor: str | None = None,
) -> RunList:
    registry = _registry(request)
    owner = _owner(request)
    try:
        query = RunQuery(state=state, since=since, limit=limit, cursor=cursor)
    except ValueError as exc:
        raise _invalid(exc) from exc
    try:
        page = await registry.list(owner, query)
    except InvalidCursor as exc:
        raise ProblemException(
            status=422,
            title="Unprocessable Content",
            detail=f"the cursor {exc} names no run of yours",
            code=INVALID_CURSOR,
        ) from exc
    return RunList(runs=[RunBody.of(r) for r in page.runs], next_cursor=page.next_cursor)


@router.get("/{run_id}", summary="Read a Run")
async def get_run(request: Request, run_id: str) -> RunBody:
    registry = _registry(request)
    return RunBody.of(await _read(registry, _owner(request), run_id))


@router.delete("/{run_id}", status_code=202, summary="Cancel a Run")
async def cancel_run(request: Request, run_id: str) -> Response:
    """Spec D12: 202 while any Candidate is not terminal, after stopping every live topic; 204,
    changing nothing, once every Candidate is terminal."""
    registry = _registry(request)
    owner = _owner(request)
    before = await _read(registry, owner, run_id)
    if all(is_terminal_candidate(c.state) for c in before.candidates):
        return Response(status_code=204)
    record = await registry.cancel(owner, run_id)
    if record is None:
        raise _not_found(run_id)
    live = [
        c.attempt_id
        for c in record.candidates
        if c.state in _ON_THE_RUNNER and c.attempt_id is not None
    ]
    await _stop_all(request, live)
    return Response(status_code=202)


# --- binding a start (spec R2) -----------------------------------------------------------

# How a refused bind answers: (status, title, code, detail).
_REFUSALS: dict[type[Exception], tuple[int, str, str, str]] = {
    RunNotFound: (404, "Not Found", RUN_NOT_FOUND, "no such run"),
    UnknownCandidate: (400, "Bad Request", MALFORMED_HEADER, "the run has no such Candidate"),
    RunCanceled: (409, "Conflict", RUN_CANCELED, "the run was canceled"),
    CandidateAlreadyStarted: (
        409,
        "Conflict",
        CANDIDATE_ALREADY_STARTED,
        "the Candidate or the topic is already bound to another start",
    ),
}


def _start_binding(request: Request) -> tuple[RunRegistry, str, int] | None:
    """(registry, run id, Candidate index) for a start that names a Run, else None."""
    run_id = request.headers.get(RUN_HEADER)
    if run_id is None:
        return None
    raw = request.headers.get(CANDIDATE_HEADER)
    if raw is None or not raw.isascii() or not raw.isdigit():
        raise ProblemException(
            status=400,
            title="Bad Request",
            detail=f"{CANDIDATE_HEADER} must be the Candidate's zero-based index",
            code=MALFORMED_HEADER,
        )
    registry = getattr(request.app.state, "run_registry", None)
    # Runs off: the start runs unbound, as on an Engine without `/runs`.
    return None if registry is None else (registry, run_id, int(raw))


async def bind_start(request: Request, topic: str) -> Callable[[], Awaitable[None]]:
    """Bind the start's topic to its Run's Candidate, before anything is scheduled.

    Returns the step the start runs once scheduled: `confirm_scheduled`, or a no-op for an
    unbound start. A start without `X-SF-Run` is unchanged. A bind that fails on the database is
    logged and the start proceeds unbound (spec §8): history never blocks an evaluation.
    """
    binding = _start_binding(request)
    if binding is None:
        return _unbound
    registry, run_id, candidate = binding
    owner = _caller(request)
    if owner is None or not RUN_ID_PATTERN.fullmatch(run_id):
        raise _not_found(run_id)
    try:
        await registry.bind(owner, run_id, candidate, topic)
    except tuple(_REFUSALS) as exc:
        status, title, code, detail = _REFUSALS[type(exc)]
        raise ProblemException(status=status, title=title, detail=detail, code=code) from exc
    except Exception:
        _logger.warning("run bind failed topic=%s; starting unbound", topic, exc_info=True)
        return _unbound
    return functools.partial(confirm_scheduled, request, topic)


async def _unbound() -> None:
    """An unbound start has nothing to confirm."""


async def confirm_scheduled(request: Request, topic: str) -> None:
    """Move the bound Candidate to `scheduled`. A cancel that won between the bind and here
    stopped the Candidate, so the start stops what it just scheduled and answers 409."""
    registry: RunRegistry = request.app.state.run_registry
    try:
        stands = await registry.mark_scheduled(topic)
    except Exception:
        # WHY carry on: the run is scheduled; its outcome still settles it (R4).
        _logger.warning("run mark_scheduled failed topic=%s", topic, exc_info=True)
        return
    if not stands:
        await _stop(request, topic)
        raise ProblemException(
            status=409,
            title="Conflict",
            detail="the run was canceled while this Candidate started",
            code=RUN_CANCELED,
        )


__all__ = [
    "CANDIDATE_HEADER",
    "RUN_HEADER",
    "bind_start",
    "confirm_scheduled",
    "router",
]
