"""The route-facing seam for OME-303 per-observed-attempt usage accounting.

FEATURE: default-on evidence for non-streaming ``POST /v1/chat/completions`` calls.

STORY: as a benchmark operator I receive every observed
local provider attempt, canonical usage and provider-authored cost evidence. Cache replay
is labelled historical evidence rather than current spend or counterfactual savings.

INVARIANT: accounting activation is gateway-owned and never enters the request body or the
OME-305 effective request/cache key. Streaming bypasses accounting until the gateway can
observe SSE usage without consuming or delaying the caller's stream.

INVARIANT (§6): metadata is attached to a COPY, and only after the request cache has
stored the provider's own JSON. See ``attach_success_metadata``.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Final, Literal

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse

from aigateway.call_context import current_call_id, current_trace_id, new_gateway_call_id

from ...core.usage_accounting.hooks import AccountingAsyncHTTPHandler
from ...core.usage_accounting.signals import bound_collector
from .classify import classify_conversion_failure, classify_transport_failure
from .collector import RequestAccountingCollector
from .render import (
    CacheStatusWord,
    attach_metadata,
    merged_error_detail,
    render_aigw_metadata,
)
from .types import CacheReference, ProviderUsageAccountingEvidence, UsageAccountingStrategy

logger = logging.getLogger(__name__)

_STATE_ATTR: Final = "aigw_accounting"

__all__ = [
    "AccountingSession",
    "accounting_error_response",
    "attach_hit_metadata",
    "attach_success_metadata",
    "begin_accounting",
    "bound_dispatch",
    "finalize_provider_evidence",
    "note_dispatch_failure",
    "usage_accounting_strategy_for",
]


@dataclass
class AccountingSession:
    """Everything the route needs to account for one non-streaming caller request."""

    provider: str
    supported: bool
    collector: RequestAccountingCollector | None
    gateway_call_id: str
    inject_shared_handler: bool
    dispatch_count: int = 0
    cache_status: CacheStatusWord = "bypass"

    def note_dispatch(self) -> None:
        """One gateway/plugin dispatch attempt is starting (an overload retry is a new one)."""
        self.dispatch_count += 1
        if self.collector is not None:
            self.collector.begin_dispatch()


def usage_accounting_strategy_for(plugin: object | None) -> UsageAccountingStrategy:
    """Resolve an optional provider contribution with a safe unsupported default."""
    if plugin is None:
        return UsageAccountingStrategy.unsupported()
    contribution = getattr(plugin, "usage_accounting_strategy", None)
    if not callable(contribution):
        return UsageAccountingStrategy.unsupported()
    strategy = contribution()
    if type(strategy) is UsageAccountingStrategy:
        return strategy
    logger.warning(
        "provider usage-accounting strategy is invalid provider=%s",
        getattr(plugin, "custom_llm_provider", "unknown"),
    )
    return UsageAccountingStrategy.unsupported()


def begin_accounting(
    request: Request, *, plugin: object | None, provider: str, model: str
) -> AccountingSession | None:
    """Open a session for a non-streaming request.

    Called BEFORE the cache stage so a hit still renders metadata — but note that the
    collector exists only to hold records, and a hit creates none. Nothing here reads a
    credential, dispatches, or touches the request body.
    """
    taxonomy = getattr(
        getattr(getattr(request, "app", None), "state", None), "taxonomy_plugin", None
    )
    if taxonomy is not None and not taxonomy.enabled:
        return None
    try:
        strategy = usage_accounting_strategy_for(plugin)
    except Exception:
        logger.warning("provider usage-accounting strategy failed provider=%s", provider)
        strategy = UsageAccountingStrategy.unsupported()
    # FEATURE (OME-938): the id is MINTED BY MIDDLEWARE and consumed here, not the other way
    # round. It used to be minted by the collector, which made correlation a side effect of
    # usage accounting — and this function returns None when the taxonomy plugin is disabled
    # (line 105), so `AIGW_TAXONOMY_ENABLED=false` silently deleted the gateway's only
    # correlation mechanism.
    #
    # INVARIANT: ONE id per request, shared by the response body and every log line. Letting the
    # collector mint its own would put a different id in `_aigw.gateway_call_id` than the logs
    # carry — two ids for one call, both looking correct, which is worse than none.
    #
    # `or new_gateway_call_id()`: a session can be built outside any request (unit tests
    # constructing one directly), and a missing id there must not be an error.
    call_id = current_call_id() or new_gateway_call_id()
    collector = (
        RequestAccountingCollector(
            provider=provider,
            requested_model=model,
            transport=strategy.capability,
            gateway_call_id=call_id,
        )
        if strategy.is_supported
        else None
    )
    session = AccountingSession(
        provider=provider,
        supported=strategy.is_supported,
        collector=collector,
        gateway_call_id=call_id,
        inject_shared_handler=strategy.uses_shared_litellm_http,
    )
    # Published so the app-wide HTTPException handler can render `_aigw` beside `detail`
    # for EVERY safe terminal error, including ones raised long before dispatch.
    setattr(request.state, _STATE_ATTR, session)
    # §9.24: the id is logged here so an operator can correlate a response with gateway
    # logs. Without this line `gateway_call_id` would be response-local only.
    logger.info(
        "usage accounting started provider=%s gateway_call_id=%s supported=%s",
        provider,
        session.gateway_call_id,
        session.supported,
    )
    return session


def session_for(request: Request) -> AccountingSession | None:
    return getattr(request.state, _STATE_ATTR, None)


def dispatch_body_with_accounting(
    body: dict[str, Any], session: AccountingSession | None, handler: Any
) -> dict[str, Any]:
    """Inject the gateway's observed LiteLLM client for an accounted dispatch.

    INVARIANT: injected ONLY for an accounted non-streaming request whose provider declared
    ``litellm_async_http``. Streaming and unsupported providers keep their existing client
    selection.

    INVARIANT: a fresh dict. The caller's ``body`` is the one the cache keyed; a dispatch
    control written into it would leak into that identity.
    """
    if (
        session is None
        or session.collector is None
        or not session.inject_shared_handler
        or handler is None
    ):
        return body
    out = dict(body)
    out["client"] = handler
    return out


def accounting_handler(request: Request) -> AccountingAsyncHTTPHandler | None:
    """The app-lifetime observed handler, if the app built one."""
    taxonomy = getattr(request.app.state, "taxonomy_plugin", None)
    if taxonomy is not None:
        return taxonomy.handler
    return getattr(request.app.state, "usage_accounting_handler", None)


def bound_dispatch(session: AccountingSession | None):
    """Bind the collector for the duration of a dispatch, or do nothing.

    The handler is app-lifetime and shared; this binding is what makes its hooks write
    to THIS caller's records and no one else's.
    """
    if session is None or session.collector is None:
        return _NullBinding()
    return bound_collector(session.collector)


class _NullBinding:
    def __enter__(self) -> None:
        return None

    def __exit__(self, *_exc: object) -> Literal[False]:
        return False


def safe_request_view(body: Mapping[str, Any]) -> Mapping[str, Any]:
    """The only part of the dispatch body a provider mapper may see.

    INVARIANT: mappers never receive credentials or prompt content. By the time the
    route finalizes evidence, ``body`` carries the injected provider credential and the
    caller's full ``messages``; handing that to a plugin hook would give evidence
    normalization access to both, for no reason — it needs neither to read a ``usage``
    block. Least privilege, enforced structurally rather than by convention.
    """
    return {
        key: value
        for key, value in body.items()
        if key not in _MAPPER_HIDDEN_FIELDS and not isinstance(value, (list, dict))
    }


# Credentials, prompt content and transport controls. The value-shape filter above also
# drops anything structured, so a nested prompt cannot arrive through a new field name.
_MAPPER_HIDDEN_FIELDS: Final = frozenset(
    {"api_key", "messages", "system", "headers", "extra_headers", "client", "metadata"}
)


def finalize_provider_evidence(
    session: AccountingSession | None,
    *,
    plugin: object,
    request_body: Mapping[str, Any],
    final_response: Mapping[str, Any] | None,
) -> None:
    """Run the provider's pure mapper over each observed send's own raw evidence.

    The LAST succeeded send additionally receives ``final_response`` as a fallback: it is
    the one whose body became the caller's answer, so it is the only record for which the
    converted shape describes the same call.

    INVARIANT: totally non-raising. A mapper bug must never fail a completed provider
    response; it degrades the record to incomplete instead.
    """
    if session is None or session.collector is None:
        return
    collector = session.collector
    observed = collector.open_records()
    last_success = next(
        (call_id for call_id, _raw, ok in reversed(observed) if ok),
        None,
    )
    for call_id, raw_evidence, succeeded in observed:
        try:
            contribution = getattr(plugin, "normalize_chat_usage_accounting")
            evidence = contribution(
                request_body=request_body,
                raw_response=raw_evidence,
                final_response=final_response if call_id == last_success else None,
                failed=not succeeded,
            )
        except Exception:
            logger.warning(
                "provider usage-accounting mapper failed provider=%s gateway_call_id=%s",
                session.provider,
                session.gateway_call_id,
            )
            continue
        if type(evidence) is not ProviderUsageAccountingEvidence:
            logger.warning(
                "provider usage-accounting mapper returned invalid evidence "
                "provider=%s gateway_call_id=%s",
                session.provider,
                session.gateway_call_id,
            )
            continue
        collector.apply_evidence(call_id, evidence)


def note_conversion_failure(session: AccountingSession | None) -> None:
    """The provider answered but local conversion of its response failed (§9.20)."""
    if session is None or session.collector is None:
        return
    outcome, failure_code = classify_conversion_failure()
    session.collector.mark_conversion_failed(outcome, failure_code)


def note_dispatch_failure(
    session: AccountingSession | None,
    exc: BaseException,
    *,
    provider_error_after_response: bool = False,
) -> None:
    """Finalize a transport escape or an HTTP-200 body rejected by provider validation."""
    if session is None or session.collector is None:
        return
    outcome, failure_code = classify_transport_failure(exc)
    finalized = session.collector.finalize_last_open_failure(
        outcome=outcome, failure_code=failure_code
    )
    if finalized:
        return
    if provider_error_after_response:
        session.collector.mark_last_succeeded_provider_error()
    else:
        session.collector.mark_last_succeeded_indeterminate()


def _metadata(
    session: AccountingSession,
    *,
    cache_status: CacheStatusWord,
    cache_reference: CacheReference | None = None,
) -> dict[str, Any]:
    return render_aigw_metadata(
        trace_id=current_trace_id(),
        collector=session.collector,
        supported=session.supported,
        cache_status=cache_status,
        gateway_call_id=session.gateway_call_id,
        cache_reference=cache_reference,
    )


def attach_success_metadata(
    result: dict[str, Any], session: AccountingSession | None, *, cache_status: CacheStatusWord
) -> dict[str, Any]:
    """Return an accounted response body on a miss/bypass.

    INVARIANT (§6): this runs AFTER ``store_global_response``. Two independent reasons —
    the cache row must stay provider-compatible for every future replay, and
    ``store_global_response`` measures ``response_size_bytes`` against what it is given,
    so attaching first could push an otherwise cacheable response over the size cap and
    silently cost the deployment a cache entry.
    """
    if session is None:
        return result
    try:
        return attach_metadata(result, _metadata(session, cache_status=cache_status))
    except Exception:
        logger.warning(
            "usage accounting success rendering failed gateway_call_id=%s",
            session.gateway_call_id,
        )
        return result


def _restore_cached_json_numbers(value: Any) -> Any:
    """Undo the cache reader's Decimal precision carrier before serving JSON."""
    if type(value) is Decimal:
        return float(value)
    if type(value) is dict:
        restored = {key: _restore_cached_json_numbers(item) for key, item in value.items()}
        return value if all(restored[key] is item for key, item in value.items()) else restored
    if type(value) is list:
        restored_list = [_restore_cached_json_numbers(item) for item in value]
        return (
            value
            if all(new is old for new, old in zip(restored_list, value, strict=True))
            else restored_list
        )
    return value


