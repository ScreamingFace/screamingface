"""FastAPI dependency injection for auth: extracts the `URL4-Capability` header
from a request, verifies it as a JWT via `JwtCodec`, and yields the decoded
claims to the route — translating any verification failure into a uniform
401 RFC 9457 problem response.
"""

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Annotated

from fastapi import Depends, Request

from screamingface_engine.auth.errors import AuthError, MissingCredentials
from screamingface_engine.auth.jwt import JwtCodec
from screamingface_engine.auth.problem import ProblemException
from screamingface_engine.config import Settings

Clock = Callable[[], datetime]
_CAPABILITY_HEADER = "URL4-Capability"


def _default_clock() -> datetime:
    return datetime.now(UTC)


def _extract_capability(request: Request) -> str:
    # WHY: the per-run capability rides a dedicated header (RFC 6648-clean, no `X-`; RFC 9449
    # DPoP-style secondary credential), decoupled from `Authorization` so a gateway/mesh/SDK that
    # owns the primary identity slot cannot strip or overwrite it (OME-556). Bare JWT, no scheme.
    token = request.headers.get(_CAPABILITY_HEADER)
    if not token:
        raise MissingCredentials("missing capability credentials")
    return token.strip()


def verified_claims(request: Request) -> dict[str, object]:
    """FastAPI dependency: verify the request's capability token and return
    its claims.

    Uses `request.app.state.clock` if set (tests inject a fake clock),
    otherwise the real UTC clock.

    Raises:
        ProblemException: 401 Unauthorized if the token is missing, malformed,
            unsigned by this app's secret, or outside its iat/exp window —
            wraps any `AuthError` from `_extract_capability`/`JwtCodec.verify`
            without leaking which specific check failed.
    """
    settings: Settings = request.app.state.settings
    clock: Clock = getattr(request.app.state, "clock", _default_clock)
    codec = JwtCodec(
        secret=settings.jwt_secret,
        iat_window_s=settings.iat_window_s,
        capability_lifetime_s=settings.capability_lifetime_s,
    )
    try:
        token = _extract_capability(request)
        return codec.verify(token, clock())
    except AuthError as exc:
        # WHY: one opaque reason for every failure — no oracle revealing which check failed. No
        # WWW-Authenticate header here: that RFC 7235 challenge is bound to `Authorization`, which
        # this capability scheme deliberately does not use (OME-556). This is a different auth
        # surface from `rest/catalog.py`, which DOES authenticate via `Authorization` and DOES send
        # `WWW-Authenticate: Bearer` on its own 401s — that is not an inconsistency to harmonize.
        raise ProblemException(
            status=401,
            title="Unauthorized",
            detail="missing, invalid, or expired capability token",
        ) from exc


# AIDEV-NOTE: capability-token auth — inject verified JWT claims into a route handler
# via `claims: VerifiedClaims`, e.g. `rest/routes.py`'s run-control endpoints.
VerifiedClaims = Annotated[dict[str, object], Depends(verified_claims)]
