from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from html import escape
from ipaddress import ip_address
from typing import Any, cast
from urllib.parse import parse_qs, urlencode, urlsplit
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, ConfigDict, SecretStr
from tortoise.exceptions import IntegrityError
from tortoise.transactions import in_transaction

from ..core.auth.middleware import CurrentAccount
from ..core.credential_blob.store import CredentialBlobMutationConflict
from ..core.credential_strategy_cache import credential_strategy_cache
from ..core.errors import AuthError, CredentialNotFoundError
from ..core.oauth.store import (
    OAuthConnectionStore,
    credential_key_for,
)
from ..core.oauth_pkce import generate_pkce, generate_state
from ..core.pending_auth import PendingAuthEntry
from ..core.plugin_base import (
    OAuthCodeExchangeRequest,
    OAuthConfig,
    credential_service_provider_for,
    credential_strategy_from,
)
from ..core.profile_index import ProfileIndexStore, ProfileTransitionConflict
from ..core.profile_models import (
    AuthType,
    Profile,
    ProfileDefaults,
    ProfileState,
    credential_name_for,
    profile_id_for,
)
from ..core.provider_access import (
    ProviderCredentialAdmin,
    ProviderUnknown,
    TargetMissing,
    WriteConflict,
    begin_connection_oauth,
    complete_connection_oauth,
    facade_target,
    fail_connection_oauth,
    patch_facade,
    provider_credential_admin_for,
    refresh_facade,
)
from .api_key_validation import normalize_api_key, require_valid_api_key
from .credential_persistence import (
    SupportsCredentialPersistence,
    SupportsCredentialSlot,
    persist_credentials_or_503,
)
from .provider_access_http import (
    legacy_delete_refusals_as_http,
    refusals_as_http,
    render_refusal,
)

logger = logging.getLogger(__name__)
router = APIRouter()


@dataclass(frozen=True)
class _LoopbackHttpRequest:
    method: str
    target: str
    headers: dict[str, str]


def _index_store(request: Request) -> ProfileIndexStore:
    return _index_store_for_app(request.app)


def _index_store_for_app(app) -> ProfileIndexStore:
    return app.state.profile_index


def _registry(request: Request):
    return _registry_for_app(request.app)


def _registry_for_app(app):
    return app.state.providers


def _credential_store_for_app(app):
    return app.state.credential_store


def _credential_admin(request: Request) -> ProviderCredentialAdmin:
    """The admin boundary the Profile management shells call (OME-1230, Stage A3)."""
    return provider_credential_admin_for(request.app)


def _projections(summaries) -> list[dict]:
    # COMPATIBILITY (window-only, Stage E): today's Profile JSON, from the summary's projection.
    return [summary.legacy_projection for summary in summaries]


def _credential_strategy_for_app(
    app,
    plugin,
    provider: str,
    account_id: str,
    name: str,
    auth_type: AuthType = "oauth",
):
    return _credential_strategy_for_credential_name(
        app,
        plugin,
        provider,
        credential_name_for(account_id, name),
        auth_type=auth_type,
    )


def _credential_strategy_for_credential_name(
    app,
    plugin,
    provider: str,
    credential_name: str,
    auth_type: AuthType = "oauth",
):
    return credential_strategy_from(
        plugin,
        credential_name,
        auth_type=auth_type,
        credential_store=_credential_store_for_app(app),
        http_client_factory=getattr(app.state, f"{provider}_http_factory", None),
    )


def _invalidate_profile_session(app, plugin, account_id: str, name: str) -> None:
    _invalidate_credential(app, plugin, credential_name_for(account_id, name))


def _invalidate_credential(app, plugin, credential_name: str) -> None:
    """Evict one credential name — the Profile address, or a migrated Connection's locator."""
    invalidator = getattr(plugin, "invalidate_profile_session", None)
    if callable(invalidator):
        invalidator(credential_name)
    # Drop the shared cached strategy so re-auth / api-key change / delete / refresh
    # never serve a stale in-memory token from a prior credential (SF-282).
    credential_strategy_cache(app).evict(credential_name)


@asynccontextmanager
async def _profile_refresh_lifecycle(
    request: Request,
    plugin,
    profile: Profile,
    provider: str,
    account_id: str,
    name: str,
) -> AsyncIterator[None]:
    """Shared profile state updates around provider-owned credential refresh."""
    # INVARIANT (OME-307 H-1): a manual refresh reads the profile, runs the provider network call,
    # then publishes the result. A delete that commits during that network window must WIN — a
    # deleted profile is never resurrected. The success branch publishes only while the profile
    # remains PRESENT (require_present); the error branch additionally fences on the snapshot below
    # (auth_type + last_refreshed_at) so a deleted/superseded profile is not recreated as a ghost
    # ERROR row. SCOPE (guard-now): require_present is presence-only, so a concurrent
    # re-authentication that keeps the profile present is NOT fenced out on the success path — the
    # stronger prepare-then-publish ownership split is deferred, outside this DELETE scope.
    expected_auth_type = profile.auth_type
    expected_last_refreshed_at = profile.last_refreshed_at
    try:
        yield
    except (CredentialNotFoundError, AuthError) as exc:
        # Error branch: fence on ownership and swallow a lost race (mirrors
        # chat_credentials._mark_profile_error_fresh) so a profile deleted or superseded during the
        # network window is never recreated as a ghost ERROR row.
        try:
            await _index_store(request).mark_authenticated_error(
                profile.id,
                expected_auth_type=expected_auth_type,
                expected_last_refreshed_at=expected_last_refreshed_at,
            )
        except ProfileTransitionConflict:
            pass
        _invalidate_profile_session(request.app, plugin, account_id, name)
        raise HTTPException(
            status_code=401,
            detail={
                "code": "auth_required",
                "message": str(exc),
                "reauth_url": f"/v1/auth/{provider}/profiles/{name}",
            },
        ) from exc
    else:
        # Success branch: publish only while the profile still exists (require_present). A profile
        # deleted during the network window makes this raise -> 409 instead of resurrecting it as
        # an AUTHENTICATED row.
        profile.state = ProfileState.AUTHENTICATED
        profile.last_refreshed_at = datetime.now(UTC)
        try:
            await _index_store(request).upsert(profile, require_present=True)
        except ProfileTransitionConflict as exc:
            _invalidate_profile_session(request.app, plugin, account_id, name)
            raise HTTPException(
                status_code=409,
                detail={"code": "profile_conflict", "provider": provider, "profile": name},
            ) from exc
        _invalidate_profile_session(request.app, plugin, account_id, name)


