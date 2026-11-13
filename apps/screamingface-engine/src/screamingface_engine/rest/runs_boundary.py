"""The `/runs` boundary (E5 P1 spec §4.1, D2, D6): who is asking, the private Problems every
answer carries, and stopping a Run's Candidate. Shared by the `/runs` routes.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Coroutine
from typing import Any

from fastapi import Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.routing import APIRoute
from starlette.exceptions import HTTPException
from starlette.requests import HTTPConnection
from starlette.types import Message

from screamingface_engine import job_env
from screamingface_engine.artifacts.run_results import RESULT_STORE_UNAVAILABLE
from screamingface_engine.auth import ProblemException
from screamingface_engine.rest.capped_body import BodyTooLarge, capped_body
from screamingface_engine.rest.gateway_route import problem_responses
from screamingface_engine.rest.selector import refuse_selector
from screamingface_engine.rest.stopping import QUEUE_UNAVAILABLE_RETRY_AFTER_S, stop_topic
from screamingface_engine.runs.db import UNAVAILABLE_ERRORS
from screamingface_engine.runs.ids import RUN_ID_PATTERN
from screamingface_engine.runs.records import (
    OwnerKey,
    owner_key,
)
from screamingface_engine.runs.registry import (
    RunRegistry,
)

_logger = logging.getLogger(__name__)

RUN_NOT_FOUND = "run_not_found"
RUN_CANCELED = "run_canceled"
CLIENT_KEY_CONFLICT = "client_key_conflict"
INVALID_CURSOR = "invalid_cursor"
MALFORMED_BODY = "malformed_body"
# E5 P2 spec D16: every 404 and 422 a P2 Engine sends on `/runs` carries a code, so a P2 Client
# tells an Engine from before P2 (code-less) from this one.
RUNS_OFF = "runs_off"
INVALID_REQUEST = "invalid_request"
REQUEST_TOO_LARGE = "request_too_large"
# The verified identity that owns a hosted Run (spec D6). Local mode is single-user.
_OWNER_HEADER = "X-User-Email"
_LOCAL_OWNER = "local"
# INVARIANT (spec D5, D6): a Run answer is its owner's alone, so a shared cache in front of the
# Engine never serves it to another caller. Errors and empty answers carry it too: a 404 tells
# one owner's Runs from another's.
PRIVATE_HEADERS = {"Cache-Control": "private, no-store", "Vary": _OWNER_HEADER}


def private_answer(response: Response) -> None:
    response.headers.update(PRIVATE_HEADERS)


def problem(
    *, status: int, title: str, detail: str | None = None, code: str | None = None
) -> ProblemException:
    """A `/runs` Problem, with the private cache headers."""
    return ProblemException(
        status=status, title=title, detail=detail, code=code, headers=dict(PRIVATE_HEADERS)
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


class RunsRoute(APIRoute):
    """The `/runs` boundary. Spec D2, D6: Runs off answers 404 and a hosted call with no identity
    401, whatever its body or query; a request FastAPI cannot validate answers a 422 Problem."""

    def get_route_handler(self) -> Callable[[Request], Coroutine[Any, Any, Response]]:
        route_handler = super().get_route_handler()

        async def runs_route_handler(request: Request) -> Response:
            # WHY before `route_handler`: that is where FastAPI reads and parses the body, so an
            # unparseable one would otherwise answer 422 ahead of Runs off and identity.
            _admit(request, self.methods)
            try:
                return await route_handler(await _capped(request))
            except RequestValidationError as exc:
                raise problem(
                    status=422,
                    title="Unprocessable Content",
                    detail=f"the request is invalid at {_invalid_at(exc)}",
                    code=INVALID_REQUEST,
                ) from None
            except HTTPException as exc:
                # FastAPI's answer to a body it could not decode (invalid UTF-8, say).
                if exc.status_code != 400:
                    raise
                raise problem(
                    status=400,
                    title="Bad Request",
                    detail="the request body could not be read as JSON",
                    code=MALFORMED_BODY,
                ) from None
            except ProblemException:
                raise
            except UNAVAILABLE_ERRORS as exc:
                # WHY inside the same envelope: the answer depends on who asks, so even a failure
                # stays a private Problem rather than a shared plain-text 500 (spec §4.1).
                raise _registry_unavailable(exc) from None
            except Exception as exc:
                # WHY not 503: retrying a bug fails the same way, so the Client is not told to.
                raise _unexpected_failure(exc) from None

        return runs_route_handler


def _admit(request: Request, methods: set[str] | None) -> None:
    """Runs off (404) and no identity (401) first; then, on `POST /runs`, a stated selector (400).

    WHY the selector: `POST /runs` feeds the driver, which schedules, so it refuses one as the
    start route does (OME-1381), before the body is read.
    """
    request_registry(request)
    request_owner(request)
    if methods and "POST" in methods:
        refuse_selector(request.headers, problem_headers=dict(PRIVATE_HEADERS))


async def _capped(request: Request) -> Request:
    """``request`` with its body read up to `run_request_max_bytes` (E5 P2 spec §4.1): a body
    over it is a 413 before any of it is parsed. WHY a new `Request`: FastAPI reads the body
    from the request it is handed, and this one's stream is spent."""
    if request.method != "POST":
        return request
    limit = request.app.state.settings.run_request_max_bytes
    try:
        body = await capped_body(request, limit)
    except BodyTooLarge as exc:
        raise problem(
            status=413, title="Content Too Large", detail=str(exc), code=REQUEST_TOO_LARGE
        ) from None

    async def replay() -> Message:
        return {"type": "http.request", "body": body, "more_body": False}

    return Request(request.scope, replay)


