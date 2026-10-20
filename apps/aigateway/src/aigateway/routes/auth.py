from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from html import escape
from ipaddress import ip_address
from typing import Any, cast
from urllib.parse import parse_qs, urlsplit

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from tortoise.exceptions import IntegrityError
from tortoise.transactions import in_transaction

from ..core.auth.middleware import CurrentAccount
from ..core.credential_blob.store import CredentialBlobMutationConflict
from ..core.credential_strategy_cache import credential_strategy_cache
from ..core.oauth.store import (
    OAuthConnectionStore,
    credential_key_for,
)
from ..core.pending_auth import PendingAuthEntry
from ..core.plugin_base import (
    OAuthCodeExchangeRequest,
    OAuthConfig,
    credential_strategy_from,
)
from ..core.profile_index import ProfileIndexStore
from ..core.profile_models import ProfileState
from ..core.provider_access import (
    PairAuthorityConflict,
    claim_observed,
    credential_name_of,
    replace_effective,
    retire_replaced,
)
from .credential_persistence import (
    SupportsCredentialPersistence,
    persist_credentials_or_503,
)

logger = logging.getLogger(__name__)
router = APIRouter()


@dataclass(frozen=True)
class _LoopbackHttpRequest:
    method: str
    target: str
    headers: dict[str, str]


def _index_store_for_app(app) -> ProfileIndexStore:
    return app.state.profile_index


def _registry_for_app(app):
    return app.state.providers


def _credential_store_for_app(app):
    return app.state.credential_store


def _credential_strategy_for_credential_name(app, plugin, provider: str, credential_name: str):
    return credential_strategy_from(
        plugin,
        credential_name,
        auth_type="oauth",
        credential_store=_credential_store_for_app(app),
        http_client_factory=getattr(app.state, f"{provider}_http_factory", None),
    )


def _invalidate_credential(app, plugin, credential_name: str) -> None:
    """Evict one credential name — a replaced Connection's locator."""
    invalidator = getattr(plugin, "invalidate_profile_session", None)
    if callable(invalidator):
        invalidator(credential_name)
    # Drop the shared cached strategy so re-auth / api-key change / delete / refresh
    # never serve a stale in-memory token from a prior credential (SF-282).
    credential_strategy_cache(app).evict(credential_name)


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
    account and Connection.

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
        await _record_oauth_connection_completion(app, pending, plugin, creds)
        await _close_loopback_callback(app, state)
    except asyncio.CancelledError:
        # INVARIANT (OME-307 Blocker 5): a callback cancellation must never strand the Connection
        # flow. We consumed the state before the first await above; on cancellation the
        # enclosing transaction (if any) rolls back, and we re-publish the consumed state
        # SYNCHRONOUSLY so the flow stays completable via retry. Python 3.12
        # ``asyncio.CancelledError`` is a ``BaseException`` that escapes the ``except Exception``
        # handlers above; ``put`` is synchronous so it finishes even while the task unwinds.
        # AIDEV-NOTE: cleanup-then-re-raise — the cancellation is NEVER caught-and-suppressed.
        pending_table.put(state, pending)
        raise


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
    await _mark_connection_error(app, pending, connection_message)
    await _close_loopback_callback(app, state)


async def _mark_profile_authenticated(
    app,
    pending: PendingAuthEntry,
    plugin,
    creds: dict,
) -> None:
    """D14: mirror the native callback's success onto a same-named compat document, if any."""
    index = _index_store_for_app(app)
    profile = await index.get(
        pending.account_id,
        pending.provider,
        pending.profile_name,
    )
    if profile is None:
        return
    profile.state = ProfileState.AUTHENTICATED
    # A completed OAuth round-trip overwrites the credential slot, so the
    # discriminator must flip back even if the profile was api_key before.
    profile.auth_type = "oauth"
    profile.last_refreshed_at = datetime.now(UTC)
    label = plugin.account_label_from_credentials(creds)
    if label is not None:
        profile.account_label = label
    await index.upsert(profile)


def _credential_name_for_pending(pending: PendingAuthEntry) -> str:
    return credential_key_for(pending.account_id, pending.connection_id)


