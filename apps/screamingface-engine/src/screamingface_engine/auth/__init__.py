"""Public surface of the auth package: capability-token errors, the HS256 JWT codec,
RFC 9457 problem-details plumbing, and the FastAPI dependency that verifies a
request's capability token and yields its claims.
"""

from screamingface_engine.auth.dependencies import (
    Clock,
    VerifiedClaims,
    default_clock,
    verified_claims,
)
from screamingface_engine.auth.errors import (
    AuthError,
    IatWindowExceeded,
    InvalidToken,
    MissingCredentials,
    MissingIat,
    TokenExpired,
)
from screamingface_engine.auth.jwt import JwtCodec
from screamingface_engine.auth.problem import (
    PROBLEM_MEDIA_TYPE,
    Problem,
    ProblemException,
    install_problem_handlers,
    problem_exception_handler,
)
from screamingface_engine.auth.token import new_topic

__all__ = [
    "PROBLEM_MEDIA_TYPE",
    "AuthError",
    "Clock",
    "IatWindowExceeded",
    "InvalidToken",
    "JwtCodec",
    "MissingCredentials",
    "MissingIat",
    "Problem",
    "ProblemException",
    "TokenExpired",
    "VerifiedClaims",
    "default_clock",
    "install_problem_handlers",
    "new_topic",
    "problem_exception_handler",
    "verified_claims",
]