def _pending(request: Request):
    return _pending_for_app(request.app)


def _pending_for_app(app):
    return app.state.pending_auth


def _redirect_path_for(cfg: OAuthConfig) -> str:
    return cfg.redirect_path if cfg.redirect_path.startswith("/") else f"/{cfg.redirect_path}"


def _gateway_redirect_uri_for(request: Request, cfg: OAuthConfig) -> str:
    path = _redirect_path_for(cfg)
    public_url = request.app.state.settings.public_url
    if public_url:
        return f"{public_url}{path}"
    port = _request_host_port(request) or request.app.state.settings.port
    return f"http://localhost:{port}{path}"


def _invalid_redirect_uri(provider: str, message: str) -> HTTPException:
    return HTTPException(
        status_code=400,
        detail={"code": "invalid_redirect_uri", "provider": provider, "message": message},
    )


def _validate_redirect_uri_override(
    provider: str,
    cfg: OAuthConfig,
    redirect_uri: str,
) -> str:
    try:
        parsed = urlsplit(redirect_uri)
        port = parsed.port
    except ValueError as exc:
        raise _invalid_redirect_uri(provider, "redirect_uri is not a valid URL") from exc

    if parsed.scheme != "http":
        raise _invalid_redirect_uri(provider, "redirect_uri must use http")
    if parsed.username is not None or parsed.password is not None:
        raise _invalid_redirect_uri(provider, "redirect_uri must not include credentials")
    if parsed.query or parsed.fragment:
        raise _invalid_redirect_uri(provider, "redirect_uri must not include query or fragment")
    if port is None or port < 1:
        raise _invalid_redirect_uri(provider, "redirect_uri must include a valid port")

    hostname = (parsed.hostname or "").lower()
    if hostname not in {"localhost", "127.0.0.1", "::1"}:
        raise _invalid_redirect_uri(provider, "redirect_uri host must be loopback localhost")

    expected_path = _redirect_path_for(cfg)
    if parsed.path != expected_path:
        raise _invalid_redirect_uri(
            provider,
            f"redirect_uri path must be {expected_path}",
        )

    allowed_ports = cfg.loopback_redirect_ports
    if allowed_ports and port not in allowed_ports:
        raise _invalid_redirect_uri(
            provider,
            f"redirect_uri port must be one of {allowed_ports}",
        )
    return redirect_uri


def _request_host_port(request: Request) -> int | None:
    host_header = request.headers.get("host")
    if host_header:
        try:
            return urlsplit(f"//{host_header.strip()}").port
        except ValueError:
            return None
    return request.url.port


def _loopback_host_allowed(host_header: str | None) -> bool:
    hostname = _loopback_hostname(host_header)
    if hostname is None:
        return False
    normalized = hostname.rstrip(".").lower()
    if normalized == "localhost":
        return True
    try:
        return ip_address(normalized).is_loopback
    except ValueError:
        return False


def _loopback_hostname(host_header: str | None) -> str | None:
    if host_header is None:
        return None
    try:
        return urlsplit(f"//{host_header.strip()}").hostname
    except ValueError:
        return None


async def _close_loopback_callback(app, state: str) -> None:
    callbacks = getattr(app.state, "loopback_oauth_callbacks", None)
    server = callbacks.pop(state, None) if isinstance(callbacks, dict) else None
    tasks = getattr(app.state, "loopback_oauth_callback_tasks", None)
    task = tasks.pop(state, None) if isinstance(tasks, dict) else None
    current_task = asyncio.current_task()
    if task is not None and task is not current_task:
        task.cancel()
    if server is not None:
        server.close()
        await server.wait_closed()
    if task is not None and task is not current_task:
        await asyncio.gather(task, return_exceptions=True)


async def close_loopback_callbacks(app) -> None:
    callbacks = getattr(app.state, "loopback_oauth_callbacks", None)
    servers = list(callbacks.values()) if isinstance(callbacks, dict) else []
    if isinstance(callbacks, dict):
        callbacks.clear()

    task_map = getattr(app.state, "loopback_oauth_callback_tasks", None)
    tasks = list(task_map.values()) if isinstance(task_map, dict) else []
    if isinstance(task_map, dict):
        task_map.clear()

    current_task = asyncio.current_task()
    tasks_to_cancel = [task for task in tasks if task is not current_task]
    for task in tasks_to_cancel:
        task.cancel()
    for server in servers:
        server.close()
    if tasks_to_cancel:
        await asyncio.gather(*tasks_to_cancel, return_exceptions=True)
    for server in servers:
        await server.wait_closed()


async def _expire_loopback_callback(app, state: str, ttl_seconds: int) -> None:
    await asyncio.sleep(ttl_seconds)
    await _close_loopback_callback(app, state)