async def _mark_connection_error(app, pending: PendingAuthEntry, message: str) -> None:
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
    identity = await _extract_connection_identity(app, pending, plugin, creds)
    label = _connection_label(pending, plugin, creds, identity)
    if not label:
        raise HTTPException(
            status_code=409,
            detail={"code": "label_required", "provider": pending.provider},
        )

    if await _handle_duplicate_connection_identity(app, store, pending, identity):
        return
    if await _handle_duplicate_connection_label(app, store, pending, label, identity):
        return

    connection = await _connection_for_pending(store, pending)
    replaced: list = []
    try:
        # INVARIANT: connection lifecycle operations lock the stable connection row before the
        # optional credential row. The pending-only CAS and credential write commit together, so
        # a concurrent DELETE wins without credential orphaning or stale-row resurrection.
        async with in_transaction():
            # INVARIANT (OME-1497, G0 §5.3): check and publication are atomic — the native claim
            # and compat-document update commit with the activated row and its blob, or not at all.
            await claim_observed(pending.observed_pair)
            if pending.replaces_effective is None:
                await _mark_profile_authenticated(app, pending, plugin, creds)
            else:
                # FEATURE (OME-1209, E1b, R6): this flow repairs a migrated pair — marker first
                # (D14), the old row revoked before this one activates.
                # INVARIANT (R6, §8 Q7): a repair writes no Profile document.
                await replace_effective(pending.replaces_effective, connection_id=connection.id)
                replaced = await retire_replaced(
                    pending.replaces_effective,
                    alongside=(connection.id,),
                    identity_sub=getattr(identity, "sub", None),
                )
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
        for row in replaced:
            _invalidate_credential(
                app, plugin, credential_name_of(plugin, row, account_id=pending.account_id)
            )
    except PairAuthorityConflict as exc:
        # WHY: a lost callback retires its row — a stranded `pending` row would keep its label
        # taken with nothing to clean it up.
        await store.mark_revoked(connection, "superseded")
        raise _connection_conflict(pending) from exc
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
    except CredentialBlobMutationConflict:
        # WHY: the compat-document update exhausted its retries; everything rolled back and the
        # Connection stays pending, so the callback keeps its retryable `profile_index_conflict`.
        raise
    except Exception as exc:
        await store.mark_pending_error(connection, "connection_activation_failed")
        raise _activation_failed(pending) from exc


def _connection_conflict(pending: PendingAuthEntry) -> HTTPException:
    return HTTPException(
        status_code=409,
        detail={"code": "connection_conflict", "provider": pending.provider},
    )


def _activation_failed(pending: PendingAuthEntry) -> HTTPException:
    return HTTPException(
        status_code=503,
        detail={
            "code": "connection_activation_failed",
            "provider": pending.provider,
            "message": "Could not activate OAuth connection. Try again.",
        },
    )


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
    identity,
) -> bool:
    if pending.replaces_effective is not None:
        # FEATURE (OME-1209, E1b, R6): a repair is never a duplicate — it retires every row of the
        # pair holding this identity under its row locks (`retire_replaced`) and activates its own.
        return False
    duplicate = await store.find_by_identity(
        pending.account_id, pending.provider, getattr(identity, "sub", None)
    )
    if duplicate is None:
        return False
    connection = await _connection_for_pending(store, pending)
    if duplicate.id != connection.id:
        await store.delete_or_supersede_pending(connection, duplicate)
        await _delete_connection_credentials(app, connection.credential_locator)
    return True


async def _handle_duplicate_connection_label(
    app,
    store: OAuthConnectionStore,
    pending: PendingAuthEntry,
    label: str,
    identity,
) -> bool:
    if identity is not None and identity.sub is not None:
        return False
    duplicate_label = await store.find_by_label(pending.account_id, pending.provider, label)
    if duplicate_label is None:
        return False
    observed = pending.replaces_effective
    if observed is not None and duplicate_label.id == observed.effective_connection_id:
        # WHY: the flow asked for the effective row's own label — that row is being replaced.
        return False
    connection = await _connection_for_pending(store, pending)
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


async def _connection_for_pending(store: OAuthConnectionStore, pending: PendingAuthEntry):
    connection = await store.get(pending.account_id, pending.connection_id)
    if connection is None:
        raise HTTPException(status_code=404, detail={"code": "connection_not_found"})
    return connection


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
    return pending.profile_name


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
