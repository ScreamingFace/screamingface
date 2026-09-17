"""RFC 9457 (application/problem+json) error responses shared by the auth layer
and, via `install_problem_handlers`, the rest of the app: a `Problem` body model,
a `ProblemException` any handler can raise to produce one, and the FastAPI
exception handler that renders it.
"""

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel

PROBLEM_MEDIA_TYPE = "application/problem+json"


class Problem(BaseModel):
    """An RFC 9457 problem object; ``None`` members are dropped on the wire."""

    type: str = "about:blank"
    title: str
    status: int
    detail: str | None = None
    instance: str | None = None
    # RFC 9457 §3.2 extension members (OME-941). Optional, so `exclude_none=True` drops them and
    # every problem raised without them stays byte-identical to what it was before.
    code: str | None = None
    """The run's error code — ALWAYS an engine-authored one. Whoever fills this is responsible
    for the allowlisting; the model cannot tell an engine code from an adapter's."""
    permanent: bool | None = None
    """Whether retrying this request could ever succeed."""
    trace_id: str | None = None
    """W3C trace id of the run, so the caller can find it in the trace store. NOT the topic —
    the topic is a bearer capability and never belongs in a response body."""


class ProblemException(Exception):
    """Exception carrying a `Problem` (and optional response headers) to be
    rendered by `problem_exception_handler`.
    """

    def __init__(
        self,
        status: int,
        title: str,
        detail: str | None = None,
        type_: str = "about:blank",
        headers: dict[str, str] | None = None,
        code: str | None = None,
        permanent: bool | None = None,
        trace_id: str | None = None,
    ) -> None:
        self.problem = Problem(
            type=type_,
            title=title,
            status=status,
            detail=detail,
            code=code,
            permanent=permanent,
            trace_id=trace_id,
        )
        self.headers = headers
        super().__init__(title)


async def problem_exception_handler(request: Request, exc: Exception) -> Response:
    """Render a :class:`ProblemException` as ``application/problem+json`` (RFC 9457).

    Typed `Exception` (not `ProblemException`) to match FastAPI's exception
    handler signature.
    """
    # INVARIANT: only registered for ProblemException; re-raise anything else untouched.
    # Raising here does NOT re-dispatch to a sibling handler — it propagates to the
    # outer error middleware and becomes an unhandled 500.
    if not isinstance(exc, ProblemException):
        raise exc
    return JSONResponse(
        status_code=exc.problem.status,
        content=exc.problem.model_dump(exclude_none=True),
        media_type=PROBLEM_MEDIA_TYPE,
        headers=exc.headers,
    )


def install_problem_handlers(app: FastAPI) -> None:
    """Wire the RFC 9457 handler additively onto ``app`` (idempotent per exception type)."""
    app.add_exception_handler(ProblemException, problem_exception_handler)