def _http_response(status: int, body: str, *, content_type: str = "text/html") -> bytes:
    reason = {200: "OK", 400: "Bad Request", 403: "Forbidden", 404: "Not Found"}.get(
        status, "Internal Server Error"
    )
    data = body.encode("utf-8")
    headers = (
        f"HTTP/1.1 {status} {reason}\r\n"
        f"content-type: {content_type}; charset=utf-8\r\n"
        f"content-length: {len(data)}\r\n"
        "connection: close\r\n"
        "\r\n"
    ).encode("ascii")
    return headers + data


async def _read_loopback_http_request(
    reader: asyncio.StreamReader,
) -> _LoopbackHttpRequest | None:
    try:
        raw = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), timeout=5)
    except (asyncio.IncompleteReadError, asyncio.LimitOverrunError, TimeoutError):
        return None
    return _parse_loopback_http_request(raw)


def _parse_loopback_http_request(raw: bytes) -> _LoopbackHttpRequest | None:
    lines = raw.decode("iso-8859-1", errors="replace").split("\r\n")
    request_line = lines[0].split()
    if len(request_line) < 2:
        return None
    return _LoopbackHttpRequest(
        method=request_line[0],
        target=request_line[1],
        headers=_parse_loopback_headers(lines[1:]),
    )


def _parse_loopback_headers(lines: list[str]) -> dict[str, str]:
    headers: dict[str, str] = {}
    for line in lines:
        if not line or ":" not in line:
            continue
        key, value = line.split(":", 1)
        headers[key.strip().lower()] = value.strip()
    return headers


async def _handle_loopback_callback(
    app,
    provider: str,
    expected_path: str,
    expected_state: str,
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
) -> None:
    status = 500
    body = "Authentication failed"
    close_callback = False
    try:
        callback_request = await _read_loopback_http_request(reader)
        if callback_request is None:
            status = 400
            body = "Malformed callback request"
            return

        if not _loopback_host_allowed(callback_request.headers.get("host")):
            status = 403
            body = "Forbidden callback host"
            return

        parsed = urlsplit(callback_request.target)
        if callback_request.method != "GET" or parsed.path != expected_path:
            status = 404
            body = "Unknown callback path"
            return

        params = parse_qs(parsed.query)
        code = params.get("code", [None])[0]
        state = params.get("state", [None])[0]
        close_callback = state == expected_state
        if not code or not state:
            status = 400
            body = "Missing callback code or state"
            return
        if state != expected_state:
            status = 400
            body = "OAuth state not recognized or expired"
            return

        await _complete_oauth_for_app(app, provider, code, state)
        status = 200
        body = _CALLBACK_HTML
    except Exception as exc:
        status = 500
        logger.error(
            "Loopback OAuth callback failed for provider %s: %s",
            provider,
            type(exc).__name__,
        )
        body = _callback_failure_html(
            provider,
            type(exc).__name__,
            "OAuth callback failed. Try again.",
        )
    finally:
        writer.write(_http_response(status, body))
        await writer.drain()
        writer.close()
        await writer.wait_closed()
        if close_callback:
            await _close_loopback_callback(app, expected_state)


async def _loopback_redirect_uri_for(
    request: Request,
    provider: str,
    cfg: OAuthConfig,
    state: str,
) -> str:
    path = _redirect_path_for(cfg)
    callbacks = getattr(request.app.state, "loopback_oauth_callbacks", None)
    if not isinstance(callbacks, dict):
        callbacks = {}
        request.app.state.loopback_oauth_callbacks = callbacks
    for port in cfg.loopback_redirect_ports or []:
        try:
            server = await asyncio.start_server(
                lambda reader, writer: _handle_loopback_callback(
                    request.app, provider, path, state, reader, writer
                ),
                host="localhost",
                port=port,
            )
        except OSError:
            continue
        callbacks = getattr(request.app.state, "loopback_oauth_callbacks", None)
        if not isinstance(callbacks, dict):
            callbacks = {}
            request.app.state.loopback_oauth_callbacks = callbacks
        callbacks[state] = server
        tasks = getattr(request.app.state, "loopback_oauth_callback_tasks", None)
        if not isinstance(tasks, dict):
            tasks = {}
            request.app.state.loopback_oauth_callback_tasks = tasks
        tasks[state] = asyncio.create_task(_expire_loopback_callback(request.app, state, 600))
        return f"http://localhost:{port}{path}"
    raise HTTPException(
        status_code=503,
        detail={"code": "oauth_loopback_unavailable", "ports": cfg.loopback_redirect_ports},
    )


async def _redirect_uri_for(
    request: Request,
    provider: str,
    cfg: OAuthConfig,
    state: str,
    redirect_uri: str | None = None,
) -> str:
    if redirect_uri is not None:
        return _validate_redirect_uri_override(provider, cfg, redirect_uri)
    if request.app.state.settings.public_url:
        return _gateway_redirect_uri_for(request, cfg)
    if cfg.loopback_redirect_ports:
        return await _loopback_redirect_uri_for(request, provider, cfg, state)
    return _gateway_redirect_uri_for(request, cfg)


# --- legacy Profile listings: shells over `ProviderCredentialAdmin.list` (OME-1230, A3) ---------
# COMPATIBILITY: these routes and their JSON are the legacy Profile surface, retired at Stage E
# (OME-1209); the backing-neutral successor is `GET /v1/provider-access` (A4).


@router.get("/v1/auth/profiles")
async def list_profiles(request: Request, current: CurrentAccount) -> dict:
    return {"profiles": _projections(await _credential_admin(request).list(str(current.id)))}


@router.get("/v1/auth/{provider}/profiles")
async def list_provider_profiles(provider: str, request: Request, current: CurrentAccount) -> dict:
    summaries = await _credential_admin(request).list(str(current.id), provider)
    return {"profiles": _projections(summaries)}