def attach_hit_metadata(
    cached: dict[str, Any], session: AccountingSession | None, *, plugin: object
) -> dict[str, Any]:
    """Return an accounted response body on a cache HIT.

    INVARIANT: ``attempts`` is empty and ``observed_new_attempts`` is ``0``.
    A hit performs no provider dispatch, so a synthetic record here would report spend
    that did not happen. Limited historical evidence goes under ``cache.reference`` and
    is structurally marked as not incurred by the current request.

    INVARIANT: ``cached`` is the store's replayed row. It is copied, never mutated.
    """
    response = _restore_cached_json_numbers(cached)
    if session is None:
        return response
    reference: CacheReference | None = None
    try:
        contribution = getattr(plugin, "cache_reference_from_cached_response")
        reference = contribution(cached)
    except Exception:
        logger.warning(
            "cache-reference mapper failed provider=%s gateway_call_id=%s",
            session.provider,
            session.gateway_call_id,
        )
    if reference is not None and type(reference) is not CacheReference:
        logger.warning(
            "cache-reference mapper returned invalid evidence provider=%s gateway_call_id=%s",
            session.provider,
            session.gateway_call_id,
        )
        reference = None
    try:
        return attach_metadata(
            response, _metadata(session, cache_status="hit", cache_reference=reference)
        )
    except Exception:
        logger.warning(
            "usage accounting cache-hit rendering failed gateway_call_id=%s",
            session.gateway_call_id,
        )
        return response


def accounting_error_response(request: Request, exc: HTTPException) -> JSONResponse | None:
    """A safe terminal error body carrying ``_aigw`` beside ``detail``, or ``None``.

    ``None`` means the request has no accounting session, including non-chat and streaming
    paths; the caller gets the route's unchanged error shape.

    INVARIANT: only the already-sanitized ``exc.detail`` is echoed. Raw provider bodies,
    prompts, generated text, credentials, headers and tracebacks are excluded upstream
    of here and nothing in the metadata can reintroduce them.
    """
    session = session_for(request)
    if session is None:
        return None
    try:
        return JSONResponse(
            status_code=exc.status_code,
            content=merged_error_detail(
                exc.detail, _metadata(session, cache_status=session.cache_status)
            ),
            headers=dict(exc.headers or {}),
        )
    except Exception:
        # INVARIANT: accounting may never make an error worse than it already was. This
        # renderer is reached from an APP-WIDE exception handler, so a failure here
        # would break error responses on every route in the gateway, not just this one.
        # Returning None falls back to Starlette's untouched handler.
        logger.warning(
            "accounting error rendering failed gateway_call_id=%s", session.gateway_call_id
        )
        return None
