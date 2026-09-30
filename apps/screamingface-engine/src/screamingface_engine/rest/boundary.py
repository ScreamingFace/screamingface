"""The request boundary shared by the credential-adjacent REST routes (connections, freeze).

FEATURE: OME-1381 selector refusal and OME-1119 trace propagation, written once. Each route family
differs only in its log label and its fixed 422 problem; everything else here is the same.

INVARIANT: never log or echo request input — a validation failure is replaced by a fixed problem.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Coroutine, Mapping
from typing import Annotated, Any

from fastapi import Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.routing import APIRoute

from screamingface_engine import job_env
from screamingface_engine.auth import PROBLEM_MEDIA_TYPE, ProblemException
from screamingface_engine.connections.port import Caller
from screamingface_engine.rest.selector import X_PROFILE_PARAMETER, refuse_selector
from url4.streaming.trace import valid_traceparent


def boundary_route_class(
    *, logger: logging.Logger, log_message: str, detail: str, code: str | None = None
) -> type[APIRoute]:
    """A route class that refuses a stated selector before anything else, then replaces FastAPI's
    input-bearing validation errors with a fixed 422 problem (``detail`` and ``code``).

    ``log_message`` is logged on the route family's own ``logger``.
    """

    class _BoundaryRoute(APIRoute):
        def get_route_handler(
            self,
        ) -> Callable[[Request], Coroutine[Any, Any, Response]]:
            route_handler = super().get_route_handler()

            async def boundary_route_handler(request: Request) -> Response:
                # INVARIANT (OME-1381): refused BEFORE `route_handler`, which is where FastAPI
                # reads, parses and validates the body and resolves dependencies — so a stated
                # `X-Profile` is answered 400 ahead of any 422, and ahead of the endpoint's 503
                # for an unconfigured service. Nothing is read, written or forwarded for a
                # request that named a selector.
                refuse_selector(request.headers)
                try:
                    return await route_handler(request)
                except RequestValidationError:
                    logger.info(log_message)
                    raise ProblemException(
                        status=422,
                        title="Unprocessable Content",
                        detail=detail,
                        code=code,
                    ) from None

            return boundary_route_handler

    return _BoundaryRoute


def declare_x_profile(_x_profile: Annotated[str | None, X_PROFILE_PARAMETER] = None) -> None:
    """Document the retired header on a route; its route class refuses it."""


def problem_responses(descriptions: Mapping[int, str]) -> dict[int | str, dict[str, Any]]:
    """The OpenAPI problem responses of a route family, one per status."""
    return {
        status: {
            "description": description,
            "content": {PROBLEM_MEDIA_TYPE: {"schema": {"$ref": "#/components/schemas/Problem"}}},
        }
        for status, description in descriptions.items()
    }


def caller(request: Request) -> Caller:
    # INVARIANT (OME-1381): selector-less. The route class has already refused a stated
    # `X-Profile`, so the `Caller` built below never carries one.
    # WHY `valid_traceparent` and not the raw header (OME-1119): this value is forwarded to
    # aigateway, and a malformed one is worse than none — it would be rejected or, worse,
    # parsed into a trace joining nothing. Same rule the run path applies at
    # `adapters/k8s.py:591`, so a caller cannot get a different answer depending on which
    # Engine surface they entered through. Invalid degrades to absent, never to an error:
    # a bad trace header must not fail an otherwise valid request.
    return Caller(
        job_env.identity_from_headers(request.headers),
        traceparent=valid_traceparent(request.headers.get("traceparent")),
    )


def mark_private(response: Response) -> None:
    response.headers["Cache-Control"] = "private, no-store"
    response.headers["Vary"] = "X-User-Email"


__all__ = [
    "boundary_route_class",
    "caller",
    "declare_x_profile",
    "mark_private",
    "problem_responses",
]