@router.get("/v1/auth/{provider}/profiles/{name}")
async def get_profile(provider: str, name: str, request: Request, current: CurrentAccount) -> dict:
    for summary in await _credential_admin(request).list(str(current.id), provider):
        if summary.selector == name:
            return summary.legacy_projection
    raise render_refusal(TargetMissing(provider, name))


class StartAuthRequest(BaseModel):
    name: str
    defaults: ProfileDefaults | None = None
    redirect_uri: str | None = None


@router.post("/v1/auth/{provider}/profiles", status_code=201)
async def start_oauth(
    provider: str,
    body: StartAuthRequest,
    request: Request,
    current: CurrentAccount,
) -> dict:
    plugin = _registry(request).get(provider)
    if plugin is None:
        raise HTTPException(
            status_code=404, detail={"code": "unknown_provider", "provider": provider}
        )

    cfg = plugin.oauth_config()
    if cfg is None:
        raise HTTPException(status_code=400, detail={"code": "provider_does_not_use_oauth"})

    account_id = str(current.id)
    profile_id = profile_id_for(account_id, provider, body.name)
    code_verifier, code_challenge = generate_pkce()
    state = generate_state()

    # Bind the redirect (for loopback, a listener keyed by ``state``) BEFORE superseding any
    # older flow for this profile: a redirect-setup failure must leave the previous flow
    # untouched rather than destroy it for a flow that never started (OME-307 Blocker 5).
    redirect_uri: str | None = None
    if body.redirect_uri is not None:
        redirect_uri = await _redirect_uri_for(request, provider, cfg, state, body.redirect_uri)
    if redirect_uri is None:
        redirect_uri = await _redirect_uri_for(request, provider, cfg, state)

    # INVARIANT (OME-307 Blockers 1 & 5): durably publish THIS flow — its pending state and a
    # fresh ownership generation — in one atomic CAS BEFORE irreversibly superseding any older
    # flow. On failure, tear down only this flow's own loopback listener and re-raise; the older
    # flow stays completable and no invisible pending flow is stranded.
    # FEATURE (OME-1208, D14): a MIGRATED pair claims its pair marker's generation and publishes
    # on its effective Connection; every other pair claims today's index generation.
    try:
        with refusals_as_http():
            flow = await begin_connection_oauth(
                request.app,
                plugin,
                account_id=account_id,
                provider=provider,
                name=body.name,
                scopes=cfg.scopes,
                defaults=body.defaults,
            )
        generation = (
            None
            if flow is not None
            else await _begin_legacy_pending(request, account_id, provider, body, cfg, profile_id)
        )
    except Exception:
        await _close_loopback_callback(request.app, state)
        raise

    _pending(request).put(
        state,
        PendingAuthEntry(
            account_id=account_id,
            provider=provider,
            profile_name=body.name,
            profile_id=profile_id,
            code_verifier=code_verifier,
            redirect_uri=redirect_uri,
            oauth_generation=generation,
            pair_generation=None if flow is None else flow.generation,
        ),
    )

    # Only now that this flow is fully published: supersede older flows for the same profile,
    # excluding this flow's own freshly-published state (Blocker 5).
    for stale_state in _pending(request).pop_for_profile(
        account_id, provider, body.name, exclude_state=state
    ):
        await _close_loopback_callback(request.app, stale_state)

    params = {
        "response_type": "code",
        "client_id": cfg.client_id,
        "redirect_uri": redirect_uri,
        "scope": " ".join(cfg.scopes),
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
        "state": state,
    }
    if cfg.extra_authorize_params:
        params.update(cfg.extra_authorize_params)
    authorize_url = f"{cfg.authorize_url}?{urlencode(params)}"

    return {
        "profile_id": profile_id,
        "authorize_url": authorize_url,
        "state": state,
        "expires_in": 600,
    }


async def _begin_legacy_pending(
    request: Request,
    account_id: str,
    provider: str,
    body: StartAuthRequest,
    cfg: OAuthConfig,
    profile_id: str,
) -> int:
    """Publish the pending profile of a pair the legacy Profile owns; returns its generation."""
    # Update the existing profile in place instead of replacing it wholesale:
    # an api_key profile keeps its auth_type/account_label/defaults until the
    # OAuth flow actually COMPLETES (completion flips auth_type to "oauth" in
    # _mark_profile_authenticated). A wholesale reset at flow start would
    # desync the index from the still-stored API-key blob (SF-244 audit F08).
    profile = await _index_store(request).get(account_id, provider, body.name)
    if profile is None:
        profile = Profile(
            id=profile_id,
            account_id=account_id,
            provider=provider,
            name=body.name,
        )
    profile.scopes = list(cfg.scopes)
    profile.state = ProfileState.PENDING
    if body.defaults is not None:
        profile.defaults = body.defaults
    # begin_pending is what assigns the ownership generation the callback later presents to
    # authenticate_pending (OME-307 Blocker 1).
    return await _index_store(request).begin_pending(profile)


_CALLBACK_HTML = """<!doctype html>
<html><body><p>Authentication complete. You may close this window.</p></body></html>
"""


def _callback_failure_html(provider: str, code: str, message: str) -> str:
    return (
        "<!doctype html><html><body>"
        "<h2>Authentication failed</h2>"
        f"<p>Provider: {escape(provider)}</p>"
        f"<pre style='white-space:pre-wrap'>{escape(code)}: {escape(message)}</pre>"
        "</body></html>"
    )


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


