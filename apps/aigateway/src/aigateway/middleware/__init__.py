"""App-wide ASGI middleware that is not tied to one feature area.

`core/auth/` holds the middleware that enforces the auth boundary. This package is for
cross-cutting request plumbing — today, correlation (OME-938).
"""

from .call_id import CallIdMiddleware

__all__ = ["CallIdMiddleware"]
