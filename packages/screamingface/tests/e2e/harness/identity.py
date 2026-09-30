"""The test edge: a stand-in for Cloudflare Access + Envoy (unit E2E, OME-1307).

FEATURE: OME-1307 (E14) E2E, D5. The scoreboard and the gateway run `cloudflare_headers`. Each
checks that the TCP peer is in an allowed network (the loopback peer of the test process and of
the engine), and only then reads `X-User-Email`. So the submitter, the result reporter, the
receipt `sub`, the grant `sub`, the metadata owner and the publish owner are all the verified
email set here. No test seam writes `submitted_by`.
INVARIANT: every request leaves with exactly ONE `X-User-Email`, the edge user. Envoy clears a
client copy first, and so does this edge.
"""

from __future__ import annotations

from collections.abc import Generator, Mapping
from typing import TYPE_CHECKING, Final

import httpx

import screamingface as sf
from screamingface._access.base import _TransportAuth
from screamingface._engine.transport import Url4CloudTransport

if TYPE_CHECKING:
    from .e14_stack import E14Stack

EDGE_NETWORK: Final = "127.0.0.1/32"  # the allowed network of the scoreboard and the gateway
# WHY 192.0.2.1 (TEST-NET-1, never a real peer): uvicorn defaults FORWARDED_ALLOW_IPS to 127.0.0.1,
# which overlaps EDGE_NETWORK, and the scoreboard `create_app` refuses that overlap in
# cloudflare_headers mode. The same value as the SB-submit `clustered_cf_app` fixture.
FORWARDED_ALLOW_IPS_E2E: Final = "192.0.2.1"
_HEADER: Final = "X-User-Email"


class EdgeIdentityTransport(httpx.BaseTransport):
    """Test-only stand-in for Cloudflare Access + Envoy: every request leaves as `user`."""

    def __init__(self, user: str, inner: httpx.BaseTransport | None = None) -> None:
        self._user = user
        self._inner = inner if inner is not None else httpx.HTTPTransport()

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        # WHY: `Headers.__setitem__` replaces every value of the name, in any casing, so a client
        # copy never survives.
        request.headers[_HEADER] = self._user
        return self._inner.handle_request(request)

    def close(self) -> None:
        self._inner.close()


class _EdgeRunAuth(_TransportAuth):
    """Sets the verified email on the run transport's requests (`GET /?q=` and the rest).

    WHY an Auth and not `http_transport=`: `Url4CloudTransport` builds its OWN httpx client for
    the run lifecycle, so `Client(http_transport=...)` never reaches the start request. The
    engine reads the identity of a run off that start request, so without this the gateway sees
    no `X-User-Email` and answers 401. `Url4CloudTransport(engine_url, caller_auth)` is the
    seam its own tests use.
    """

    def __init__(self, user: str) -> None:
        self._user = user

    def auth_flow(self, request: httpx.Request) -> Generator[httpx.Request, httpx.Response, None]:
        request.headers[_HEADER] = self._user
        yield request

    def reauthenticate(self, *, timeout: float = 300.0) -> None:
        return None

    async def reauthenticate_async(self, *, timeout: float = 300.0) -> None:
        return None

    def websocket_headers(self) -> Mapping[str, str]:
        return {}

    async def websocket_headers_async(self) -> Mapping[str, str]:
        return {}

    def close(self) -> None:
        return None


def edge_run_transport(engine_url: str, user: str) -> Url4CloudTransport:
    """A run transport whose start request leaves as `user` (see `_EdgeRunAuth`)."""
    return Url4CloudTransport(engine_url, _EdgeRunAuth(user))


def edge_client(stack: E14Stack, user: str) -> sf.Client:
    """An SDK client whose engine, run and scoreboard calls all leave as `user`."""
    return sf.Client(
        engine_url=stack.engine_url,
        scoreboard_url=stack.scoreboard_url,
        http_transport=EdgeIdentityTransport(user),
        scoreboard_transport=EdgeIdentityTransport(user),
        run_transport=edge_run_transport(stack.engine_url, user),
    )


def edge_http(base_url: str, user: str | None) -> httpx.Client:
    """A raw HTTP client. `user=None` is an anonymous reader of a public board (no header)."""
    transport = EdgeIdentityTransport(user) if user is not None else None
    return httpx.Client(base_url=base_url, timeout=30.0, transport=transport)