async def _complete_oauth_for_app(
    app,
    provider: str,
    code: str,
    state: str,
    current_account_id: str | None = None,
) -> None:
    """Run the OAuth token exchange and persist credentials.

    Used by both the GET browser-redirect callback and the POST manual
    paste-code endpoint. Raises HTTPException on failure.
    """
    pending_table = _pending_for_app(app)
    pending = _pending_or_unknown(pending_table.peek(state))
    _validate_pending_oauth(pending, provider, current_account_id)
    plugin = _registry_for_app(app).get(provider)
    if plugin is None:
        raise HTTPException(
            status_code=404, detail={"code": "unknown_provider", "provider": provider}
        )

    credential_name = _credential_name_for_pending(pending)
    strategy = _credential_strategy_for_credential_name(app, plugin, provider, credential_name)
    if strategy is None:
        raise HTTPException(
            status_code=400,
            detail={"code": "provider_does_not_use_oauth", "provider": provider},
        )

    # Consume the OAuth state after all synchronous validation and before the
    # first await that can race another callback using the same code.
    pending = _pending_or_unknown(pending_table.pop(state))
    try:
        try:
            creds = await _exchange_oauth_code_for_pending(
                app, plugin, provider, code, state, pending
            )
        except NotImplementedError as exc:
            await _mark_oauth_completion_error(app, pending, "provider_does_not_use_oauth", state)
            raise HTTPException(
                status_code=400,
                detail={"code": "provider_does_not_use_oauth", "provider": provider},
            ) from exc
        except Exception:
            await _mark_oauth_completion_error(app, pending, "OAuth code exchange failed", state)
            raise
        if pending.pair_generation is not None:
            await _publish_migrated_oauth(app, plugin, pending, creds, state)
        elif pending.connection_id is None:
            slot = cast(SupportsCredentialSlot, strategy)
            try:
                # WHY: token exchange stays outside the transaction; only profile + credential
                # publication is atomic. The always-present account index row is mutated first,
                # matching API-key set/delete's lock order; the optional credential row follows.
                # The generation CAS rejects stale callbacks before they can write credentials.
                async with in_transaction():
                    await _mark_profile_authenticated(
                        app,
                        pending,
                        plugin,
                        creds,
                        require_pending=True,
                    )
                    await persist_credentials_or_503(
                        slot,
                        creds,
                        description="OAuth profile credentials",
                    )
            except ProfileTransitionConflict as exc:
                await _close_loopback_callback(app, state)
                raise HTTPException(
                    status_code=409,
                    detail={
                        "code": "profile_auth_conflict",
                        "provider": pending.provider,
                        "profile": pending.profile_name,
                    },
                ) from exc
            except HTTPException:
                await _mark_oauth_completion_error(
                    app, pending, "credential_store_unavailable", state
                )
                raise
            _invalidate_profile_session(app, plugin, pending.account_id, pending.profile_name)
        else:
            await _mark_profile_authenticated(app, pending, plugin, creds)
        if pending.pair_generation is None:
            # D14: the shadow Connection write is today's behaviour for a pair the legacy Profile
            # owns; a MIGRATED pair's effective Connection IS the Connection.
            await _record_oauth_connection_completion(app, pending, plugin, creds)
        await _close_loopback_callback(app, state)
    except asyncio.CancelledError:
        # INVARIANT (OME-307 Blocker 5): a callback cancellation must never strand the profile
        # pending. We consumed the state before the first await above; on cancellation the
        # enclosing transaction (if any) rolls back, and we re-publish the consumed state
        # SYNCHRONOUSLY so the flow stays completable via retry. Python 3.12
        # ``asyncio.CancelledError`` is a ``BaseException`` that escapes the ``except Exception``
        # handlers above; ``put`` is synchronous so it finishes even while the task unwinds.
        # AIDEV-NOTE: cleanup-then-re-raise — the cancellation is NEVER caught-and-suppressed.
        pending_table.put(state, pending)
        raise


async def _publish_migrated_oauth(
    app,
    plugin,
    pending: PendingAuthEntry,
    creds: dict,
    state: str,
) -> None:
    """FEATURE (OME-1208, D14): a MIGRATED pair's callback publishes its effective Connection.

    The bodies on the wire are the legacy flow's: a superseded publication is
    `409 profile_auth_conflict`, a failed blob write `503 credential_store_unavailable`.
    """
    try:
        with refusals_as_http():
            try:
                credential_name = await complete_connection_oauth(app, plugin, pending, creds)
            except WriteConflict as exc:
                raise HTTPException(
                    status_code=409,
                    detail={
                        "code": "profile_auth_conflict",
                        "provider": pending.provider,
                        "profile": pending.profile_name,
                    },
                ) from exc
    except HTTPException as exc:
        if exc.status_code == 409:
            await _close_loopback_callback(app, state)
        else:
            await _mark_oauth_completion_error(app, pending, "credential_store_unavailable", state)
        raise
    _invalidate_credential(app, plugin, credential_name)


def _pending_or_unknown(pending: PendingAuthEntry | None) -> PendingAuthEntry:
    if pending is not None:
        return pending
    raise HTTPException(
        status_code=400,
        detail={"code": "unknown_state", "message": "OAuth state not recognized or expired"},
    )


def _validate_pending_oauth(
    pending: PendingAuthEntry,
    provider: str,
    current_account_id: str | None,
) -> None:
    if pending.provider != provider:
        raise HTTPException(status_code=400, detail={"code": "provider_mismatch"})
    if current_account_id is not None and current_account_id != pending.account_id:
        raise HTTPException(status_code=404, detail={"code": "profile_not_found"})


