"""The App's sync forwarder: verbatim onward delivery to the node tier (prd/03 §2.2, C2).

FEATURE (unit 3, D6): the App is the one public origin. A request to a declared mount is
forwarded UNCHANGED to the node Service; everything else is answered here. The App keeps
ownership of identity: it strips any client-supplied ``X-User-Email`` and sets the
edge-verified value before forwarding (AC4).

# INVARIANT: only KNOWN MOUNTS are forwarded (contracts.md C2 option 2). The forwardable set is
# derived at App startup from the SAME `world` module the node uses, so both tiers resolve one
# declaration and drift is impossible within a release. The App's `NodeMountRoute` matches only
# that set, so an unknown path is the engine's own 404 and never reaches the node (AC12/T10) —
# that is what makes D6's "verbatim" safe rather than a proxy for typos.

# INVARIANT: the outbound header set is BUILT, never copied. `forwarded_headers` is the ONE
# strip-and-reset helper (shared with local mode): every inbound header except the allowlist is
# dropped and the identity is set from the VERIFIED value, so a client-supplied `X-User-Email`,
# a Cookie, an `Authorization` or a `URL4-Capability` cannot survive the hop.

# INVARIANT: the retry is transport-level and narrow — exactly one retry when the request never
# reached the node (a refused connection, a connect timeout, a pool timeout), never on a read or
# write timeout and never on a 5xx (AC9/T8). A read or write timeout may mean the node is
# mid-call and billing; retrying would double one caller's cost for one request.

# INVARIANT: this module lives under `rest/` (a control-plane package), not as a new top-level
# module. The layering gate classifies an unlisted top-level module as a shared leaf that may not
# import `world`; the forwarder serves the shared world, so it belongs to the half that serves.
"""

from __future__ import annotations

import hashlib
import logging
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path

import httpx
from starlette.datastructures import Headers

from screamingface_engine import job_env
from screamingface_engine.request_scope import (
    ANSWER_SEED_HEADER,
    CACHE_CONTROL_HEADER,
    PROFILE_HEADER,
    TRACEPARENT_HEADER,
)
from screamingface_engine.world.config import DEFAULT_CONFIG_PATH, WorldConfig
from screamingface_engine.world.serving import compose_serving_world, node_mount_paths
from screamingface_engine.world.wire import AsgiReceive, AsgiScope, AsgiSend, send_url4_error, write

logger = logging.getLogger(__name__)

# WHY a separate, short connect budget (FX-33): the node is one in-cluster hop away. A connect
# that takes longer than this is a node that is not there, and waiting the whole forward budget
# for it would hold the caller for 35 s to learn what the retry learns in 2.
_CONNECT_TIMEOUT_S = 2.0

# The failures where the request never reached the node, so a retry cannot double a bill.
_CONNECTION_ERRORS = (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout)

# The forwarded request headers, and ONLY these (contracts.md C2). Identity is not in the list:
# it is set from the verified value, never copied from the wire.
_FORWARDED_REQUEST_HEADERS = (
    PROFILE_HEADER,
    CACHE_CONTROL_HEADER,
    ANSWER_SEED_HEADER,
    TRACEPARENT_HEADER,
)

# Response headers that describe the HOP, not the payload. `content-length` is re-derived from
# the buffered body; `content-encoding` is dropped because httpx decodes transparently.
_HOP_BY_HOP = frozenset(
    {
        "connection",
        "keep-alive",
        "proxy-authenticate",
        "proxy-authorization",
        "te",
        "trailers",
        "transfer-encoding",
        "upgrade",
        "content-length",
        "content-encoding",
    }
)

# WHY `server` and `date` are dropped too (FX-37): the App's own server writes both on every
# response, so relaying the node's would send two of each.
_NOT_RELAYED = _HOP_BY_HOP | {"server", "date"}

_MISSING_IDENTITY_MESSAGE = (
    "the sync surface requires an edge-verified identity (X-User-Email); this request carried "
    "none, so it is refused rather than forwarded anonymously"
)
_TIMEOUT_MESSAGE = (
    "the node tier did not answer within the forward budget — long-running work belongs on the "
    "ensemble path (POST /token, attach the WebSocket, then GET /?q=<expression>)"
)
_UNREACHABLE_MESSAGE = "the node tier is unreachable; retry shortly"

# The url4 WIRE error codes this module emits itself (contracts.md C1 status mapping). Plain
# strings, NOT `url4.core.errors.ErrorCode`: the control plane does not import the url4 ENGINE
# (`test_url4_executor.py`), and the mount surface's envelope is a wire contract, not an engine
# call. `world.node_tier` owns the node side of the same mapping; the two spell the codes once each.
_ENDPOINT_NOT_FOUND = "endpoint_not_found"
_IDENTITY_ACCESS_DENIED = "identity_access_denied"
_TIMEOUT_CODE = "timeout"
_UPSTREAM_UNAVAILABLE = "upstream_unavailable"


