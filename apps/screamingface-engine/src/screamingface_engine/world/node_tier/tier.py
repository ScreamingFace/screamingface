"""The node tier (prd/03 §2.1): one world, built once, served over url4's own guards.

FEATURE (unit 3, prd/03): `screamingface-engine node` is the deployed shape of the sync
surface. It builds the declared world ONCE at process start and serves
:meth:`Url4Node.asgi`, wrapped in url4's own admission and timeout middleware
(:func:`url4.cli._serve.build_asgi_app`) — this module adds only what url4's node does not:
per-request caller binding (F2 producer 2), a missing-``q`` explanation, readiness, and the
observability the accepted risks need to be visible.

Identity trust (RD1): the SAME model as the ensemble path. Envoy's SecurityPolicy at the edge
sets ``X-User-Email``; the App trusts it, strips any client copy and re-sets it on the forward.
The node trusts the App: the chart's node-tier NetworkPolicy
(`deploy/helm/templates/networkpolicy-node.yaml`, named `<fullname>-node`) admits ingress on the
mount port only from the App's pods, so no other caller can reach this header reader. There is
no second verification step here, by decision.

# INVARIANT: the tier is STATELESS. It holds one world, one `httpx.AsyncClient` to aigateway
# (inside the world), and a caller's state exists only in the `request_scope` ContextVar bound
# for the duration of its request. Nothing derived from a request may be stored on `self`; the
# erd.md invariant is what makes one node safe for two concurrent callers (T1).

# INVARIANT: the timeout (504) mechanic is url4's (`build_asgi_app`), never re-implemented here.
# Admission has two owners at ONE cap (§2.2a): url4 admits per EVALUATION (its slot is freed when
# `inner` returns), and the tier admits per REQUEST, because only the tier sees the spill phase
# after that. The tier's gate runs first, so url4's gate is a backstop that cannot fire first.
# Both answer the same `503 overloaded` envelope. Beyond that the engine owns only the 504 body's
# wording, the `Retry-After` value, and the 500 → 502 remap for a downstream failure (§2.2).

# WHY this package lives under `world/` rather than a new control-plane package: it serves the
# shared world and imports it, and `.claude/scripts/check_layering.py` classifies an unlisted
# top-level module as a shared leaf that must NOT import `world`. `world` is the one category
# importable by both halves, so the serving shape of the world belongs here beside
# `world/serving.py` (the F4 composition helper). It is not imported by `runner`, so the run
# mode's cold start is unchanged.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from starlette.datastructures import Headers

from screamingface_engine.artifacts import ArtifactWriter
from screamingface_engine.logs import run_scope
from screamingface_engine.request_scope import (
    AnswerSeedError,
    RequestScope,
    request_scope,
    request_scope_from_headers,
)
from screamingface_engine.world.node_tier.metrics import NodeMetrics
from screamingface_engine.world.node_tier.send import (
    _OVERLOADED,
    _OVERLOADED_MESSAGE,
    _ObservedSend,
    _SpillSend,
)
from screamingface_engine.world.node_tier.settings import NodeTierSettings
from screamingface_engine.world.wire import (
    AsgiApp,
    AsgiReceive,
    AsgiScope,
    AsgiSend,
    send_url4_error,
    write_json,
)
from url4.core.errors import ErrorCode, ParseError
from url4.peer.server import Url4Node
from url4.streaming.trace import parse_traceparent
from url4.wire.subrequest import extract_expression_params

logger = logging.getLogger(__package__)

# The paths the WRAPPER owns (they are not node mounts). `build` passes them to the collision
# guard as the tier's "engine routes", so a declared mount at one of them fails startup instead
# of being silently shadowed by the wrapper — the F4 guarantee the App gets from its literals.
# `/metrics` is NOT here (FX-5): it is served on its own port, so on this port it is a path
# like any other.
_HEALTH_PATHS = ("/healthz", "/livez")
_READY_PATH = "/readyz"
OPS_PATHS = frozenset({*_HEALTH_PATHS, _READY_PATH})

_MISSING_Q_MESSAGE = "this mount requires a `q` query parameter: GET <mount>?q=(context)!intent"
# Engine-added code (contracts.md C1): a present-but-unusable request header.
_MALFORMED_HEADER = "malformed_header"
_DRAINING = "draining"
# The final codes that mean "the request budget ran out" (§2.2b, the R7 signal): url4's 504 and
# the connector's deadline-bounded 502.
_BUDGET_EXHAUSTED_CODES = frozenset({str(ErrorCode.TIMEOUT), "aigateway_deadline_exceeded"})


@dataclass(slots=True)
class NodeReadiness:
    """What the readiness probe reports. Drain-only (RD2).

    Readiness fails in exactly two cases: the world failed to build (or the collision guard
    refused it, AC18), and the pod is draining (shutdown has started). It does NOT fail under
    saturation: a busy pod that left the Service would move its load onto the other pods and
    could take them all out of rotation. Saturation is url4's 503 + ``Retry-After`` instead.

    Mutable and shared between the composition root and the ASGI app so a failed start is
    observable as a 503 on `/readyz` rather than only as a process that never came up.
    """

    ready: bool = False
    reason: str | None = None

    def succeed(self) -> None:
        self.ready = True
        self.reason = None

    def fail(self, reason: str) -> None:
        self.ready = False
        self.reason = reason

    def drain(self) -> None:
        """Leave rotation because shutdown has started (SIGTERM or lifespan shutdown)."""
        self.fail(_DRAINING)


class NodeTier:
    """The node tier's ASGI app plus the world it serves.

    Construct through :func:`~screamingface_engine.world.node_tier.build.build_node_tier`, which
    builds the world first and then this object with every field (FX-15). It IS the ASGI app
    (``tier`` is passed to uvicorn directly), so there is one object to wire and no factory
    indirection.
    """

    def __init__(
        self,
        *,
        settings: NodeTierSettings,
        metrics: NodeMetrics,
        readiness: NodeReadiness,
        node: Url4Node,
        inner: AsgiApp,
        mounts: frozenset[str],
        world_aclose: Callable[[], Awaitable[None]] | None,
        artifact_store: ArtifactWriter | None = None,
        signing_key: str = "",
        clock: Callable[[], float] | None = None,
    ) -> None:
        self._settings = settings
        self._metrics = metrics
        self._readiness = readiness
        self._node = node
        self._inner = inner
        self._mounts = mounts
        self._aclose_world = world_aclose
        # FEATURE (unit 3, D9/OQ-3.2): the spill writer and the HMAC key the 303's Location is
        # signed with. `clock` is injectable so the expiry is deterministic in tests without
        # freezing the process's real clock.
        self._artifact_store = artifact_store
        self._signing_key = signing_key
        self._clock = clock if clock is not None else time.time
        # §2.2a: the requests admitted and not yet finished, spill phase included. A count, not
        # caller state, so the STATELESS invariant holds.
        self._inflight = 0
        self._closed = False

    # --- what the composition root reads -------------------------------------------------

    @property
    def settings(self) -> NodeTierSettings:
        return self._settings

    @property
    def readiness(self) -> NodeReadiness:
        return self._readiness

    @property
    def metrics(self) -> NodeMetrics:
        return self._metrics

    @property
    def mounts(self) -> frozenset[str]:
        """The node's declared mount paths (its processor routes)."""
        return self._mounts

    # --- shutdown ------------------------------------------------------------------------

    async def aclose(self) -> None:
        """Release the world and the node exactly once.

        Idempotent because two shutdown paths meet here: the ASGI lifespan (uvicorn's graceful
        drain) and the composition root's own `finally`. A double close of an httpx client is
        harmless in practice but not in principle — one owner, one call.
        """
        if self._closed:
            return
        self._closed = True
        if self._aclose_world is not None:
            await self._aclose_world()
        await self._node.aclose()

    # --- ASGI ----------------------------------------------------------------------------

    async def __call__(self, scope: AsgiScope, receive: AsgiReceive, send: AsgiSend) -> None:
        kind = scope.get("type")
        if kind == "lifespan":
            await self._lifespan(receive, send)
        elif kind == "http":
            await self._http(scope, receive, send)
        elif kind == "websocket":
            # No websocket surface on the node tier (the ensemble path owns streaming). Refuse
            # explicitly rather than hanging the connection on a handler that will never answer.
            await send({"type": "websocket.close"})

    async def _lifespan(self, receive: AsgiReceive, send: AsgiSend) -> None:
        while True:
            message = await receive()
            if message["type"] == "lifespan.startup":
                # The world is already built (and guarded) by `build_node_tier` — the tier does
                # not serve until that returns — so startup has nothing left to do but ack.
                await send({"type": "lifespan.startup.complete"})
            elif message["type"] == "lifespan.shutdown":
                # RD2: out of rotation before the world closes (SIGTERM drains earlier still).
                self._readiness.drain()
                await self.aclose()
                await send({"type": "lifespan.shutdown.complete"})
                return

    async def _http(self, scope: AsgiScope, receive: AsgiReceive, send: AsgiSend) -> None:
        path = str(scope.get("path") or "")
        method = str(scope.get("method") or "GET")
        if method == "GET" and path in OPS_PATHS:
            await self._ops(path, send)
        elif not self._readiness.ready:
            # AC18: not ready means no traffic. The 503 carries the build/guard reason so a
            # direct probe (or a log-scraping operator) sees *why* the pod is out of rotation.
            await send_url4_error(
                send,
                503,
                "not_ready",
                self._readiness.reason or "node tier is not ready",
                retry_after=self._settings.retry_after_s,
            )
        elif method == "GET" and self._is_mount_missing_q(scope):
            # T9/AC11: url4's dispatch only consults endpoints when `q` is present, so a bare
            # mount path falls through to the data routes and answers 404 endpoint_not_found —
            # telling a caller who forgot the query that the mount does not exist. Intercept
            # BEFORE dispatch so the message names the missing parameter instead.
            await send_url4_error(send, 400, ErrorCode.MISSING_INTENT, _MISSING_Q_MESSAGE)
        else:
            await self._request(scope, receive, send, path)

    async def _request(
        self, scope: AsgiScope, receive: AsgiReceive, send: AsgiSend, path: str
    ) -> None:
        try:
            # Identity trust (RD1): see the module docstring — the App sets the header, and
            # only the App can reach this port.
            bound = request_scope_from_headers(
                Headers(scope=scope),
                deadline=time.monotonic() + self._settings.request_timeout_s,
            )
        except AnswerSeedError as exc:
            # A declared sitting must not silently run without its seed (OME-1038), so this is
            # the sync surface's one 400 that is not url4's dispatch refusing anything (FX-17).
            await send_url4_error(send, 400, _MALFORMED_HEADER, str(exc))
            return
        await self._dispatch(scope, receive, send, bound, path)

    async def _dispatch(
        self,
        scope: AsgiScope,
        receive: AsgiReceive,
        send: AsgiSend,
        bound: RequestScope,
        path: str,
    ) -> None:
        started = time.monotonic()
        # INVARIANT: spill wraps observation, so the metric records the status the CALLER
        # actually received (303/413/502 after a spill decision), not the node's pre-decision
        # 200. The 504 reword stays inside `_ObservedSend`, which spill only writes to.
        observed = _ObservedSend(send, self._settings.request_timeout_s)
        spill = _SpillSend(
            observed,
            store=self._artifact_store,
            inline_cap=self._settings.result_inline_cap_bytes,
            hard_cap=self._settings.result_hard_cap_bytes,
            signing_key=self._signing_key,
            ttl_s=self._settings.artifact_url_ttl_s,
            clock=self._clock,
            spill_timeout_s=self._settings.spill_timeout_s,
            retry_after_s=self._settings.retry_after_s,
        )
        # INVARIANT: both scopes are bound around the call and reset after it, so a sibling
        # request task can never observe this caller's identity or this request's log context.
        # The per-request log line is INSIDE them (FX-6), so it carries origin and trace_id.
        with (
            request_scope(bound),
            run_scope(None, parse_traceparent(bound.traceparent), origin="sync"),
        ):
            admitted = self._admit()
            try:
                if admitted:
                    await self._inner(scope, receive, spill)
                    # WHY after `inner` returns (§2.2): the finish — and its spill — runs outside
                    # url4's `asyncio.timeout`, so a late spill still answers the caller.
                    await spill.finish()
                else:
                    self._metrics.shed.inc()
                    await send_url4_error(
                        observed,
                        503,
                        _OVERLOADED,
                        _OVERLOADED_MESSAGE,
                        retry_after=self._settings.retry_after_s,
                    )
            finally:
                if admitted:
                    self._release()
                duration = time.monotonic() - started
                status = observed.status
                self._metrics.request_duration.labels(status=str(status)).observe(duration)
                if observed.code in _BUDGET_EXHAUSTED_CODES:
                    self._metrics.budget_exhausted.inc()
                logger.info(
                    "sync request mount=%s status=%d duration_ms=%.1f",
                    path,
                    status,
                    duration * 1000.0,
                )

    def _admit(self) -> bool:
        """Take an in-flight slot, or refuse at the cap (§2.2a).

        INVARIANT: check-then-increment with no `await` between, so on the single-threaded loop
        two requests can never both pass a full gate — the same rule url4's own gate follows.
        """
        if self._inflight >= self._settings.max_inflight:
            return False
        self._inflight += 1
        self._metrics.inflight.inc()
        return True

    def _release(self) -> None:
        self._inflight -= 1
        self._metrics.inflight.dec()

    def _is_mount_missing_q(self, scope: AsgiScope) -> bool:
        path = str(scope.get("path") or "")
        if path not in self._mounts:
            return False
        query = (scope.get("query_string") or b"").decode("latin-1")
        try:
            _params, q = extract_expression_params(query)
        except ParseError:
            # A malformed query is url4's to report (400 malformed_source); do not shadow it.
            return False
        return q is None

    async def _ops(self, path: str, send: AsgiSend) -> None:
        if path == _READY_PATH:
            if self._readiness.ready:
                await write_json(send, 200, {"status": "ready"})
            else:
                await write_json(
                    send,
                    503,
                    {"status": "not_ready", "reason": self._readiness.reason},
                    retry_after=self._settings.retry_after_s,
                )
            return
        await write_json(send, 200, {"status": "live"})


__all__ = ["OPS_PATHS", "NodeReadiness", "NodeTier"]
