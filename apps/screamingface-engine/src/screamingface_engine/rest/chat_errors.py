"""The OpenAI error envelope of POST /v1/chat/completions, with fixed messages.

WHY fixed messages: no provider text and no client text reaches a caller through this envelope,
with one exception: `model_does_not_support_tools` (TC-S10) names the model id of a final step,
a route parsed from the client's recipe. Each code has one message in FIXED_MESSAGES; a code
without one gets the generic run failure.
"""

from fastapi.responses import JSONResponse

from screamingface_engine.auth import ProblemException
from screamingface_engine.chat.wire import ErrorBody, ErrorEnvelope
from screamingface_engine.rest.stopping import QUEUE_UNAVAILABLE_RETRY_AFTER_S
from screamingface_engine.runner_queue import RunQueueUnavailable
from url4.streaming.interfaces import JobRunnerAtCapacity

__all__ = [
    "FIXED_MESSAGES",
    "RESTART_RETRY_AFTER_S",
    "ChatError",
    "error_type",
    "fixed_message",
    "from_problem",
    "restart_retry_after",
]

# WHY: an OpenAI SDK with no Retry-After retries after about one second, into the same restart.
# The retryable 503 answers of a failed run, a draining worker and a restarting App send this.
RESTART_RETRY_AFTER_S = 5

FIXED_MESSAGES: dict[str, str] = {
    "unsupported_media_type": "Content-Type must be application/json",
    "identity_required": "a verified caller identity is required",
    "server_restarting": "the server is restarting; retry the request",
    "chat_unavailable": "chat completions are not available on this Engine",
    "request_too_large": "the request is too large",
    "request_timeout": "the request body did not arrive in time",
    "client_disconnected": "the client closed the connection",
    "invalid_request": "the request body is not valid",
    "unsupported_parameter": "this parameter is not supported",
    "unsupported_content": "only inline data: URIs are supported for pictures and files",
    "tools_not_available": (
        "tool calls are not available yet; remove the tools and the tool messages from the request"
    ),
    "model_not_found": "the model is not known",
    "catalog_unavailable": "the model catalog is not available",
    "overloaded": "the server is at capacity; retry shortly",
    "queue_unavailable": "the run queue is unavailable; retry shortly",
    "internal_error": "the request failed",
    "timeout": "the request did not finish in time; the run was stopped",
    "result_unavailable": "the result of the run could not be read",
    "result_invalid": "the result of the run is not valid",
    "result_too_large": "the result of the run is too large",
    "run_failed": "the run failed; retry the request",
    "worker_draining": "the worker is restarting; retry the request",
}


def fixed_message(code: str) -> str:
    """The fixed message of a code, or the generic run failure for an unknown code."""
    return FIXED_MESSAGES.get(code, "the run failed")


def error_type(status: int) -> str:
    """The OpenAI ``type`` of an error status."""
    if status == 429:
        return "rate_limit_error"
    if 400 <= status < 500:
        return "invalid_request_error"
    return "server_error"


class ChatError(Exception):
    """One refusal or failure of a chat request, answered in the OpenAI envelope."""

    def __init__(
        self,
        status: int,
        code: str,
        message: str | None = None,
        *,
        param: str | None = None,
        retry_after: int | None = None,
        should_retry: bool = False,
    ) -> None:
        self.status = status
        self.code = code
        self.message = message or fixed_message(code)
        self.param = param
        self.retry_after = retry_after
        self.should_retry = should_retry
        super().__init__(code)

    def response(self) -> JSONResponse:
        """The envelope as a response, with ``x-should-retry`` and, when given, ``Retry-After``."""
        body = ErrorEnvelope(
            error=ErrorBody(
                message=self.message,
                type=error_type(self.status),
                param=self.param,
                code=self.code,
            )
        ).model_dump(mode="json")
        headers = {"x-should-retry": "true" if self.should_retry else "false"}
        if self.retry_after is not None:
            headers["Retry-After"] = str(self.retry_after)
        return JSONResponse(content=body, status_code=self.status, headers=headers)


def restart_retry_after(status: int, should_retry: bool) -> int | None:
    """The Retry-After of a run or wait answer: only a retryable 503 has one."""
    return RESTART_RETRY_AFTER_S if status == 503 and should_retry else None


def _retry_after(headers: dict[str, str] | None, default: int) -> int:
    """The ``Retry-After`` that the problem carries, or `default` when it is missing or not whole
    seconds (a problem built by hand can have no headers)."""
    value = (headers or {}).get("Retry-After", "")
    return int(value) if value.isdigit() else default


def from_problem(exc: ProblemException) -> ChatError:
    """Re-envelope a problem raised by the scheduler (CC-S36, Q3).

    A full runner is a 429 ``overloaded``; a broken queue is a 503 ``queue_unavailable``; any
    other problem keeps its status with the fixed ``internal_error`` message.
    """
    cause = exc.__cause__
    if isinstance(cause, JobRunnerAtCapacity):
        return ChatError(
            429, "overloaded", retry_after=_retry_after(exc.headers, 1), should_retry=True
        )
    if isinstance(cause, RunQueueUnavailable):
        return ChatError(
            503,
            "queue_unavailable",
            retry_after=_retry_after(exc.headers, QUEUE_UNAVAILABLE_RETRY_AFTER_S),
            should_retry=True,
        )
    return ChatError(exc.problem.status, "internal_error", should_retry=False)
