"""The REST surfaces' refusal of a stated `X-Profile` (OME-1381, Stage D of OME-1138).

FEATURE: selector-less provider access. The Engine is the producer of every run and every
catalog, model-parameter and connection request it sends the gateway; producer-off means none of
them names a stored credential by label any more. The gateway keeps honouring a legacy selector
until the drain proof, so a run accepted before this build still routes as it was asked to.

INVARIANT: raised BEFORE any schedule, queue publication, catalog or gateway I/O, or connection
mutation — each caller refuses first, then does its work. After authentication, where a route
has any: the capability dependency still answers an unauthenticated caller first. Where a route
reads a request body (the connection routes), the refusal runs in the route class, before FastAPI
parses or validates that body.
"""

from __future__ import annotations

from fastapi import Header
from starlette.datastructures import Headers

from screamingface_engine.auth import ProblemException
from screamingface_engine.request_scope import (
    PROFILE_HEADER,
    X_PROFILE_UNSUPPORTED,
    X_PROFILE_UNSUPPORTED_MESSAGE,
    requests_selector,
)

# The OpenAPI declaration of the retired header, shared by every refusing route. It documents and
# never decides: `refuse_selector` judges EVERY value off the request, which a single-value
# parameter cannot see.
X_PROFILE_PARAMETER = Header(
    alias=PROFILE_HEADER,
    deprecated=True,
    description="No longer supported: any nonblank value is refused with 400.",
)


def refuse_selector(headers: Headers, *, problem_headers: dict[str, str] | None = None) -> None:
    """Raise the non-retryable 400 when the request states a selector; return for absent/blank.

    ``problem_headers`` lets a route keep its own privacy headers on this answer, as on every
    other answer it gives.
    """
    if requests_selector(headers.getlist(PROFILE_HEADER)):
        raise ProblemException(
            status=400,
            title="Bad Request",
            detail=X_PROFILE_UNSUPPORTED_MESSAGE,
            code=X_PROFILE_UNSUPPORTED,
            headers=problem_headers,
        )


__all__ = ["X_PROFILE_PARAMETER", "refuse_selector"]
