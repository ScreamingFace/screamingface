"""POST /v1/classifications — one text classification by a provider's configured classifier.

# FEATURE: hosted BYOM Unit 3 — an account sends a classifier ID and a text; the Gateway calls the
# classifier with that account's own Connection and returns its labels and scores unchanged.
# INVARIANT (spec G6): the chat route's order — body shape, the provider prefix and registry, the
# INVOKE grant, the classifier, credential resolve and authorize through `ProviderAccess`, then
# dispatch under the provider budgets with the shared overload retry. No key is read and nothing
# is sent upstream before every earlier step has passed.
# INVARIANT: the grant precedes the classifier check, so an ungranted caller cannot probe aliases;
# an ungranted or disabled provider is answered exactly as an absent one.
# INVARIANT: no chat module is imported; the credential steps are the same plain port calls.
# INVARIANT (spec G9): neither the global cache nor usage accounting takes part.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from fastapi import APIRouter, HTTPException, Request

from ..core.admission import dispatch_with_budgets
from ..core.auth.middleware import CurrentAccount
from ..core.endpoint_access import EndpointOperation, permits
from ..core.provider_access import apply_authorization, provider_access_for
from ..core.retry import RetryPolicy, with_overload_retry
from ..tracing import provider_span
from .provider_access_http import refusals_as_http, selector_from_request

logger = logging.getLogger(__name__)
router = APIRouter()

_FIELDS = frozenset({"model", "input"})
# The gateway's own status for a caller that left mid-call; no client ever receives it.
_CLIENT_DISCONNECTED = 499


@router.post("/v1/classifications")
async def create_classification(request: Request, current: CurrentAccount) -> dict[str, Any]:
    with refusals_as_http():
        selector = selector_from_request(request)
    model, text = await _model_and_input(request)
    provider = model.split("/", 1)[0] if "/" in model else ""
    if not provider:
        raise HTTPException(status_code=400, detail="model must be provider-prefixed")

    account_id = str(current.id)
    plugin = request.app.state.providers.get(provider)
    if plugin is None or not permits(
        request.app, provider, account_id=account_id, operation=EndpointOperation.INVOKE
    ):
        raise HTTPException(status_code=400, detail=f"unknown provider: {provider}")
    if model not in {entry.model_name for entry in plugin.register_classifiers()}:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "invalid_model",
                "message": "model is not a configured classifier of this provider",
            },
        )

    access = provider_access_for(request.app)
    body: dict[str, Any] = {"model": model, "input": text}
    with refusals_as_http():
        target = await access.resolve(account_id, provider, selector, plugin=plugin)
        access.auth_mode(target, plugin)
        authorization = await access.authorize(target, plugin=plugin, provider=provider)
    apply_authorization(body, authorization.headers)
    return await dispatch_classification(request, plugin, provider, body)


async def _model_and_input(request: Request) -> tuple[str, str]:
    """The two body fields; every other shape is refused before any provider is looked up."""
    try:
        body = await request.json()
    except (ValueError, RecursionError):
        # WHY RecursionError: a small body of deeply nested brackets exhausts the decoder's
        # depth; it is the caller's malformed body, not a server fault.
        raise HTTPException(status_code=400, detail="request body must be valid JSON") from None
    if isinstance(body, dict) and body.keys() - _FIELDS:
        # INVARIANT: a refusal names the unknown fields, never a caller value.
        raise HTTPException(
            status_code=400,
            detail={
                "code": "unsupported_parameters",
                "rejected": {name: "unknown" for name in sorted(body.keys() - _FIELDS)},
                "message": "a classification takes only a model and an input",
            },
        )
    if not (
        isinstance(body, dict)
        and isinstance(body.get("model"), str)
        and isinstance(body.get("input"), str)
    ):
        raise HTTPException(
            status_code=400,
            detail={
                "code": "invalid_request",
                "message": "model and input are required strings",
            },
        )
    model, text = body["model"], body["input"]
    if not (_utf8(model) and _utf8(text)):
        # WHY here: a JSON `\ud800` escape decodes to a lone surrogate, which no UTF-8 request
        # can carry; refused later, it would fail at send time as the provider's 502.
        raise HTTPException(
            status_code=400,
            detail={
                "code": "invalid_request",
                "message": "model and input must be valid Unicode text",
            },
        )
    return model, text


def _utf8(value: str) -> bool:
    # INVARIANT: checked as is; nothing is replaced, and the value never reaches the answer.
    try:
        value.encode("utf-8")
    except UnicodeEncodeError:
        return False
    return True


async def dispatch_classification(
    request: Request, plugin: Any, provider: str, body: dict[str, Any]
) -> dict[str, Any]:
    """Run ``plugin.classify`` under the provider budgets and the shared overload retry.

    # INVARIANT: the retry wraps the upstream call only; the credential steps ran once before it.
    # INVARIANT: one record per failed call — provider, code, status and the exception's type
    # name; never a body, the key or the input. An unexpected error is the sanitized 502.
    """
    policy = RetryPolicy.from_settings(request.app.state.settings)
    try:
        with provider_span(provider):
            return await _dispatch(
                request,
                provider,
                lambda: with_overload_retry(lambda: plugin.classify(body), policy=policy),
            )
    except HTTPException as exc:
        _log_failure(provider, exc, type(exc).__name__)
        raise
    except Exception as exc:
        failure = HTTPException(
            status_code=502,
            detail={
                "code": "provider_error",
                "message": "The upstream provider returned an error.",
            },
        )
        _log_failure(provider, failure, type(exc).__name__)
        raise failure from None


async def _dispatch(
    request: Request, provider: str, call: Callable[[], Awaitable[dict[str, Any]]]
) -> dict[str, Any]:
    try:
        return await dispatch_with_budgets(request, provider, call)
    except asyncio.CancelledError:
        if not getattr(request.state, "provider_disconnect_cancelled", False):
            raise
        work = asyncio.current_task()
        assert work is not None
        # INVARIANT: consume only the disconnect watcher's cancellation; a concurrent shutdown or
        # caller cancellation still reaches the ASGI server.
        if work.uncancel():
            raise
        raise HTTPException(
            status_code=_CLIENT_DISCONNECTED,
            detail={"code": "client_disconnected", "message": "The client disconnected."},
        ) from None


def _log_failure(provider: str, exc: HTTPException, error_type: str) -> None:
    detail: Any = exc.detail
    code = detail.get("code") if isinstance(detail, dict) else None
    if exc.status_code == _CLIENT_DISCONNECTED:
        level = logging.INFO
    else:
        level = logging.ERROR if exc.status_code >= 500 else logging.WARNING
    logger.log(
        level,
        "classification failed provider=%s code=%s status=%d type=%s",
        provider,
        code if isinstance(code, str) else "unclassified",
        exc.status_code,
        error_type,
    )
