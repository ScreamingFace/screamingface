"""The app-wide last resort for an exception no route handled (OME-939).

FEATURE (OME-939, debugging & traceability Phase 0): before this, an exception escaping a route
outside the chat dispatch path became Starlette's plain-text 500 — no aigateway log line, no
`gateway_call_id`, no audit. An operator holding a failed request had nothing to grep for.

WHY the ids are re-bound here rather than read from the context: Starlette dispatches an
`Exception` handler from `ServerErrorMiddleware`, which is OUTSIDE every user middleware. By the
time this runs, `CallIdMiddleware`'s `call_scope` has already unwound, so the contextvar is
empty and a plain `logger.error` would produce an anonymous line — the very defect this module
exists to remove. The middleware also publishes both ids on `scope["state"]`, which outlives the
scope; re-binding from there lets the ordinary record factory stamp them like any other line.

INVARIANT: class-name-only. The exception's message and traceback are never logged or echoed —
on this service they can carry provider response text or prompt content (the same posture as
`routes/chat_dispatch.py`). `HTTPException`s never reach here: they are already rendered (and
accounted) by `main._accounted_http_exception`.

AIDEV-NOTE: Starlette's `ServerErrorMiddleware` re-raises the exception after this handler's
response is sent, so the ASGI server still logs its own traceback on `uvicorn.error`. Suppressing
it was considered (OME-939, owner-approved only if clean) and NOT done: the only way is a
non-re-raising catch-all inside the app, which would also swallow exceptions the test client is
pinned to surface (`test_profile_resolution_characterisation.py::
test_a_persistent_index_fault_at_the_resolver_read_escapes_the_route`), i.e. it changes a second
prior contract. Narrowing that traceback belongs with the later split-posture phase.
"""

from __future__ import annotations

import logging

from starlette.requests import Request
from starlette.responses import JSONResponse

from aigateway.call_context import call_scope
from aigateway.core.frozen_copy.headers import published_capture_headers
from aigateway.middleware.call_id import TRACE_RESPONSE_HEADER

logger = logging.getLogger(__name__)

_CODE = "gateway_internal_error"
_MESSAGE = "The gateway hit an unexpected error."


def generic_detail() -> dict[str, str]:
    """The fixed, sanitized 500 detail (also what a frozen copy stores for such an error)."""
    return {"code": _CODE, "message": _MESSAGE}


def _published_id(request: Request, name: str) -> str | None:
    value = getattr(request.state, name, None)
    return value if isinstance(value, str) else None


async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Log one sanitized, attributable record and return a structured 500."""

    call_id = _published_id(request, "gateway_call_id")
    trace_id = _published_id(request, "trace_id")
    # WHY the guard: with no published id there is nothing to re-bind, and binding None would
    # be indistinguishable from the unbound state anyway.
    if call_id is not None:
        with call_scope(call_id, trace_id=trace_id):
            _log(request, exc)
    else:
        _log(request, exc)

    # WHY not `internal_error` (owner decision 2026-10-02): that is url4's engine-fault default, so
    # a gateway 500 under it reads as an engine fault in the engine's error surface. A
    # gateway-prefixed code keeps the failure attributed to this service.
    detail = generic_detail()
    # FEATURE: OME-1307 — the capture outcome of a call whose route raised after the copy check.
    headers = published_capture_headers(request)
    if call_id is not None:
        detail["gateway_call_id"] = call_id
    if trace_id is not None:
        # WHY set here: this response is sent by ServerErrorMiddleware with the ORIGINAL `send`,
        # bypassing the middleware wrapper that normally appends the header.
        headers[TRACE_RESPONSE_HEADER.decode("latin-1")] = trace_id
    return JSONResponse(status_code=500, content={"detail": detail}, headers=headers)


def _log(request: Request, exc: Exception) -> None:
    # Audit parity with `routes/admin._audit`: method, path and status, recorded for the failure
    # as diligently as a success would be. INVARIANT: type name only — see the module docstring.
    logger.error(
        "unhandled request error type=%s method=%s path=%s status_code=500",
        type(exc).__name__,
        request.method,
        request.url.path,
    )


__all__ = ["generic_detail", "unhandled_exception_handler"]
