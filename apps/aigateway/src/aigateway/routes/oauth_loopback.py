"""How a provider's OAuth redirect reaches this gateway.

FEATURE: OAuth login for a desktop/CLI install that has no public URL. The gateway
opens a short-lived listener on a loopback port the provider is allowed to redirect to,
serves the callback itself, and closes the listener.

This module owns REDIRECT DELIVERY only: which redirect URI to hand the provider
(operator-configured public URL, a validated caller override, or a loopback port), the
listener that receives it, and that listener's lifetime. What to DO with a delivered
code belongs to the OAuth completion coordinator.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from html import escape
from ipaddress import ip_address
from urllib.parse import parse_qs, urlsplit

from fastapi import HTTPException, Request

from ..core.plugin_base import (
    OAuthConfig,
)

logger = logging.getLogger(__name__)


# The page a browser lands on after a provider redirect. It lives here because
# redirect DELIVERY is what serves it: the loopback listener writes it straight to
# the socket, and the gateway callback route returns the same bytes.
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


@dataclass(frozen=True)
class _LoopbackHttpRequest:
    method: str
    target: str
    headers: dict[str, str]


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

        await _complete_delivered_code(app, provider, code, state)
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


async def _complete_delivered_code(app, provider: str, code: str, state: str) -> None:
    """Hand a loopback-delivered code to the OAuth completion coordinator.

    # WHY the import is inside the function: the coordinator lives in ``routes.auth``,
    # which imports this module for its redirect-uri resolution, so a module-level import
    # would be a cycle. Resolving it per call also keeps the coordinator patchable through
    # ``routes.auth`` — the namespace the suite instruments — which a module-level
    # ``from .auth import`` would freeze at import time.
    """
    from .auth import _complete_oauth_for_app

    await _complete_oauth_for_app(app, provider, code, state)