async def _exchange_oauth_code_for_pending(
    app,
    plugin,
    provider: str,
    code: str,
    state: str,
    pending: PendingAuthEntry,
) -> dict:
    return await plugin.exchange_oauth_code(
        OAuthCodeExchangeRequest(
            code=code,
            code_verifier=pending.code_verifier,
            redirect_uri=pending.redirect_uri,
            state=state,
            http_client_factory=getattr(app.state, f"{provider}_http_factory", None),
        )
    )


async def _mark_oauth_completion_error(
    app,
    pending: PendingAuthEntry,
    connection_message: str,
    state: str,
) -> None:
    # INVARIANT (OME-307 Blocker 2): only a PROFILE flow that claimed an ownership generation
    # can own a pending profile. Mark its error CONDITIONALLY on that generation so a stale
    # failure cannot clobber a newer owner, overwrite a committed API-key profile, or resurrect
    # a deleted profile. Connection flows are handled separately by _mark_connection_error.
    if pending.pair_generation is not None:
        await fail_connection_oauth(app, pending, connection_message)
    elif pending.connection_id is None and pending.oauth_generation is not None:
        await _mark_profile_error(app, pending.profile_id, pending.oauth_generation)
    await _mark_connection_error(app, pending, connection_message)
    await _close_loopback_callback(app, state)


async def _mark_profile_authenticated(
    app,
    pending: PendingAuthEntry,
    plugin,
    creds: dict,
    *,
    require_pending: bool = False,
) -> None:
    index = _index_store_for_app(app)
    profile = await index.get(
        pending.account_id,
        pending.provider,
        pending.profile_name,
    )
    if profile is None:
        if require_pending:
            raise ProfileTransitionConflict("profile no longer exists")
        return
    if require_pending and profile.state is not ProfileState.PENDING:
        raise ProfileTransitionConflict("profile is no longer pending")
    profile.state = ProfileState.AUTHENTICATED
    # A completed OAuth round-trip overwrites the credential slot, so the
    # discriminator must flip back even if the profile was api_key before.
    profile.auth_type = "oauth"
    profile.last_refreshed_at = datetime.now(UTC)
    label = plugin.account_label_from_credentials(creds)
    if label is not None:
        profile.account_label = label
    if require_pending:
        # INVARIANT (OME-307 Blocker 1): bind publication to THIS OAuth operation by presenting
        # the ownership generation this flow claimed at begin_pending. Ownership is decided
        # INSIDE authenticate_pending's atomic durable CAS — a superseded flow loses even though
        # the row is still PENDING — closing the check-then-act TOCTOU that a separate in-memory
        # precheck left open. The state==PENDING guard inside the CAS remains defense in depth
        # for a newer flow (or API-key write) that has already committed a non-pending state.
        await index.authenticate_pending(
            profile,
            expected_generation=pending.oauth_generation,
            account_label=label,
        )
    else:
        await index.upsert(profile)


def _credential_name_for_pending(pending: PendingAuthEntry) -> str:
    if pending.connection_id is not None:
        return credential_key_for(pending.account_id, pending.connection_id)
    return credential_name_for(pending.account_id, pending.profile_name)


async def _mark_connection_error(app, pending: PendingAuthEntry, message: str) -> None:
    if pending.connection_id is None:
        return
    store = OAuthConnectionStore()
    connection = await store.get(pending.account_id, pending.connection_id)
    if connection is not None:
        # INVARIANT: only this callback's still-pending connection may transition to ERROR.
        # A concurrent DELETE or successful activation owns any non-pending row and wins.
        await store.mark_pending_error(connection, message)
    credential_strategy_cache(app).evict(
        credential_key_for(pending.account_id, pending.connection_id)
    )


async def _persist_connection_credentials(
    app,
    plugin,
    provider: str,
    account_id: str,
    connection_id: str,
    creds: dict,
) -> None:
    strategy = _credential_strategy_for_credential_name(
        app,
        plugin,
        provider,
        credential_key_for(account_id, connection_id),
    )
    if strategy is not None:
        await persist_credentials_or_503(
            cast(SupportsCredentialPersistence, strategy),
            creds,
            description="OAuth connection credentials",
        )
    credential_strategy_cache(app).evict(credential_key_for(account_id, connection_id))


async def _record_oauth_connection_completion(
    app,
    pending: PendingAuthEntry,
    plugin,
    creds: dict,
) -> None:
    store = OAuthConnectionStore()
    if not _plugin_extracts_identity(plugin) and pending.connection_id is None:
        return
    identity = await _extract_connection_identity(app, pending, plugin, creds)
    label = _connection_label(pending, plugin, creds, identity)
    if not label:
        raise HTTPException(
            status_code=409,
            detail={"code": "label_required", "provider": pending.provider},
        )

    if await _handle_duplicate_connection_identity(app, store, pending, plugin, label, identity):
        return
    if await _handle_duplicate_connection_label(app, store, pending, plugin, label, identity):
        return

    connection = await _connection_for_pending(store, pending, plugin, label)
    try:
        # INVARIANT: connection lifecycle operations lock the stable connection row before the
        # optional credential row. The pending-only CAS and credential write commit together, so
        # a concurrent DELETE wins without credential orphaning or stale-row resurrection.
        async with in_transaction():
            activated = await store.complete_pending(connection, label=label, identity=identity)
            if activated is None:
                raise HTTPException(
                    status_code=409,
                    detail={
                        "code": "connection_conflict",
                        "provider": pending.provider,
                    },
                )
            await _persist_connection_credentials(
                app,
                plugin,
                pending.provider,
                pending.account_id,
                str(activated.id),
                creds,
            )
    except IntegrityError as exc:
        await store.mark_revoked(connection, "connection_conflict")
        raise HTTPException(
            status_code=409,
            detail={"code": "connection_conflict", "provider": pending.provider, "label": label},
        ) from exc
    except HTTPException as exc:
        if exc.status_code == 503:
            await store.mark_pending_error(connection, "credential_store_unavailable")
        raise
    except Exception as exc:
        await store.mark_pending_error(connection, "connection_activation_failed")
        raise HTTPException(
            status_code=503,
            detail={
                "code": "connection_activation_failed",
                "provider": pending.provider,
                "message": "Could not activate OAuth connection. Try again.",
            },
        ) from exc


