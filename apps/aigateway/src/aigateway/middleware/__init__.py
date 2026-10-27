"""App-wide ASGI middleware that is not tied to one feature area.

`core/auth/` holds the middleware that enforces the auth boundary. This package is for
cross-cutting request plumbing — correlation (OME-938) and the body cap (OME-1542).
"""

from .body_cap import BodyCapMiddleware, RequestBodyTooLarge
from .call_id import CallIdMiddleware

__all__ = ["BodyCapMiddleware", "CallIdMiddleware", "RequestBodyTooLarge"]
