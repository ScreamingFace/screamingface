"""A private mount answers a caller it cannot prove granted as an undeclared route.

FEATURE (OME-1770 review): hosted BYOM, Unit 2. A private configured-endpoint route is executable
but unpublished, and the Gateway alone knows which accounts it grants.

INVARIANT: every answer a private mount gives a caller without a proven grant is the framework's
own 404 for a path no route matches, byte for byte, and `/metrics` counts it as unmatched. A 403,
a 405, a pre-queue 400 or 414, or a refused run would each tell that caller the route exists.

WHY the grant is asked only on a refusal: a granted caller's successful call costs no extra
Gateway round trip, and a success is never an answer an ungranted caller gets.
"""

from typing import NoReturn

from fastapi import Request
from starlette.exceptions import HTTPException

from screamingface_engine import job_env
from screamingface_engine.catalog.port import CatalogError, Credential
from screamingface_engine.metrics import DENIED_ROUTE


def deny(request: Request) -> NoReturn:
    """Answer as the router answers a path that matches no route."""
    request.scope[DENIED_ROUTE] = True
    raise HTTPException(status_code=404)


async def granted(request: Request, model: str) -> bool:
    """Whether the Gateway grants this caller `model`, asked through the details source.

    Fails closed: no identity, no details source, or a failed details call is no grant.
    """
    identity = job_env.identity_from_headers(request.headers)
    source = getattr(request.app.state, "model_parameters", None)
    if not identity or source is None:
        return False
    try:
        response = await source.fetch_model_parameters(Credential.derive(identity), model)
    except CatalogError:
        return False
    return 200 <= response.status < 300


__all__ = ["deny", "granted"]