def _plugin_extracts_identity(plugin) -> bool:
    return callable(getattr(plugin, "extract_identity", None))


async def _extract_connection_identity(
    app,
    pending: PendingAuthEntry,
    plugin,
    creds: dict,
) -> Any | None:
    extractor = getattr(plugin, "extract_identity", None)
    if not callable(extractor):
        return None
    return await cast(Callable[..., Awaitable[Any]], extractor)(
        creds,
        http_client_factory=getattr(app.state, f"{pending.provider}_http_factory", None),
    )


async def _handle_duplicate_connection_identity(
    app,
    store: OAuthConnectionStore,
    pending: PendingAuthEntry,
    plugin,
    label: str,
    identity,
) -> bool:
    duplicate = await store.find_by_identity(
        pending.account_id, pending.provider, getattr(identity, "sub", None)
    )
    if duplicate is None:
        return False
    if pending.connection_id is not None:
        connection = await _connection_for_pending(store, pending, plugin, label)
        if duplicate.id != connection.id:
            await store.delete_or_supersede_pending(connection, duplicate)
            await _delete_connection_credentials(app, connection.credential_locator)
    return True


async def _handle_duplicate_connection_label(
    app,
    store: OAuthConnectionStore,
    pending: PendingAuthEntry,
    plugin,
    label: str,
    identity,
) -> bool:
    if identity is not None and identity.sub is not None:
        return False
    duplicate_label = await store.find_by_label(pending.account_id, pending.provider, label)
    if duplicate_label is None:
        return False
    if pending.connection_id is None:
        return True
    connection = await _connection_for_pending(store, pending, plugin, label)
    if duplicate_label.id != connection.id:
        await store.delete_or_supersede_pending(connection, duplicate_label)
        await _delete_connection_credentials(app, connection.credential_locator)
    raise HTTPException(
        status_code=409,
        detail={"code": "label_conflict", "provider": pending.provider, "label": label},
    )


async def _delete_connection_credentials(app, locator: dict) -> None:
    service = locator.get("service")
    account = locator.get("account")
    if isinstance(service, str) and isinstance(account, str):
        await _credential_store_for_app(app).delete(service, account)


async def _connection_for_pending(
    store: OAuthConnectionStore,
    pending: PendingAuthEntry,
    plugin,
    label: str,
):
    if pending.connection_id is not None:
        connection = await store.get(pending.account_id, pending.connection_id)
        if connection is None:
            raise HTTPException(status_code=404, detail={"code": "connection_not_found"})
        return connection
    try:
        return await store.create_pending(
            account_id=pending.account_id,
            provider=pending.provider,
            label=label,
            connection_id=uuid4(),
            credential_provider=credential_service_provider_for(plugin, pending.provider),
        )
    except IntegrityError as exc:
        raise HTTPException(
            status_code=409,
            detail={"code": "label_conflict", "provider": pending.provider, "label": label},
        ) from exc


def _connection_label(pending: PendingAuthEntry, plugin, creds: dict, identity) -> str | None:
    if pending.requested_label:
        return pending.requested_label
    if identity is not None:
        label = identity.label()
        if label:
            return label
    label = plugin.account_label_from_credentials(creds)
    if label:
        return label
    return pending.compatibility_profile_name or pending.profile_name


async def _mark_profile_error(app, profile_id: str, expected_generation: int) -> None:
    # INVARIANT (OME-307 Blocker 2): a stale OAuth failure marks ERROR only while it still owns
    # the pending profile (same generation, still present, still PENDING). If ownership moved
    # on — newer flow, committed api_key, or delete — mark_pending_error raises and we do
    # nothing rather than corrupt the newer state or recreate a deleted profile.
    try:
        await _index_store_for_app(app).mark_pending_error(
            profile_id, expected_generation=expected_generation
        )
    except ProfileTransitionConflict:
        pass


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


@router.get("/v1/auth/{provider}/profiles/{name}/status")
async def profile_status(
    provider: str, name: str, request: Request, current: CurrentAccount
) -> dict:
    # FEATURE (OME-1208 S2'b3): a facade — a migrated pair renders from its effective Connection.
    target = await facade_target(
        request.app, account_id=str(current.id), provider=provider, name=name
    )
    if target is None:
        raise HTTPException(
            status_code=404,
            detail={"code": "profile_not_found", "provider": provider, "name": name},
        )
    p = target.view
    return {
        "state": p.state.value,
        "auth_type": p.auth_type,
        "account_label": p.account_label,
        "last_refreshed_at": p.last_refreshed_at.isoformat() if p.last_refreshed_at else None,
    }


class PatchProfileRequest(BaseModel):
    defaults: ProfileDefaults | None = None
    account_label: str | None = None


@router.patch("/v1/auth/{provider}/profiles/{name}")
async def patch_profile(
    provider: str,
    name: str,
    body: PatchProfileRequest,
    request: Request,
    current: CurrentAccount,
) -> dict:
    # FEATURE (OME-1208 S2'b3): metadata stays on the compatibility document (D16 (a)); the
    # response renders a migrated pair's state from its effective Connection.
    target = await facade_target(
        request.app, account_id=str(current.id), provider=provider, name=name
    )
    if target is None:
        raise HTTPException(status_code=404, detail={"code": "profile_not_found"})
    try:
        p = await patch_facade(
            request.app, target, defaults=body.defaults, account_label=body.account_label
        )
    except ProfileTransitionConflict as exc:
        raise HTTPException(
            status_code=409,
            detail={"code": "profile_conflict", "provider": provider, "profile": name},
        ) from exc
    return p.model_dump(mode="json")