class _NodeTimeout(Exception):
    """The forward to the node exceeded the App's budget. Never retried (AC9)."""


class _NodeUnreachable(Exception):
    """The node could not be reached after the one permitted connection retry (AC8)."""


def forwarded_headers(
    inbound: Iterable[tuple[str, str]],
    *,
    verified_identity: Mapping[str, str],
) -> list[tuple[str, str]]:
    """The outbound header set: allowlisted request headers plus the VERIFIED identity.

    THE strip-and-reset helper, shared with local mode. It never copies an inbound identity
    header — identity is not on the allowlist — and it appends the verified value last, so
    exactly one ``X-User-Email`` leaves regardless of how many the client sent or how it cased
    them. Everything not named in `_FORWARDED_REQUEST_HEADERS` is dropped: Cookies,
    ``Authorization`` and ``URL4-Capability`` especially.
    """
    canonical = {name.lower(): name for name in _FORWARDED_REQUEST_HEADERS}
    out: list[tuple[str, str]] = []
    for name, value in inbound:
        header = canonical.get(name.lower())
        if header is not None:
            out.append((header, value))
    out.extend(verified_identity.items())
    return out


@dataclass(frozen=True, slots=True)
class ForwardContract:
    """What the App derives from the world declaration: which paths to forward, and its digest.

    ``config_digest`` is the sha256 of the config FILE the mount set was derived from
    (erd.md §2), exposed on ``/healthz`` so a rolling deploy where the two tiers briefly read
    different configuration is visible rather than silent (R11). ``None`` when the file is
    absent, which the health endpoint then omits.
    """

    mount_paths: frozenset[str]
    config_digest: str | None


async def derive_forward_contract(
    *,
    env: Mapping[str, str],
    engine_routes: Iterable[str],
    config: WorldConfig | None = None,
) -> ForwardContract:
    """Build the forwardable mount set from the same `world` module the node uses (C2 option 2).

    No network call is made: building the world constructs clients but never dials them (AC19),
    and the world is closed again immediately — this process serves no mount from it. The
    composition helper (`compose_serving_world`) runs F4's collision guard against the App's own
    route table, so a mount the engine would shadow fails App startup exactly as it fails the
    node tier's.

    Raises:
        WorldConfigError: the declared world is unusable. C7: the process must not start on a
            half-configured world.
    """
    io, aclose = await compose_serving_world(env=env, engine_routes=engine_routes, config=config)
    try:
        mounts = frozenset(node_mount_paths(io))
    finally:
        if aclose is not None:
            await aclose()
    return ForwardContract(mount_paths=mounts, config_digest=_config_file_digest(env))


def _config_file_digest(env: Mapping[str, str]) -> str | None:
    """sha256 of the declared-world file, or ``None`` when it cannot be read.

    WHY the FILE bytes and not the resolved object: both tiers read the same file from the same
    image, so the file hash is the one value they can compare without agreeing on a serialization.
    """
    path = Path(env.get(job_env.RUNNER_CONFIG, DEFAULT_CONFIG_PATH))
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None


