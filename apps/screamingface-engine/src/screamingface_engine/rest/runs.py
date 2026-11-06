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
from collections.abc import Awaitable, Callable, Coroutine
from datetime import datetime
from decimal import Decimal
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.routing import APIRoute
from pydantic import BaseModel, ConfigDict, PlainSerializer, StrictInt
from starlette.exceptions import HTTPException

from screamingface_engine import job_env
from screamingface_engine.auth import ProblemException
from screamingface_engine.rest.gateway_route import problem_responses
from screamingface_engine.rest.stopping import QUEUE_UNAVAILABLE_RETRY_AFTER_S, stop_topic
from screamingface_engine.runs.ids import RUN_ID_PATTERN
from screamingface_engine.runs.records import (
    MAX_CANDIDATES,
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
MALFORMED_BODY = "malformed_body"
RUN_HEADER = "X-SF-Run"
CANDIDATE_HEADER = "X-SF-Run-Candidate"
# The verified identity that owns a hosted Run (spec D6). Local mode is single-user.
_OWNER_HEADER = "X-User-Email"
_LOCAL_OWNER = "local"
# How many of a Run's topics a cancel stops at once: each stop may wait on the runner's control
# asks, so one at a time would take N times as long; unbounded, a 256-Candidate Run would open
# 256 asks on the broker together.
_STOP_CONCURRENCY = 16


# INVARIANT (spec D5, D6): a Run answer is its owner's alone, so a shared cache in front of the
# Engine never serves it to another caller. Errors and empty answers carry it too: a 404 tells
# one owner's Runs from another's.
_PRIVATE_HEADERS = {"Cache-Control": "private, no-store", "Vary": _OWNER_HEADER}


def _private(response: Response) -> None:
    response.headers.update(_PRIVATE_HEADERS)


def _problem(
    *, status: int, title: str, detail: str | None = None, code: str | None = None
) -> ProblemException:
    """A `/runs` Problem, with the private cache headers."""
    return ProblemException(
        status=status, title=title, detail=detail, code=code, headers=dict(_PRIVATE_HEADERS)
    )


# How much of a refused request a 422 names. WHY a bound: a request can carry thousands of
# unknown fields, or a field name of any length, and the answer must not grow with it.
_SHOWN_LOCATIONS = 10
_SHOWN_SEGMENT = 64


def _invalid_at(exc: RequestValidationError) -> str:
    """Where ``exc`` found the request invalid: the field locations only, never their values
    (those are the caller's request, echoed back), bounded in count and length."""
    locations = sorted(
        {".".join(str(part)[:_SHOWN_SEGMENT] for part in e.get("loc", ())) for e in exc.errors()}
    )
    shown = ", ".join(locations[:_SHOWN_LOCATIONS])
    hidden = len(locations) - _SHOWN_LOCATIONS
    return shown if hidden <= 0 else f"{shown} and {hidden} more"


class _RunsRoute(APIRoute):
    """The `/runs` boundary. Spec D2, D6: Runs off answers 404 and a hosted call with no identity
    401, whatever its body or query; a request FastAPI cannot validate answers a 422 Problem."""

    def get_route_handler(self) -> Callable[[Request], Coroutine[Any, Any, Response]]:
        route_handler = super().get_route_handler()

        async def runs_route_handler(request: Request) -> Response:
            # WHY before `route_handler`: that is where FastAPI reads and parses the body, so an
            # unparseable one would otherwise answer 422 ahead of Runs off and identity.
            _registry(request)
            _owner(request)
            try:
                return await route_handler(request)
            except RequestValidationError as exc:
                raise _problem(
                    status=422,
                    title="Unprocessable Content",
                    detail=f"the request is invalid at {_invalid_at(exc)}",
                ) from None
            except HTTPException as exc:
                # FastAPI's answer to a body it could not decode (invalid UTF-8, say).
                if exc.status_code != 400:
                    raise
                raise _problem(
                    status=400,
                    title="Bad Request",
                    detail="the request body could not be read as JSON",
                    code=MALFORMED_BODY,
                ) from None

        return runs_route_handler


# The cache headers every `/runs` answer carries, as OpenAPI documents a response's headers.
PRIVATE_HEADERS_DOC: dict[str, Any] = {
    name: {"schema": {"type": "string", "enum": [value]}}
    for name, value in _PRIVATE_HEADERS.items()
}


def _private_problems(descriptions: dict[int, str]) -> dict[int | str, dict[str, Any]]:
    """`problem_responses` for `/runs`: every Problem carries the private cache headers too."""
    return {
        status: {**entry, "headers": PRIVATE_HEADERS_DOC}
        for status, entry in problem_responses(descriptions).items()
    }


router = APIRouter(
    prefix="/runs",
    tags=["Runs"],
    route_class=_RunsRoute,
    dependencies=[Depends(_private)],
    responses=_private_problems(
        {
            400: "The request body could not be read as JSON (`malformed_body`).",
            401: "A hosted call with no verified identity (`identity_required`).",
            422: "The request does not validate: its body, path or query.",
            404: "No such Run of the caller's (`run_not_found`), or Runs are off on this Engine.",
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


# --- who is asking -----------------------------------------------------------------------


def _registry(request: Request) -> RunRegistry:
    """The registry, or a plain 404 while Runs are off (spec D2): the answer an Engine without
    `/runs` gives, so the Client falls back (D7)."""
    # `getattr`: an App assembled without `install_runs` has Runs off.
    registry = getattr(request.app.state, "run_registry", None)
    if registry is None:
        raise _problem(status=404, title="Not Found", detail="Runs are off on this Engine")
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
        raise _problem(
            status=401,
            title="Unauthorized",
            detail="a verified caller identity is required",
            code="identity_required",
        )
    return owner


def _not_found(run_id: str) -> ProblemException:
    return _problem(status=404, title="Not Found", detail=f"no run {run_id}", code=RUN_NOT_FOUND)


def _invalid(exc: ValueError) -> ProblemException:
    return _problem(status=422, title="Unprocessable Content", detail=str(exc))


async def _read(registry: RunRegistry, owner: OwnerKey, run_id: str) -> RunRecord:
    record = await registry.get(owner, run_id) if RUN_ID_PATTERN.fullmatch(run_id) else None
    if record is None:
        raise _not_found(run_id)
    return record


async def _stop(request: Request, topic: str) -> None:
    job_runner = request.app.state.job_runner
    # No runner: this App schedules nothing, so nothing of the Run is on one.
    if job_runner is not None:
        await stop_topic(job_runner, request.app.state.stream, topic, bound=True)


async def _stop_owed(request: Request, registry: RunRegistry, owner: OwnerKey, run_id: str) -> None:
    """Stop every owed topic, `_STOP_CONCURRENCY` at a time, and clear each obligation once its
    stop succeeded (spec D12). Every stop is tried even when one fails; a failure whose topic is
    still owed is then raised as a private 503, and a retried cancel stops what is still owed."""
    topics = await registry.owed_stops(owner, run_id)
    gate = asyncio.Semaphore(_STOP_CONCURRENCY)

    async def stop_one(topic: str) -> None:
        async with gate:
            await _stop(request, topic)
        await registry.stop_done(topic)

    results = await asyncio.gather(*(stop_one(t) for t in topics), return_exceptions=True)
    failed = [(t, r) for t, r in zip(topics, results, strict=True) if isinstance(r, BaseException)]
    if not failed:
        return
    # WHY recheck: a concurrent cancel may have completed the same stop, so this one's failure
    # leaves nothing owed and is not the caller's to retry.
    still_owed = set(await registry.owed_stops(owner, run_id))
    for topic, result in failed:
        if topic in still_owed:
            raise _private_failure(result) from result


def _private_failure(exc: BaseException) -> BaseException:
    """A stop's failure as a `/runs` answer: a Problem keeps its own status and gains the private
    cache headers; any other error (the broker refusing the stream delete) is a retryable 503."""
    if isinstance(exc, ProblemException):
        exc.headers = {**(exc.headers or {}), **_PRIVATE_HEADERS}
        return exc
    if not isinstance(exc, Exception):
        return exc  # a cancellation, not a failure
    _logger.warning("a Run's stop failed; the cancel can be retried", exc_info=exc)
    return ProblemException(
        status=503,
        title="Service Unavailable",
        detail="a Candidate could not be stopped; retry",
        headers={"Retry-After": str(QUEUE_UNAVAILABLE_RETRY_AFTER_S), **_PRIVATE_HEADERS},
    )


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
        **_private_problems(
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
        raise _problem(
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
        **_private_problems(
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
    registry = _registry(request)
    owner = _owner(request)
    try:
        query = RunQuery(state=state, since=since, limit=limit, cursor=cursor)
    except ValueError as exc:
        raise _invalid(exc) from exc
    try:
        page = await registry.list(owner, query)
    except InvalidCursor as exc:
        raise _problem(
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
    registry = _registry(request)
    return RunBody.of(await _read(registry, _owner(request), run_id))


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
    registry = _registry(request)
    owner = _owner(request)
    record = await _read(registry, owner, run_id)
    changed = False
    if not all(is_terminal_candidate(c.state) for c in record.candidates):
        canceled = await registry.cancel(owner, run_id)
        if canceled is None:
            raise _not_found(run_id)
        # The cancel changed something only if it flagged the Run: the last outcome may have
        # landed first, and a retried cancel finds the flag already set.
        changed = canceled.canceled and not record.canceled
        record = canceled
    # WHY owed and not derived from state: a stop that failed leaves its Candidate `stopped`
    # (or still running), and only the stored obligation tells it from one that ended on its own.
    await _stop_owed(request, registry, owner, run_id)
    if changed or not all(is_terminal_candidate(c.state) for c in record.candidates):
        return Response(status_code=202, headers=_PRIVATE_HEADERS)
    return Response(status_code=204, headers=_PRIVATE_HEADERS)


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
    runs, candidates = (
        request.headers.getlist(RUN_HEADER),
        request.headers.getlist(CANDIDATE_HEADER),
    )
    if not runs and not candidates:
        return None
    # WHY refuse a repeat: two field lines would bind whichever one `get` happened to return.
    run_id = runs[0] if len(runs) == 1 else None
    raw = candidates[0] if len(candidates) == 1 else None
    # WHY a length bound before `int`: a run of thousands of digits is costly to parse and
    # overflows the database's index column; no Run has more than `MAX_CANDIDATES`.
    if (
        run_id is None
        or raw is None
        or not raw.isascii()
        or not raw.isdigit()
        or len(raw) > len(str(MAX_CANDIDATES))
        or int(raw) >= MAX_CANDIDATES
    ):
        raise ProblemException(
            status=400,
            title="Bad Request",
            detail=f"{RUN_HEADER} and {CANDIDATE_HEADER}, the Candidate's zero-based index, "
            "come together",
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
        # Private: whether a Run is canceled or not yours depends on who asks.
        raise _problem(status=status, title=title, detail=detail, code=code) from exc
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
        try:
            await _stop(request, topic)
            await registry.stop_done(topic)
        except BaseException as exc:
            raise _private_failure(exc) from exc
        # Private: whether a Run is canceled depends on who asks.
        raise _problem(
            status=409,
            title="Conflict",
            detail="the run was canceled while this Candidate started",
            code=RUN_CANCELED,
        )


__all__ = [
    "CANDIDATE_HEADER",
    "PRIVATE_HEADERS_DOC",
    "RUN_HEADER",
    "bind_start",
    "confirm_scheduled",
    "router",
]
