"""FastAPI WS route: authenticates the connection via a short-lived ticket, resolves
the caller's topic, then hands the accepted socket off to `Bridge` for the
duration of the connection.
"""

import logging
from datetime import UTC, datetime

from fastapi import APIRouter, WebSocket

from screamingface_engine.auth import AuthError, JwtCodec
from screamingface_engine.config import Settings
from screamingface_engine.ws.bridge import run_bridge
from screamingface_engine.ws.registry import ConnectionRegistry
from url4.streaming.interfaces import EventConsumer, JobRunner

router = APIRouter()

_SUBPROTOCOL = "cloudevents.json"
_POLICY_VIOLATION = 1008
_INTERNAL_ERROR = 1011

_logger = logging.getLogger(__name__)


def _default_clock() -> datetime:
    return datetime.now(UTC)


def _ticket_topic(websocket: WebSocket, ticket: str | None) -> str | None:
    """Verify the connect-time ticket and derive the topic to subscribe to.

    Returns None on a missing ticket or a failed verification (expired, bad
    signature, outside the iat window); the caller treats both the same way —
    closing the socket with a policy-violation code — so no distinction is made
    between "no ticket" and "invalid ticket" here.
    """
    if ticket is None:
        return None
    settings: Settings = websocket.app.state.settings
    clock = getattr(websocket.app.state, "clock", _default_clock)
    codec = JwtCodec(
        secret=settings.jwt_secret,
        iat_window_s=settings.iat_window_s,
        capability_lifetime_s=settings.capability_lifetime_s,
    )
    try:
        return str(codec.verify(ticket, clock())["sub"])
    except AuthError:
        return None


async def _accept(websocket: WebSocket) -> None:
    """Accept the handshake, echoing the `cloudevents.json` subprotocol back only if
    the client actually offered it.
    """
    offered = websocket.scope.get("subprotocols") or []
    subprotocol = _SUBPROTOCOL if _SUBPROTOCOL in offered else None
    await websocket.accept(subprotocol=subprotocol)


@router.websocket("/ws")
async def ws_endpoint(websocket: WebSocket, ticket: str | None = None) -> None:
    """Entry point for `/ws` connections.

    Closes with 1008 (policy violation) on a missing/invalid ticket, 1011
    (internal error) if the app was wired up without an event stream, and
    otherwise registers the topic, accepts the socket, and blocks for the
    lifetime of the connection inside `run_bridge`.
    """
    topic = _ticket_topic(websocket, ticket)
    if topic is None:
        # WHY worth a log line: this is invisible from the client, which sees only a
        # refused handshake. A burst of these says capabilities are arriving stale —
        # the ticket's `iat_window_s` is short enough that anything delaying the
        # connect (a Cloudflare Access login, a suspended host) outlives it.
        _logger.info(
            "ws rejected reason=%s",
            "missing ticket" if ticket is None else "unverifiable ticket",
        )
        await websocket.close(code=_POLICY_VIOLATION)
        return
    stream: EventConsumer | None = websocket.app.state.stream
    if stream is None:
        await websocket.close(code=_INTERNAL_ERROR)
        return
    registry: ConnectionRegistry = websocket.app.state.registry
    job_runner: JobRunner | None = websocket.app.state.job_runner
    clock = getattr(websocket.app.state, "clock", _default_clock)
    heartbeat_s: float = websocket.app.state.settings.ws_heartbeat_s
    registry.add(topic)
    try:
        await _accept(websocket)
        # `registry` is passed twice over, as the subscriber count AND as the session state the
        # attach frame's cache intent lands in: both are per-topic bookkeeping with the same
        # lifetime, and the `add` above is what guarantees the session exists before any frame
        # arrives.
        await run_bridge(
            websocket,
            stream,
            topic,
            job_runner=job_runner,
            sessions=registry,
            clock=clock,
            heartbeat_s=heartbeat_s,
        )
    finally:
        # INVARIANT: the registry count is decremented exactly once per successful
        # `add`, regardless of how the bridge exits (client disconnect, stream
        # failure, or task cancellation).
        registry.remove(topic)
