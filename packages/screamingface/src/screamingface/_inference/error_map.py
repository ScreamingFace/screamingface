"""The error map of the chat call (contracts C2.4): an Engine answer or a transport failure of one
chat call, as the SDK error.

FEATURE: SDK model inference (docs/spec/2026-11-18-sdk-model-inference, contracts C2.4), unit U4.
INVARIANT: an error is retryable (permanent False) only when the Engine says so: the header
x-should-retry is true, or the stream error event has should_retry true. EngineUnavailableError
(the request was never sent) is the other non-permanent error.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Final

import httpx

from screamingface._core.retry import _retry_after_seconds
from screamingface._inference.frames import FrameErrorReason, StreamError
from screamingface.errors import (
    AuthenticationError,
    EngineCapabilityError,
    EngineUnavailableError,
    ExecutionError,
    PlanningError,
    ScreamingFaceError,
)

__all__ = [
    "CHAT_ROUTE",
    "client_timeout",
    "engine_unavailable",
    "invalid_response",
    "outcome_unknown",
    "refusal_error",
    "stream_error",
]

CHAT_ROUTE: Final = "POST /v1/chat/completions"

_NO_ROUTE_STATUSES = frozenset({404, 405})
_AUTH_STATUSES = frozenset({401, 403})
_REFUSAL_STATUSES = frozenset({400, 404, 413, 415})
_RUN_STATUSES = frozenset({408, 422, 429})
_CONTRACT_CODE: Final = "engine_contract_error"
_RERUN_HINT: Final = (
    "The SDK does not send the call again, because the run can have a cost. "
    "Call again only if a second cost is acceptable."
)


@dataclass(frozen=True, slots=True)
class _Envelope:
    message: str
    code: str | None
    param: str | None


def refusal_error(response: httpx.Response, trace_id: str) -> ScreamingFaceError:
    """The error of an answer that is not 200 (C2.2, C2.4).

    INVARIANT: the caller has read the body (response.read()) before this call.
    """

    status, headers = response.status_code, response.headers
    envelope = _envelope(response.content)
    if envelope is None and status in _NO_ROUTE_STATUSES:
        # WHY: an Engine with no chat route answers the plain 404 or 405 of its framework. The
        # chat route answers with the OpenAI envelope, so the envelope tells the two apart.
        return _no_chat_route(status, trace_id)
    kind, permanent, fallback = _kind(status, headers)
    message = envelope.message if envelope is not None else f"HTTP {status}"
    code = (envelope.code if envelope is not None else None) or fallback
    return kind(
        f"The SF Engine answered the chat call with HTTP {status}: {message}",
        code=code,
        status=status,
        permanent=permanent,
        details=_details(envelope, response),
        trace_id=trace_id,
    )


def _kind(status: int, headers: httpx.Headers) -> tuple[type[ScreamingFaceError], bool, str | None]:
    result: tuple[type[ScreamingFaceError], bool, str | None]
    if status in _AUTH_STATUSES:
        result = (AuthenticationError, True, None)
    elif status in _REFUSAL_STATUSES:
        result = (PlanningError, True, None)
    elif status in _RUN_STATUSES or status >= 500:
        result = (ExecutionError, not _should_retry(headers), None)
    else:
        # WHY: a status that C2.4 does not name is not a contract answer of the chat route.
        result = (ExecutionError, True, _CONTRACT_CODE)
    return result


def _should_retry(headers: httpx.Headers) -> bool:
    return headers.get("x-should-retry", "").strip().lower() == "true"


def _details(envelope: _Envelope | None, response: httpx.Response) -> dict[str, object] | None:
    details: dict[str, object] = {}
    if envelope is not None and envelope.param is not None:
        details["param"] = envelope.param
    # WHY the SDK parser: it reads both forms of Retry-After (seconds and HTTP date), as the other
    # Engine calls do (_engine/admission.py, _cache/remote.py).
    retry_after = _retry_after_seconds(response)
    if retry_after is not None:
        details["retry_after"] = retry_after
    return details or None


def _envelope(body: bytes) -> _Envelope | None:
    """The message, code and param of the OpenAI error envelope, or None when there is none."""

    try:
        document: object = json.loads(body)
    except (ValueError, RecursionError):
        return None
    error = document.get("error") if isinstance(document, dict) else None
    if not isinstance(error, dict) or not isinstance(error.get("message"), str):
        return None
    code, param = error.get("code"), error.get("param")
    return _Envelope(
        error["message"],
        code if isinstance(code, str) else None,
        param if isinstance(param, str) else None,
    )


def _no_chat_route(status: int, trace_id: str) -> EngineCapabilityError:
    return EngineCapabilityError(
        "This SF Engine does not serve the OpenAI chat route",
        status=status,
        permanent=True,
        details={"route": CHAT_ROUTE},
        hint=(
            "Upgrade the SF Engine (or the local stack) to a version that serves "
            "POST /v1/chat/completions."
        ),
        trace_id=trace_id,
    )


def stream_error(event: StreamError, trace_id: str) -> ExecutionError:
    """The error of the error event of a stream that had started (C2.3, C4.1)."""

    details = None if event.retry_after is None else {"retry_after": event.retry_after}
    # WHY: 'is not True' and not 'is False': an event with no should_retry key comes from an
    # Engine before contracts C4.1, and that error is permanent.
    return ExecutionError(
        f"The SF Engine stopped the chat run: {event.message}",
        code=event.code,
        permanent=event.should_retry is not True,
        details=details,
        trace_id=trace_id,
    )


def invalid_response(reason: FrameErrorReason, trace_id: str) -> ExecutionError:
    """The error of a chat stream with a wrong form (C2.3)."""

    return ExecutionError(
        "The SF Engine sent a chat stream with a wrong form",
        code="invalid_response",
        permanent=True,
        details={"reason": reason},
        hint=_RERUN_HINT,
        trace_id=trace_id,
    )


def outcome_unknown(trace_id: str) -> ExecutionError:
    """The error of a connection that failed after the chat call was sent."""

    # WHY: not EngineUnavailableError. The request was sent, so the run can have started and can
    # have a cost.
    return ExecutionError(
        "The connection to the SF Engine failed after the chat call was sent; "
        "the run can have a cost",
        code="inference_outcome_unknown",
        permanent=True,
        hint=_RERUN_HINT,
        trace_id=trace_id,
    )


def client_timeout(trace_id: str) -> ExecutionError:
    """The error of a chat call that passed the time limit of the caller."""

    return ExecutionError(
        "The chat call did not finish in the time limit that you set (timeout=)",
        code="client_timeout",
        permanent=True,
        hint=_RERUN_HINT,
        trace_id=trace_id,
    )


def engine_unavailable(engine_url: str, trace_id: str) -> EngineUnavailableError:
    """The error of a chat call that was never sent, because the Engine was not reached."""

    return EngineUnavailableError(
        "Could not reach the SF Engine for the chat call",
        engine_url=engine_url,
        trace_id=trace_id,
    )
