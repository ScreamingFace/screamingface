"""The OAuth callback endpoints, and the code-exchange endpoint.

Every path a provider may redirect to, plus the explicit exchange endpoint for callers
that carry their own redirect. Each is a thin adapter over the completion coordinator in
:mod:`aigateway.routes.auth` — deliberately thin, because "which URL the provider was
told to use" is deployment shape, not behaviour.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from ..core.auth.middleware import CurrentAccount
from ..core.credential_blob.store import CredentialBlobMutationConflict
from .auth import _complete_oauth_for_app
from .auth_context import _pending
from .oauth_loopback import _CALLBACK_HTML, _callback_failure_html

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/callback")
async def oauth_callback(code: str, state: str, request: Request):
    """Provider-agnostic OAuth callback.

    This route intentionally does not require a JWT because OAuth providers
    redirect browser tabs here after the user leaves the app. The pending-auth
    state nonce is the callback credential; it maps back to the initiating
    account and profile.

    Some public OAuth clients require a fixed localhost callback path. We
    dispatch to the correct provider by looking up the ``state`` value in the
    pending-auth table.
    """
    pending_entry = _pending(request).peek(state)
    if pending_entry is None:
        raise HTTPException(
            status_code=400,
            detail={"code": "unknown_state", "message": "OAuth state not recognized or expired"},
        )
    provider = pending_entry.provider
    try:
        return await _generic_callback(provider, code, state, request)
    except CredentialBlobMutationConflict:
        return HTMLResponse(
            _callback_failure_html(
                provider,
                "profile_index_conflict",
                "Profile metadata update conflicted. Try again.",
            ),
            status_code=503,
        )
    except HTTPException as exc:
        return HTMLResponse(
            _callback_failure_html(provider, type(exc).__name__, str(exc.detail)),
            status_code=exc.status_code,
        )
    except Exception as exc:
        logger.error("OAuth callback failed for provider %s: %s", provider, type(exc).__name__)
        return HTMLResponse(
            _callback_failure_html(
                provider,
                type(exc).__name__,
                "OAuth callback failed. Try again.",
            ),
            status_code=500,
        )


@router.get("/auth/callback")
async def oauth_nested_callback(code: str, state: str, request: Request):
    return await oauth_callback(code, state, request)


@router.get("/oauth2callback")
async def oauth2_loopback_callback(code: str, state: str, request: Request):
    return await oauth_callback(code, state, request)


@router.get("/v1/auth/{provider}/callback")
async def provider_callback(provider: str, code: str, state: str, request: Request):
    """Unauthenticated OAuth callback protected by the pending-auth state nonce."""
    return await _generic_callback(provider, code, state, request)


async def _complete_oauth(
    provider: str,
    code: str,
    state: str,
    request: Request,
    current_account_id: str | None = None,
) -> None:
    await _complete_oauth_for_app(request.app, provider, code, state, current_account_id)


async def _generic_callback(provider: str, code: str, state: str, request: Request):
    await _complete_oauth(provider, code, state, request)
    return HTMLResponse(_CALLBACK_HTML)


class ExchangeCodeRequest(BaseModel):
    code: str
    state: str


@router.post("/v1/auth/{provider}/exchange-code")
async def exchange_code(
    provider: str,
    body: ExchangeCodeRequest,
    request: Request,
    current: CurrentAccount,
) -> dict:
    """Manual paste-code path for OAuth flows where the provider shows the
    authorization code on screen instead of redirecting.
    """
    await _complete_oauth(provider, body.code, body.state, request, str(current.id))
    return {"state": "authenticated"}
