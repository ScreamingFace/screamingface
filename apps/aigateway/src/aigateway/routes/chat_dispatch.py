"""Dispatch-side helpers for /v1/chat/completions.

Everything after the body is credential-sealed lives here: backpressure +
overload retry, LiteLLM-exception → HTTP mapping, dispatch-failure credential
marking, and SSE streaming. Split out of routes/chat.py (OME-428 Phase 1) behind
characterization tests; behavior is unchanged.

OME-305: request-cache planning and persistence live in ``chat_cache_stage``. The
global cache is consulted before provider credentials are resolved, so dispatch-side
helpers cannot participate in its key or storage lifecycle.
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
from collections.abc import Callable
from typing import Any, cast

import httpx
from fastapi import HTTPException, Request
from litellm.exceptions import Timeout

from ..core.admission import ProviderExecutionTimeout, dispatch_with_budgets
from ..core.credential_blob import DispatchObservation, OperationalOutcome
from ..core.http_status import valid_http_error_status
from ..core.provider_access import CredentialTarget, operational_access_for, provider_access_for
from ..core.retry import RetryPolicy, parse_retry_after_seconds, with_overload_retry
from ..tracing import provider_span
from .chat_accounting import note_conversion_failure

logger = logging.getLogger(__name__)


def _should_mark_profile_error_on_dispatch_status(plugin: Any, status_code: int) -> bool:
    checker = getattr(plugin, "should_mark_profile_error_on_dispatch_status", None)
    return bool(checker(status_code)) if callable(checker) else False


def _supports_operational_outcome_classification(plugin: Any) -> bool:
    return callable(getattr(plugin, "classify_dispatch_operational_outcome", None))


def _classified_operational_outcome(
    plugin: Any, status_code: int, detail: Any
) -> OperationalOutcome | None:
    classifier = getattr(plugin, "classify_dispatch_operational_outcome", None)
    if not callable(classifier):
        return None
    outcome = classifier(status_code, detail)
    return cast(OperationalOutcome | None, outcome)


async def _dispatch_failure_response(
    request: Request,
    exc: HTTPException,
    *,
    plugin: Any,
    target: CredentialTarget,
    observation: DispatchObservation | None = None,
) -> HTTPException:
    """Record classified operational outcomes or use the legacy error path.

    Shared by the HTTPException path and the LiteLLM-exception path. A migrated
    effective API-key target records only an adapter-classified outcome through
    its revision-fenced observation. Every unclassified failure, including one
    carrying an observation, falls through to legacy op 5 when the provider's
    status hook marks it; other targets retain existing lifecycle semantics.
    """
    access = provider_access_for(request.app)
    if observation is not None:
        operational_access = operational_access_for(request.app)
        outcome = _classified_operational_outcome(plugin, exc.status_code, exc.detail)
        if operational_access is not None and outcome is not None:
            try:
                rewritten = await operational_access.record_dispatch_outcome(
                    target, observation, outcome, exc.detail, plugin=plugin
                )
            except Exception as failure:
                logger.error(
                    "dispatch outcome persistence error type=%s status=%s",
                    type(failure).__name__,
                    exc.status_code,
                )
                return exc
            if rewritten is None:
                return exc
            return HTTPException(status_code=exc.status_code, detail=rewritten)

    if not _should_mark_profile_error_on_dispatch_status(plugin, exc.status_code):
        return exc
    rewritten = await access.record_dispatch_failure(
        target, exc.status_code, exc.detail, plugin=plugin
    )
    # `None` means the caller's own detail stands: a Connection target (whose failure body
    # gains no `reauth_url`) or no stored target at all.
    if rewritten is None:
        return exc
    return HTTPException(status_code=exc.status_code, detail=rewritten)


async def _safe_dispatch_failure_response(
    request: Request,
    exc: HTTPException,
    *,
    plugin: Any,
    provider: str,
    account_id: str,
    profile_name: str,
    target: CredentialTarget,
    observation: DispatchObservation | None = None,
    error_type: str | None = None,
) -> HTTPException:
    """Contain secondary failures while rendering/persisting dispatch errors.

    FEATURE (OME-968): also the ONE place a mapped dispatch failure is recorded. Every
    non-streaming dispatch failure branch in `routes/chat.py` already funnels through here
    with the final, sanitized exception in hand — so recording here gives exactly one
    terminal record per failing request without each branch having to remember to log.
    """
    handler_error_type: str | None = None
    try:
        final = await _dispatch_failure_response(
            request,
            exc,
            plugin=plugin,
            target=target,
            observation=observation,
        )
    except Exception as failure:
        # OME-1461: folded into the ONE terminal record below instead of a second ERROR line.
        handler_error_type = type(failure).__name__
        final = _unknown_provider_exception()
    log_dispatch_failure(
        final,
        provider=provider,
        error_type=error_type,
        account_id=account_id,
        profile_name=profile_name,
        handler_error_type=handler_error_type,
    )
    return final


def failure_classification(detail: Any) -> str:
    """The gateway-authored machine code of a failure, never its free text.

    INVARIANT: only a `code` the gateway or a plugin put in a structured detail is echoed. A
    string detail may carry provider-influenced text, so it is reduced to `unclassified`.
    """
    if isinstance(detail, dict):
        code = detail.get("code")
        if isinstance(code, str):
            return code
    return "unclassified"


def log_dispatch_failure(
    exc: HTTPException,
    *,
    provider: str,
    error_type: str | None,
    account_id: str,
    profile_name: str,
    handler_error_type: str | None = None,
) -> None:
    """Emit the terminal record of a failed non-streaming dispatch (OME-968).

    WHY ERROR for 5xx and WARNING for 4xx: an operator alerting on WARNING+ must see every
    failing call (the defect was ZERO records), while a caller's own bad request should not
    page anyone the way a provider outage does. The exceptions are `_record_level`'s.
    `gateway_call_id`/`trace_id` are NOT arguments: the OME-938 record factory stamps them
    from the request scope, as on every other line.
    INVARIANT: class-name-only — `error_type` is `type(exc).__name__`, never `str(exc)`, and
    `handler_error_type` likewise names only the class that broke failure handling.
    INVARIANT (OME-1461): exactly one record per failing call — a raising failure handler is
    `outcome=handler_error` on THIS line, never a line of its own.
    """
    outcome = "mapped" if handler_error_type is None else "handler_error"
    suffix = "" if handler_error_type is None else f" handler_type={handler_error_type}"
    classification = failure_classification(exc.detail)
    logger.log(
        _record_level(exc.status_code, classification),
        "dispatch failed provider=%s classification=%s status=%d type=%s account=%s profile=%s "
        "outcome=%s%s",
        provider,
        classification,
        exc.status_code,
        error_type or "HTTPException",
        account_id,
        profile_name,
        outcome,
        suffix,
    )


async def _record_dispatch_success(
    request: Request,
    *,
    plugin: Any,
    provider: str,
    account_id: str,
    profile_name: str,
    target: CredentialTarget,
    observation: DispatchObservation | None,
) -> None:
    if observation is None:
        return
    access = operational_access_for(request.app)
    if access is None:
        return
    try:
        await access.record_dispatch_outcome(target, observation, "connected", None, plugin=plugin)
    except Exception as failure:
        logger.error(
            "dispatch success observation error type=%s provider=%s account=%s profile=%s",
            type(failure).__name__,
            provider,
            account_id,
            profile_name,
        )


# WHY (OME-1461 log-level policy, reasons in docs/work/2026-10-02-ome-1461-*.md): 499 means the
# client left — nothing an operator can act on, so INFO (still countable, never alerting).
# 429 is back-pressure, not breakage: under overload it arrives one per rejected call, so
# WARNING keeps it visible without paging on ERROR.
_STATUS_LEVELS = {499: logging.INFO, 429: logging.WARNING}

# WHY (owner decision 2026-10-02): a 503 is levelled by ORIGIN, not status. The gateway's own
# back-pressure (#1153 / OME-1162 admission shedding) is expected overload volume → WARNING; an
# upstream 503 still failing after retries is an outage and must stay alertable → ERROR.
# INVARIANT: allowlist, fail loud — only a named gateway back-pressure code is downgraded; an
# unknown or provider-originated 503 keeps ERROR.
_GATEWAY_BACKPRESSURE_CODES = frozenset({"provider_queue_timeout"})


def _record_level(status: int, classification: str) -> int:
    if status == 503 and classification in _GATEWAY_BACKPRESSURE_CODES:
        return logging.WARNING
    default = logging.ERROR if status >= 500 else logging.WARNING
    return _STATUS_LEVELS.get(status, default)


def _retry_after_headers(exc: Exception) -> dict[str, str]:
    seconds = parse_retry_after_seconds(exc)
    if seconds is None:
        return {}
    # delta-seconds is an integer; round up so clients do not retry early.
    return {"Retry-After": str(math.ceil(seconds))}


async def _dispatch_with_backpressure(
    request: Request,
    plugin: Any,
    provider: str,
    body: dict[str, Any],
    *,
    on_dispatch: Callable[[], None] | None = None,
) -> Any:
    """Run ``plugin.chat_completion`` under the gateway's backpressure stack:
    a per-provider concurrency slot wrapping the overload-retry loop.

    The slot is held across retries so a provider's concurrent-pressure
    ceiling includes backoff time — preventing the thundering-herd quota
    re-exhaustion that pure reactive retry could not solve.

    ``on_dispatch`` (OME-303) fires once per ATTEMPT, immediately before the plugin is
    invoked. That is what lets a gateway overload retry be told apart from LiteLLM's own
    hidden in-``post()`` resend: the former bumps ``dispatch_index``, the latter only
    ``attempt_index``. Conflating the two is a plan §12 stop condition, so the hook
    belongs here — inside the retry loop — and not at the call site, which cannot see
    individual attempts.
    """
    settings = request.app.state.settings

    async def _attempt() -> Any:
        if on_dispatch is not None:
            on_dispatch()
        try:
            return await plugin.chat_completion(body)
        except (Timeout, httpx.TimeoutException):
            raise ProviderExecutionTimeout() from None

    # FEATURE (OME-1132): the provider call as a CHILD span — "which provider was slow",
    # answerable at last. Deliberately wraps the WHOLE block, slot wait and retries included,
    # because that is the wall-clock the caller experienced; per-attempt detail already lives
    # in the accounting record.
    #
    # WHY here and not in `plugins/taxonomy/collector.py`, which already measures this latency:
    # that plugin is gated by `AIGW_TAXONOMY_ENABLED`, so reusing its measurement would make an
    # accounting kill-switch silently delete the gateway's spans — the same coupling
    # `middleware/call_id.py` was written to undo for the correlation ids. One extra clock read
    # is the cheaper of the two costs.
    with provider_span(provider):
        try:
            return await dispatch_with_budgets(
                request,
                provider,
                lambda: with_overload_retry(_attempt, policy=RetryPolicy.from_settings(settings)),
            )
        except asyncio.CancelledError:
            if not getattr(request.state, "provider_disconnect_cancelled", False):
                raise
            work = asyncio.current_task()
            assert work is not None
            # INVARIANT: consume only the watcher's cancellation. Concurrent server
            # shutdown or caller cancellation must still propagate to the ASGI server.
            if work.uncancel():
                raise
            # WHY: a normal HTTP response lets middleware unwind without an ASGI
            # ERROR traceback; the client has gone and cannot receive this response.
            raise HTTPException(
                status_code=499,
                detail={"code": "client_disconnected", "message": "The client disconnected."},
            ) from None


# WHY (FINDING B): the client-facing message is gateway-authored per machine
# code — NEVER str(exc), which serializes the raw LiteLLM/provider text (and any
# secret embedded in it) into the response, logs, and (for a 401, via
# _dispatch_failure_response) persisted connection error state.
# INVARIANT: this generic sanitizer applies only to RAW LiteLLM/provider
# exceptions (route Branch B); errors already authored safely by gateway policy
# (route Branch A HTTPExceptions) keep their curated detail unchanged.
_PROVIDER_ERROR_MESSAGE = {
    "bad_request": "The upstream provider rejected the request.",
    "auth_required": "The stored provider credential was rejected.",
    "rate_limited": "The upstream provider is rate limiting requests.",
    "provider_unavailable": "The upstream provider is temporarily unavailable.",
    "provider_error": "The upstream provider returned an error.",
    # OME-927: a 402 (out of credits) is not a generic provider fault — the
    # status itself is safe to name (it carries no provider text), so the
    # dedicated message tells the caller they need to top up, without str(exc).
    "insufficient_credits": "The upstream provider reported insufficient credits.",
}


def _sanitized_provider_status(exc: Exception) -> int | None:
    """A validated provider HTTP error status (400-599), else ``None``.

    # WHY (FINDING B / blocker E): never ``int(status_code)`` — a malformed
    # provider status (e.g. 'not-a-status' or the Unicode '²') would raise and
    # 500. One strict shared validator (rejects bool/str/float) is used here and
    # by the OpenRouter plugin/provenance so the three sites cannot diverge.
    """
    try:
        status = getattr(exc, "status_code", None)
    except Exception:
        return None
    return valid_http_error_status(status)


def _provider_error_code(status: int, *, validated: bool) -> str:
    if status == 400:
        return "bad_request"
    if status == 401:
        return "auth_required"
    if status == 402:
        return "insufficient_credits"
    if status == 429:
        return "rate_limited"
    if validated and status >= 500:
        return "provider_unavailable"
    # An absent/malformed status resolves to 502 but stays "provider_error"
    # (mirrors the OpenRouter plugin's _embedded_error_exception): only a
    # provider-validated 5xx earns the more specific "provider_unavailable".
    return "provider_error"


def _litellm_http_exception(exc: Exception) -> HTTPException:
    status = _sanitized_provider_status(exc)
    resolved = status if status is not None else 502
    code = _provider_error_code(resolved, validated=status is not None)
    return HTTPException(
        status_code=resolved,
        detail={"code": code, "message": _PROVIDER_ERROR_MESSAGE[code]},
        headers=_retry_after_headers(exc),
    )


def convert_provider_response(
    provider_response: Any, session: Any = None, *, provider: str | None = None
) -> Any:
    """Render the provider's response object to a plain JSON-able body.

    OME-303 §9.20: when this fails the provider ANSWERED — and very likely billed — but
    the gateway could not render its answer. That is neither a provider error nor a
    transport error, and the distinction is what stops Engine from being told the
    provider rejected work it actually performed, which would under-count real spend.
    The classification itself is core-owned and provider-neutral.

    WHY this raises directly instead of going through ``_safe_dispatch_failure_response``:
    that path exists to flip a profile or OAuth connection to ERROR when a status means
    the stored credential is bad. A conversion failure says nothing about the credential
    — the call authenticated and succeeded — so marking the profile would disable a
    working connection because of a gateway-side bug.
    """
    dumpable = cast(Any, provider_response)
    try:
        result = dumpable.model_dump() if hasattr(dumpable, "model_dump") else provider_response
    except Exception as failure:
        # INVARIANT: type only. The exception text is provider-influenced.
        _log_conversion_failure(provider, type(failure).__name__)
        note_conversion_failure(session)
        raise _unknown_provider_exception() from None
    if not isinstance(result, dict):
        _log_conversion_failure(provider, "non_object")
        note_conversion_failure(session)
        raise _unknown_provider_exception() from None
    return result


def _log_conversion_failure(provider: str | None, error_type: str) -> None:
    # FEATURE (OME-968): the terminal record of this path, same fields as `dispatch failed`.
    # The status/classification are what `_unknown_provider_exception` renders.
    logger.error(
        "provider response conversion failed type=%s provider=%s classification=provider_error "
        "status=502",
        error_type,
        provider,
    )


def _unknown_provider_exception() -> HTTPException:
    return HTTPException(
        status_code=502,
        detail={"code": "provider_error", "message": _PROVIDER_ERROR_MESSAGE["provider_error"]},
    )


async def _stream(plugin: Any, body: dict[str, Any], *, provider: str | None = None):
    try:
        async for chunk in plugin.chat_completion_stream(body):
            payload = chunk.model_dump() if hasattr(chunk, "model_dump") else chunk
            yield f"data: {json.dumps(payload)}\n\n"
        yield "data: [DONE]\n\n"
    except Exception as exc:
        # INVARIANT: provider-controlled exception text and traceback data stay out of logs.
        # FEATURE (OME-968): the terminal record of a failed stream. `status=200` is the
        # truth, not a typo: the status line was committed before the first chunk, so the
        # failure travels in the SSE error frame and this record is the only place it is
        # attributable (the call id is stamped from the request scope, which the pure-ASGI
        # `CallIdMiddleware` keeps bound for the whole stream).
        logger.error(
            "stream failed type=%s plugin=%s provider=%s classification=provider_error status=200",
            type(exc).__name__,
            type(plugin).__name__,
            provider,
        )
        err = {
            "error": {
                "code": "provider_error",
                "message": _PROVIDER_ERROR_MESSAGE["provider_error"],
            }
        }
        yield f"data: {json.dumps(err)}\n\n"