class SetApiKeyRequest(BaseModel):
    model_config = ConfigDict(hide_input_in_errors=True)

    api_key: SecretStr
    defaults: ProfileDefaults | None = None


@router.put("/v1/auth/{provider}/profiles/{name}/api-key")
async def set_profile_api_key(
    provider: str,
    name: str,
    body: SetApiKeyRequest,
    request: Request,
    current: CurrentAccount,
) -> dict:
    """Create or update the CALLER's own API-key profile.

    A thin wrapper over :func:`upsert_api_key_profile`; the tenant-facing contract is simply
    "whatever that does, to my own account".
    """
    return await upsert_api_key_profile(
        request,
        provider=provider,
        name=name,
        account_id=str(current.id),
        raw_api_key=body.api_key,
        defaults=body.defaults,
    )


async def upsert_api_key_profile(
    request: Request,
    *,
    provider: str,
    name: str,
    account_id: str,
    raw_api_key: SecretStr,
    defaults: ProfileDefaults | None,
) -> dict:
    """Create or update a profile that authenticates with a raw API key — the ONE shared shell.

    The tenant route and the admin console (`OME-706`) both call this, so the OME-307 invariants
    live in exactly one place: `core/provider_access/profile_admin.py::set_api_key`, behind the
    admin boundary (OME-1230, Stage A3). The shell keeps the two edge halves only:

    - key normalisation and validation BEFORE the boundary is called (F4, owner 2026-09-18 —
      moving validation into core is outside this stage);
    - the post-commit OAuth cleanup AFTER it (network I/O, outside any transaction).

    The RAW key is never returned in responses or logs; the response is the boundary's window-only
    projection of the Profile, byte-identical to today's `Profile.model_dump(mode="json")`.
    # COMPATIBILITY: retired with the legacy Profile routes at Stage E (OME-1209).
    """
    plugin = _registry(request).get(provider)
    if plugin is None:
        raise render_refusal(ProviderUnknown(provider))
    api_key = normalize_api_key(raw_api_key)
    await require_valid_api_key(request, plugin, provider, api_key)

    with refusals_as_http():
        summary = await _credential_admin(request).set_api_key(
            account_id, provider, raw_api_key=api_key, legacy_name=name, defaults=defaults
        )
    # INVARIANT (OME-307 Unit 5): only after the API-key publication COMMITS do we
    # irreversibly cancel any in-flight OAuth flow for this profile. A late OAuth callback is
    # already rejected by authenticate_pending's pending-state CAS (it rolls back and returns
    # 409), so this pop is cleanup, not correctness. Deferring it past the commit means a
    # failed or cancelled publication above leaves the older OAuth flow usable and orphans no
    # credential. Closing loopback listeners is network I/O and stays outside the transaction
    # (SF-244 audit F10 stale cleanup) — which is why this half stays in the shell.
    for stale_state in _pending(request).pop_for_profile(account_id, provider, name):
        await _close_loopback_callback(request.app, stale_state)
    return summary.legacy_projection


@router.delete("/v1/auth/{provider}/profiles/{name}", status_code=204)
async def delete_profile(provider: str, name: str, request: Request, current: CurrentAccount):
    """Delete the CALLER's own profile. Thin wrapper over the shared implementation."""
    await delete_profile_for_account(
        request, provider=provider, name=name, account_id=str(current.id)
    )


async def delete_profile_for_account(
    request: Request, *, provider: str, name: str, account_id: str
) -> None:
    """Remove one profile and its credential — the ONE shared shell over the admin boundary.

    WHY `account_id` is a parameter: the admin console deletes on a tenant's behalf (`OME-706`).
    The OME-307 transaction ordering lives in `profile_admin.py::delete`; this shell only renders
    the refusals — through the delete-specific rows, because this route's 404 bodies carry no
    provider or name field (F3, owner 2026-09-18).
    # COMPATIBILITY: retired with the legacy Profile routes at Stage E (OME-1209).
    """
    with legacy_delete_refusals_as_http():
        await _credential_admin(request).delete(account_id, provider, legacy_name=name)


@router.post("/v1/auth/{provider}/profiles/{name}/refresh")
async def refresh_profile(
    provider: str, name: str, request: Request, current: CurrentAccount
) -> dict:
    plugin = _registry(request).get(provider)
    if plugin is None:
        raise HTTPException(status_code=404, detail={"code": "unknown_provider"})
    account_id = str(current.id)
    target = await facade_target(request.app, account_id=account_id, provider=provider, name=name)
    if target is None:
        raise HTTPException(status_code=404, detail={"code": "profile_not_found"})
    if target.connection is not None:
        # FEATURE (OME-1208 S2'b3): a migrated pair refreshes THROUGH its effective Connection.
        with refusals_as_http():
            refreshed = await refresh_facade(
                request.app, plugin, target, provider=provider, account_id=account_id, name=name
            )
        return refreshed.model_dump(mode="json")
    p = target.document
    strategy = _credential_strategy_for_app(
        request.app, plugin, provider, account_id, name, auth_type=p.auth_type
    )
    if strategy is None:
        raise HTTPException(status_code=400, detail={"code": "provider_does_not_use_oauth"})

    async with _profile_refresh_lifecycle(request, plugin, p, provider, account_id, name):
        await strategy.refresh_credentials()
    return p.model_dump(mode="json")
