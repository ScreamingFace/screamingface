"""What makes `auth_mode=disabled` safe: nothing but this machine can reach the write endpoint.

`disabled` asks callers for nothing — no identity, no bot token, no budget. That is the right
posture for a developer running the service on their laptop and the wrong one for anything
reachable over a network, so the mode is bound to loopback rather than merely documented as
local. Both halves are checked, because they close different holes: the peer must be loopback
(nobody else can connect) and the `Host` header must be loopback (a DNS name resolving to
127.0.0.1 cannot be used to walk a browser into posting here from a page it loaded elsewhere).

INVARIANT — `/healthz` and `/readyz` are exempt, unconditionally, and the exemption is not
configurable. A kubelet dials the Pod IP, so a probe behind this check is a pod that fails its own
liveness probe and CrashLoopBackOffs; the CI image job, which curls the container through a
published port, hits exactly the same non-loopback peer. This is plan §11 conflict 9, and it is
listed there because the middleware this one is modelled on (`apps/aigateway`'s
`AuthDisabledLocalOnlyMiddleware`) gates every path. Exempting them costs nothing: `/healthz` is a
constant and `/readyz` is a boolean about this process, neither of which is worth reaching for.

Pure ASGI rather than `BaseHTTPMiddleware` so the refusal is the same RFC 9457 body every other
refusal in this service is — a `BaseHTTPMiddleware` raising `ProblemException` would land outside
starlette's exception middleware and become a 500.
"""

from __future__ import annotations

from ipaddress import ip_address
from urllib.parse import urlsplit

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from .problem import render_problem
from .problem_catalogue import loopback_only

PROBE_PATHS = frozenset({"/healthz", "/readyz"})
"""The paths a kubelet, a `helm test` pod, and the CI image job reach without being loopback.

Pinned as literals rather than derived from the routers, so a renamed route breaks a test here
instead of silently un-exempting a probe. `tests/unit/test_local_only.py` asserts each one is a
real route on the app.
"""

_REFUSAL = (
    "this report-intake is running with REPORT_INTAKE_AUTH_MODE=disabled, which serves loopback "
    "clients only; a deployment reachable over a network must set auth_mode=mesh_or_turnstile"
)


def _hostname(host_header: str | None) -> str | None:
    """The `Host` header without its port, or None when there is nothing usable in it.

    The trailing dot is stripped and the name lowercased, because `Reports.` and `reports` are the
    same name to a resolver and a comparison that disagrees with the resolver is not a check.
    """
    value = (host_header or "").strip()
    if not value:
        return None
    try:
        hostname = urlsplit(f"//{value}").hostname
    except ValueError:
        hostname = None
    return hostname.rstrip(".").lower() if hostname else None


def _is_loopback_host(host_header: str | None) -> bool:
    hostname = _hostname(host_header)
    if hostname == "localhost":
        return True
    try:
        # `""` for a missing header, which `ip_address` refuses — the same answer as a name that
        # is not an address, and one fewer branch than checking for None first.
        return ip_address(hostname or "").is_loopback
    except ValueError:
        return False


def _host_header(scope: Scope) -> str | None:
    for name, value in scope.get("headers", ()):
        if name.lower() == b"host":
            return value.decode("latin-1")
    return None


def _is_loopback_client(scope: Scope) -> bool:
    client = scope.get("client")
    if not client:
        return False
    try:
        return ip_address(client[0]).is_loopback
    except ValueError:
        return False


class LoopbackOnlyMiddleware:
    """Refuse anything but a loopback caller, except the probes."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["path"] in PROBE_PATHS:
            await self.app(scope, receive, send)
            return
        if _is_loopback_client(scope) and _is_loopback_host(_host_header(scope)):
            await self.app(scope, receive, send)
            return
        response = render_problem(loopback_only(_REFUSAL))
        # The body is deliberately not drained: this caller is not entitled to have one read.
        await response(scope, _nothing_more, send)


async def _nothing_more() -> Message:
    """A `receive` for a response that never reads one."""
    return {"type": "http.request", "body": b"", "more_body": False}