class NodeForwarder:
    """The App's ASGI forwarder to the node Service.

    Installed on the App behind a `NodeMountRoute` (`app._install_forwarder`), which matches only
    the derived mount set — so every engine route keeps its own answer and only a declared mount
    reaches this class. The defensive 404 below covers a path outside the set all the same.

    ``timeout_s`` has no default (FX-34): the forward budget comes only from
    `Settings.node_forward_timeout_s`, which the chart derives from the node's own budgets.
    """

    def __init__(
        self,
        *,
        node_base_url: str,
        timeout_s: float,
        mount_paths: frozenset[str] = frozenset(),
        config_digest: str | None = None,
        identity_resolver: Callable[[Headers], Mapping[str, str]] | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._node_base_url = node_base_url
        self._mount_paths = mount_paths
        self._config_digest = config_digest
        self._identity_resolver = identity_resolver
        # WHY a shared client with keep-alive: C2 names it, and a per-request client would pay a
        # TCP/TLS handshake on every sync call. `timeout_s` bounds read/write/pool; connect has
        # its own short bound (`_CONNECT_TIMEOUT_S`). The node's own 30 s wrapper fires first.
        self._owns_client = client is None
        self._client = (
            client
            if client is not None
            else httpx.AsyncClient(timeout=httpx.Timeout(timeout_s, connect=_CONNECT_TIMEOUT_S))
        )

    # --- wiring --------------------------------------------------------------------------

    def set_mount_paths(self, paths: Iterable[str]) -> None:
        """Populate the forwardable set after startup derivation (production wiring)."""
        self._mount_paths = frozenset(paths)

    @property
    def mount_paths(self) -> frozenset[str]:
        """The forwardable set — what the App's `NodeMountRoute` matches against."""
        return self._mount_paths

    def set_config_digest(self, digest: str | None) -> None:
        self._config_digest = digest

    @property
    def config_digest(self) -> str | None:
        return self._config_digest

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    # --- ASGI ----------------------------------------------------------------------------

    async def __call__(self, scope: AsgiScope, receive: AsgiReceive, send: AsgiSend) -> None:
        if scope.get("type") != "http":
            return
        path = str(scope.get("path") or "")
        if path not in self._mount_paths:
            await send_url4_error(
                send,
                404,
                _ENDPOINT_NOT_FOUND,
                f"no mount is declared at {path!r}",
            )
            return
        identity = self._resolve_identity(scope)
        if not identity:
            await send_url4_error(send, 403, _IDENTITY_ACCESS_DENIED, _MISSING_IDENTITY_MESSAGE)
            return
        await self._forward(scope, send, identity)

    def _resolve_identity(self, scope: AsgiScope) -> Mapping[str, str]:
        """The caller's verified identity, or an empty mapping when none is present.

        ``identity_resolver`` is this class's one test seam: a test can present a verified value
        the client header does NOT contain, modelling Envoy's overwrite. Production leaves it
        ``None`` and reads the edge-injected header, which IS the trust boundary (C2, RD1).
        """
        headers = Headers(scope=scope)
        if self._identity_resolver is None:
            return job_env.identity_from_headers(headers)
        return dict(self._identity_resolver(headers))

    async def _forward(self, scope: AsgiScope, send: AsgiSend, identity: Mapping[str, str]) -> None:
        request = self._build_request(scope, identity)
        try:
            response = await self._send_with_policy(request)
        except _NodeTimeout:
            await send_url4_error(send, 504, _TIMEOUT_CODE, _TIMEOUT_MESSAGE)
            return
        except _NodeUnreachable:
            await send_url4_error(
                send, 503, _UPSTREAM_UNAVAILABLE, _UNREACHABLE_MESSAGE, retry_after=1
            )
            return
        await self._relay(send, response)

    def _build_request(self, scope: AsgiScope, identity: Mapping[str, str]) -> httpx.Request:
        raw_path = scope.get("raw_path") or str(scope.get("path") or "/").encode("latin-1")
        query = scope.get("query_string") or b""
        # Combine into ONE raw path: httpx's URL constructor ignores `query` when `raw_path` is
        # also given, so appending here is what keeps the wire query byte-for-byte unchanged.
        if query:
            raw_path = raw_path + b"?" + query
        url = httpx.URL(self._node_base_url).copy_with(raw_path=raw_path)
        inbound = [
            (name.decode("latin-1"), value.decode("latin-1"))
            for name, value in scope.get("headers") or ()
        ]
        return self._client.build_request(
            str(scope.get("method") or "GET"),
            url,
            headers=forwarded_headers(inbound, verified_identity=identity),
        )

    async def _send_with_policy(self, request: httpx.Request) -> httpx.Response:
        """Send once; retry exactly once when the request never reached the node (AC9/T8).

        A connect or pool timeout is a connection failure, not a slow node: nothing was sent, so
        it takes the retry like a refused connection (FX-33). A read or write timeout raises on
        the first attempt: the node may be mid-call and billing, and a retry doubles the cost. A
        5xx is a RESPONSE, so it is never retried at all — it is relayed unchanged.
        """
        try:
            return await self._client.send(request)
        except _CONNECTION_ERRORS:
            logger.warning("node connection failed; retrying once")
        except httpx.TimeoutException:
            raise _NodeTimeout from None
        except httpx.TransportError as exc:
            raise _NodeUnreachable from exc
        return await self._retry(request)

    async def _retry(self, request: httpx.Request) -> httpx.Response:
        try:
            return await self._client.send(request)
        except _CONNECTION_ERRORS as exc:
            raise _NodeUnreachable from exc
        except httpx.TimeoutException:
            raise _NodeTimeout from None
        except httpx.TransportError as exc:
            raise _NodeUnreachable from exc

    async def _relay(self, send: AsgiSend, response: httpx.Response) -> None:
        # A `303` is relayed unchanged: the node signs its Location under the App's own
        # `/artifacts/` route, and its query string carries the signature (OQ-3.2).
        body = await response.aread()
        headers = _response_headers(response, body)
        await response.aclose()
        await write(send, response.status_code, headers, body)


def _response_headers(response: httpx.Response, body: bytes) -> list[tuple[bytes, bytes]]:
    """The node's response headers, minus the unrelayed ones, with a corrected content-length."""
    headers = [
        (name.lower().encode("latin-1"), value.encode("latin-1"))
        for name, value in response.headers.multi_items()
        if name.lower() not in _NOT_RELAYED
    ]
    headers.append((b"content-length", str(len(body)).encode("ascii")))
    return headers


__all__ = [
    "ForwardContract",
    "NodeForwarder",
    "derive_forward_contract",
    "forwarded_headers",
]