def _registry_unavailable(exc: Exception) -> ProblemException:
    _logger.warning("the Run registry could not answer; the request can be retried", exc_info=exc)
    return ProblemException(
        status=503,
        title="Service Unavailable",
        detail="the Run registry could not answer; retry",
        headers={"Retry-After": str(QUEUE_UNAVAILABLE_RETRY_AFTER_S), **PRIVATE_HEADERS},
    )


def _unexpected_failure(exc: Exception) -> ProblemException:
    _logger.error("a /runs request failed unexpectedly", exc_info=exc)
    return problem(
        status=500,
        title="Internal Server Error",
        detail="the request failed unexpectedly; retrying will not help",
    )


# The cache headers every `/runs` answer carries, as OpenAPI documents a response's headers.
PRIVATE_HEADERS_DOC: dict[str, Any] = {
    name: {"schema": {"type": "string", "enum": [value]}} for name, value in PRIVATE_HEADERS.items()
}


def private_problems(descriptions: dict[int, str]) -> dict[int | str, dict[str, Any]]:
    """`problem_responses` for `/runs`: every Problem carries the private cache headers too."""
    return {
        status: {**entry, "headers": PRIVATE_HEADERS_DOC}
        for status, entry in problem_responses(descriptions).items()
    }


# --- who is asking -----------------------------------------------------------------------


def request_registry(request: Request) -> RunRegistry:
    """The registry, or a plain 404 while Runs are off (spec D2): the answer an Engine without
    `/runs` gives, so the Client falls back (D7)."""
    # `getattr`: an App assembled without `install_runs` has Runs off.
    registry = getattr(request.app.state, "run_registry", None)
    if registry is None:
        raise problem(
            status=404, title="Not Found", detail="Runs are off on this Engine", code=RUNS_OFF
        )
    return registry


def request_email(connection: HTTPConnection) -> str | None:
    """The caller's verified email, or None in local mode (single-user) or with no identity.

    INVARIANT (E5 P2 spec D8): personal data, kept on the Run for its driver only; never logged
    and never returned.
    """
    if not getattr(connection.app.state, "runs_require_identity", True):
        return None
    return job_env.identity_from_headers(connection.headers).get(_OWNER_HEADER)


def request_caller(connection: HTTPConnection) -> OwnerKey | None:
    """The caller's owner key (spec D6), or None when a hosted request carries no identity.
    Also asked of a WebSocket (`rest.runs_events`)."""
    if not getattr(connection.app.state, "runs_require_identity", True):
        return owner_key(_LOCAL_OWNER)
    email = request_email(connection)
    return None if email is None else owner_key(email)


def request_owner(request: Request) -> OwnerKey:
    owner = request_caller(request)
    if owner is None:
        raise problem(
            status=401,
            title="Unauthorized",
            detail="a verified caller identity is required",
            code="identity_required",
        )
    return owner


def run_not_found(run_id: str) -> ProblemException:
    # WHY only a well-formed id is named: anything else is the caller's raw value, of any length.
    detail = f"no run {run_id}" if RUN_ID_PATTERN.fullmatch(run_id) else "no run with that id"
    return problem(status=404, title="Not Found", detail=detail, code=RUN_NOT_FOUND)


def result_store_unavailable(exc: Exception | None) -> ProblemException:
    """The run-results store is missing or refused (E5 P2 spec §4.1): retryable, and private."""
    if exc is not None:
        _logger.warning("the run-results store could not answer; retryable", exc_info=exc)
    return ProblemException(
        status=503,
        title="Service Unavailable",
        detail="the run-results store could not be reached; retry",
        code=RESULT_STORE_UNAVAILABLE,
        headers={"Retry-After": str(QUEUE_UNAVAILABLE_RETRY_AFTER_S), **PRIVATE_HEADERS},
    )


def invalid_value(exc: ValueError) -> ProblemException:
    return problem(status=422, title="Unprocessable Content", detail=str(exc), code=INVALID_REQUEST)


async def stop_candidate(request: Request, topic: str) -> None:
    job_runner = request.app.state.job_runner
    # No runner: this App schedules nothing, so nothing of the Run is on one.
    if job_runner is not None:
        await stop_topic(job_runner, request.app.state.stream, topic, bound=True)


def private_failure(exc: BaseException) -> BaseException:
    """A stop's failure as a `/runs` answer: a Problem keeps its own status and gains the private
    cache headers; any other error (the broker refusing the stream delete) is a retryable 503."""
    if isinstance(exc, ProblemException):
        exc.headers = {**(exc.headers or {}), **PRIVATE_HEADERS}
        return exc
    if not isinstance(exc, Exception):
        return exc  # a cancellation, not a failure
    _logger.warning("a Run's stop failed; the cancel can be retried", exc_info=exc)
    return ProblemException(
        status=503,
        title="Service Unavailable",
        detail="a Candidate could not be stopped; retry",
        headers={"Retry-After": str(QUEUE_UNAVAILABLE_RETRY_AFTER_S), **PRIVATE_HEADERS},
    )


__all__ = [
    "PRIVATE_HEADERS",
    "PRIVATE_HEADERS_DOC",
    "RunsRoute",
]
