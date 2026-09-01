"""RFC 9457 (`application/problem+json`) error responses for the whole service: a `Problem` body
model, a `ProblemException` any handler can raise to produce one, and the FastAPI exception
handler that renders it.

Mirrored from the engine's `auth/problem.py` rather than imported — apps here never import each
other's internals — so a client that already codes against the engine's error shape needs no
second parser.

THIS MODULE IS THE ONLY RFC 9457 PLUMBING IN THIS SERVICE. Constructors for the individual
statuses this service can return live beside it in `problem_catalogue.py`; no route raises
`ProblemException` with an ad-hoc status. A status a client has never seen documented is what
turns "my retry stopped working" into a support question.
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


class ProblemException(Exception):
    """Exception carrying a :class:`Problem` (and optional response headers) to be rendered by
    :func:`problem_exception_handler`.
    """

    def __init__(
        self,
        status: int,
        title: str,
        detail: str | None = None,
        type_: str = "about:blank",
        headers: dict[str, str] | None = None,
    ) -> None:
        self.problem = Problem(type=type_, title=title, status=status, detail=detail)
        self.headers = headers
        super().__init__(title)


def render_problem(exc: ProblemException) -> Response:
    """The response body for a :class:`ProblemException`, without a request.

    Exists because the pre-routing body-limit middleware sits OUTSIDE starlette's
    `ExceptionMiddleware` — where the handler below is registered — so raising there produces an
    unhandled 500 rather than a problem body. It has to send the response itself, and it must
    send the same one every other 413 in this service sends.
    """
    return JSONResponse(
        status_code=exc.problem.status,
        content=exc.problem.model_dump(exclude_none=True),
        media_type=PROBLEM_MEDIA_TYPE,
        headers=exc.headers,
    )


async def problem_exception_handler(request: Request, exc: Exception) -> Response:
    """Render a :class:`ProblemException` as ``application/problem+json`` (RFC 9457).

    Typed `Exception` (not `ProblemException`) to match FastAPI's exception handler signature.
    """
    # INVARIANT: only registered for ProblemException; re-raise anything else untouched. Raising
    # here does NOT re-dispatch to a sibling handler — it propagates to the outer error
    # middleware and becomes an unhandled 500.
    if not isinstance(exc, ProblemException):
        raise exc
    return render_problem(exc)


def install_problem_handlers(app: FastAPI) -> None:
    """Wire the RFC 9457 handler additively onto ``app`` (idempotent per exception type)."""
    app.add_exception_handler(ProblemException, problem_exception_handler)
