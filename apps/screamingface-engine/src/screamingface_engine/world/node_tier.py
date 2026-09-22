"""The node tier (prd/03 §2.1): one world, built once, served over url4's own guards.

FEATURE (unit 3, prd/03): `screamingface-engine node` is the deployed shape of the sync
surface. It builds the declared world ONCE at process start and serves
:meth:`Url4Node.asgi`, wrapped in url4's own admission and timeout middleware
(:func:`url4.cli._serve.build_asgi_app`) — this module adds only what url4's node does not:
per-request caller binding (F2 producer 2), a missing-``q`` explanation, readiness, and the
observability the accepted risks need to be visible.

# INVARIANT: the tier is STATELESS. It holds one world, one `httpx.AsyncClient` to aigateway
# (inside the world), and a caller's state exists only in the `request_scope` ContextVar bound
# for the duration of its request. Nothing derived from a request may be stored on `self`; the
# erd.md invariant is what makes one node safe for two concurrent callers (T1).

# INVARIANT: the admission (503 + `Retry-After`) and timeout (504) mechanics are url4's
# (`build_asgi_app`), never re-implemented here. This module passes a `ServeConfig` carrying the
# engine's ladder numbers and wraps the result; the only engine-owned response is the 504 body's
# wording, which the timeout clause of AC6 requires to name the ensemble path.

# WHY this module lives under `world/` rather than a new control-plane package: it serves the
# shared world and imports it, and `.claude/scripts/check_layering.py` classifies an unlisted
# top-level module as a shared leaf that must NOT import `world`. `world` is the one category
# importable by both halves, so the serving shape of the world belongs here beside
# `world/serving.py` (the F4 composition helper). It is not imported by `runner`, so the run
# mode's cold start is unchanged.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from collections.abc import (
    Awaitable,
    Callable,
    Iterable,
    Mapping,
    MutableMapping,
    Sequence,
)
from dataclasses import dataclass, replace
from typing import Any

import httpx
from prometheus_client import (
    CONTENT_TYPE_LATEST,
    CollectorRegistry,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
)

from screamingface_engine import job_env
from screamingface_engine.artifacts import (
    ArtifactWriter,
    ResultDelivery,
    allowed_result_bytes,
    decide_result_delivery,
)
from screamingface_engine.artifacts.signing import signed_artifact_path
from screamingface_engine.artifacts.wiring import result_writer_from_env
from screamingface_engine.benchmarks import EMPTY_BENCHMARKS, BenchmarkRegistry
from screamingface_engine.logs import run_scope
from screamingface_engine.request_scope import (
    AnswerSeedError,
    RequestScope,
    request_scope,
    request_scope_from_headers,
)
from screamingface_engine.world.config import WorldConfig, load_config
from screamingface_engine.world.serving import compose_serving_world
from url4.cli._serve import ServeConfig, build_asgi_app
from url4.core.errors import ErrorCode, ParseError
from url4.peer.server import Url4Node
from url4.streaming.trace import parse_traceparent
from url4.wire.subrequest import extract_expression_params

logger = logging.getLogger(__name__)

# These mirror httpx's own ASGI types (MutableMapping, not Mapping): `NodeTier` must be
# assignable to `httpx.ASGITransport`'s `_ASGIApp`, and a param typed `Mapping` is too wide to
# accept the narrower `MutableMapping` message dict the transport hands in.
AsgiScope = MutableMapping[str, Any]
AsgiReceive = Callable[[], Awaitable[MutableMapping[str, Any]]]
AsgiSend = Callable[[MutableMapping[str, Any]], Awaitable[None]]
AsgiApp = Callable[[AsgiScope, AsgiReceive, AsgiSend], Awaitable[None]]

# The paths the WRAPPER owns (they are not node mounts). Passed to the collision guard as the
# tier's "engine routes", so a declared mount at one of them fails startup instead of being
# silently shadowed by the wrapper — the same F4 guarantee the App gets from its literal routes.
_HEALTH_PATHS = ("/healthz", "/livez")
_READY_PATH = "/readyz"
_METRICS_PATH = "/metrics"
_OPS_PATHS = frozenset({*_HEALTH_PATHS, _READY_PATH, _METRICS_PATH})

_NODE_ENV = "URL4_CLOUD_NODE_"
REQUEST_TIMEOUT_ENV = f"{_NODE_ENV}REQUEST_TIMEOUT_S"
AIGATEWAY_TIMEOUT_ENV = f"{_NODE_ENV}AIGATEWAY_TIMEOUT_S"
MAX_INFLIGHT_PER_WORKER_ENV = f"{_NODE_ENV}MAX_INFLIGHT_PER_WORKER"
WORKERS_ENV = f"{_NODE_ENV}WORKERS"
RETRY_AFTER_ENV = f"{_NODE_ENV}RETRY_AFTER_S"
ARTIFACT_URL_TTL_ENV = f"{_NODE_ENV}ARTIFACT_URL_TTL_S"
HOST_ENV = f"{_NODE_ENV}HOST"
PORT_ENV = f"{_NODE_ENV}PORT"
LOG_LEVEL_ENV = f"{_NODE_ENV}LOG_LEVEL"

# WHY the env names are local to this module rather than in `job_env`: `job_env` is the JOB's
# contract (per-run and per-deploy values the chart writes onto a run), while these are the node
# tier's own Deployment. They move into `job_env` with the Helm unit that actually writes them;
# until then a name here cannot drift against a chart value that does not exist yet.

_MISSING_Q_MESSAGE = "this mount requires a `q` query parameter: GET <mount>?q=(context)!intent"

# Engine-added error codes (contracts.md C1/C5): `result_too_large` mirrors the run path's code
# for the same refusal; `artifact_spill_failed` names the failed deposit as the cause of a 502.
_RESULT_TOO_LARGE = "result_too_large"
_ARTIFACT_SPILL_FAILED = "artifact_spill_failed"


@dataclass(frozen=True, slots=True)
class NodeTierSettings:
    """Every number on the node tier's timeout/admission ladder, in ONE place (T4 refactor).

    The defaults are the plan's (`contracts.md` timeout ladder, `ans:Q5`): the request wrapper
    fails at 30 s, aigateway at 28 s so the inner failure wins and the caller gets a 502 naming
    the cause, and the in-flight cap is 2 × the worker count. No literal for any of these may
    appear anywhere else — a second copy is how a ladder ends up non-monotonic.

    ``artifact_url_ttl_s`` (OQ-3.2) is centralized here beside the ladder numbers: the node
    signs a spilled artifact's redirect with this TTL and the App enforces the same expiry from
    the signature, so the number has one home. `result_inline_cap_bytes`/`result_hard_cap_bytes`
    are here for the same reason — the sync spill path must decide without a second config read.
    """

    request_timeout_s: float = 30.0
    aigateway_timeout_s: float = 28.0
    max_inflight_per_worker: int = 2
    workers: int = 1
    retry_after_s: int = 1
    artifact_url_ttl_s: int = 600
    # WHY the caps live here TOO, even though `job_env` owns their names and defaults: the
    # sync tier must refuse an over-hard-cap body without a second read of the environment,
    # and a test needs one seam to aim the boundary at an exact byte. They read the SAME
    # `URL4_CLOUD_RESULT_*` names the run path reads, so the two paths cannot be capped
    # differently by a one-sided edit.
    result_inline_cap_bytes: int = job_env.DEFAULT_RESULT_INLINE_CAP_BYTES
    result_hard_cap_bytes: int = job_env.DEFAULT_RESULT_HARD_CAP_BYTES
    host: str = "0.0.0.0"
    port: int = 9109
    log_level: str = "info"

    @property
    def max_inflight(self) -> int:
        """2 × the worker count: the bound url4's admission gate enforces per process."""
        return self.max_inflight_per_worker * max(1, self.workers)

    @classmethod
    def from_env(cls, env: Mapping[str, str]) -> NodeTierSettings:
        """Resolve the tier's settings from its Deployment env, tolerantly and per field.

        INVARIANT: never raises on an unparseable value — this runs at boot, and the safe answer
        to a typo'd knob is the shipped default, not a pod that cannot start. A wrong-but-running
        tier is diagnosable from `/metrics`; a crashing one is not.
        """
        return cls(
            request_timeout_s=_float(env, REQUEST_TIMEOUT_ENV, 30.0),
            aigateway_timeout_s=_float(env, AIGATEWAY_TIMEOUT_ENV, 28.0),
            max_inflight_per_worker=_int(env, MAX_INFLIGHT_PER_WORKER_ENV, 2),
            workers=_int(env, WORKERS_ENV, 1),
            retry_after_s=_int(env, RETRY_AFTER_ENV, 1),
            artifact_url_ttl_s=_int(env, ARTIFACT_URL_TTL_ENV, 600),
            result_inline_cap_bytes=_int(
                env, job_env.RESULT_INLINE_CAP_BYTES, job_env.DEFAULT_RESULT_INLINE_CAP_BYTES
            ),
            result_hard_cap_bytes=_int(
                env, job_env.RESULT_HARD_CAP_BYTES, job_env.DEFAULT_RESULT_HARD_CAP_BYTES
            ),
            host=env.get(HOST_ENV) or "0.0.0.0",
            port=_int(env, PORT_ENV, 9109),
            log_level=env.get(LOG_LEVEL_ENV) or "info",
        )


def _float(env: Mapping[str, str], name: str, default: float) -> float:
    raw = env.get(name)
    if raw is None:
        return default
    try:
        return float(raw)
    except ValueError:
        logger.warning("ignoring unparseable %s=%r", name, raw)
        return default


def _int(env: Mapping[str, str], name: str, default: int) -> int:
    raw = env.get(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        logger.warning("ignoring unparseable %s=%r", name, raw)
        return default


@dataclass(slots=True)
class NodeReadiness:
    """What the readiness probe reports: world built AND the collision guard passed (AC18).

    Mutable and shared between the composition root and the ASGI app so a failed start is
    observable as a 503 on `/readyz` (the probe's answer) rather than only as a process that
    never came up. The run state is deliberately NOT stored here: readiness is a fact about the
    world, not about traffic.
    """

    ready: bool = False
    reason: str | None = None

    def succeed(self) -> None:
        self.ready = True
        self.reason = None

    def fail(self, reason: str) -> None:
        self.ready = False
        self.reason = reason


@dataclass(frozen=True, slots=True)
class NodeMetrics:
    """The node tier's own Prometheus registry and the three signals test-plan §9 names.

    WHY a private `CollectorRegistry`: the same reason `app.metrics.Metrics` uses one — repeated
    construction (across tests, or a future multi-app process) must not collide on the global
    default registry.
    """

    registry: CollectorRegistry
    request_duration: Histogram
    inflight: Gauge
    shed: Counter


def build_node_metrics() -> NodeMetrics:
    """Build the node tier's registry.

    ``request_duration`` is labelled by ``status``, so the 504 RATE (``_count{status="504"}``)
    and the 504 DURATION histogram come from one series — the signal that answers whether the
    accepted 30 s risk (R7) is wrong. ``inflight`` and ``shed`` answer whether the cap (R5) is.
    """
    registry = CollectorRegistry()
    request_duration = Histogram(
        "screamingface_engine_node_sync_request_duration_seconds",
        "Duration of sync-surface requests handled by the node tier.",
        ["status"],
        registry=registry,
    )
    inflight = Gauge(
        "screamingface_engine_node_sync_inflight",
        "Sync requests currently being handled by the node tier.",
        registry=registry,
    )
    shed = Counter(
        "screamingface_engine_node_sync_shed_total",
        "Sync requests shed with 503 because the node tier was at capacity.",
        registry=registry,
    )
    return NodeMetrics(
        registry=registry, request_duration=request_duration, inflight=inflight, shed=shed
    )


class NodeTierError(ValueError):
    """The node tier cannot serve: the declared world is not a url4 node, or it failed to build."""


class NodeTier:
    """The node tier's ASGI app plus the world it serves.

    Construct through :func:`build_node_tier`; the class itself is thin. It IS the ASGI app
    (``tier`` is passed to uvicorn directly), so there is one object to wire and no factory
    indirection between the composition root and what serves.
    """

    def __init__(
        self,
        *,
        settings: NodeTierSettings,
        metrics: NodeMetrics,
        readiness: NodeReadiness,
        artifact_store: ArtifactWriter | None = None,
        signing_key: str = "",
        clock: Callable[[], float] | None = None,
    ) -> None:
        self._settings = settings
        self._metrics = metrics
        self._readiness = readiness
        # FEATURE (unit 3, D9/OQ-3.2): the spill writer and the HMAC key the 303's Location is
        # signed with. `None` store / empty key is a working tier for bodies under the inline
        # cap; only a spill needs them, and a spill that cannot be signed or written is a 502
        # rather than an inline fallback. `clock` is injectable so the expiry is deterministic
        # in tests without freezing the process's real clock.
        self._artifact_store = artifact_store
        self._signing_key = signing_key
        self._clock = clock if clock is not None else time.time
        self._inner: AsgiApp | None = None
        self._node: Any = None
        self._aclose_world: Callable[[], Awaitable[None]] | None = None
        self._mounts: frozenset[str] = frozenset()
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
        if self._node is not None:
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
                await self.aclose()
                await send({"type": "lifespan.shutdown.complete"})
                return

    async def _http(self, scope: AsgiScope, receive: AsgiReceive, send: AsgiSend) -> None:
        path = str(scope.get("path") or "")
        method = str(scope.get("method") or "GET")
        if method == "GET" and path in _OPS_PATHS:
            await self._ops(path, send)
        elif not self._readiness.ready:
            # AC18: not ready means no traffic. The 503 carries the build/guard reason so a
            # direct probe (or a log-scraping operator) sees *why* the pod is out of rotation.
            await _send_error(
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
            await _send_error(send, 400, ErrorCode.MISSING_INTENT, _MISSING_Q_MESSAGE)
        else:
            await self._request(scope, receive, send, path)

    async def _request(
        self, scope: AsgiScope, receive: AsgiReceive, send: AsgiSend, path: str
    ) -> None:
        try:
            bound = request_scope_from_headers(_header_view(scope))
        except AnswerSeedError as exc:
            # A declared sitting must not silently run without its seed (OME-1038), so this is
            # the sync surface's one 400 that is not url4's dispatch refusing anything.
            await _send_error(send, 400, ErrorCode.MALFORMED_SOURCE, str(exc))
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
        inner = self._inner
        assert inner is not None  # guaranteed by build_node_tier before serving
        started = time.monotonic()
        # INVARIANT: spill wraps observation, so the metric records the status the CALLER
        # actually received (303/413/502 after a spill decision), not the node's pre-decision
        # 200. The 504 reword stays inside `_ObservedSend`, which spill only forwards.
        observed = _ObservedSend(send, self._settings.request_timeout_s)
        spill = _SpillSend(
            observed,
            store=self._artifact_store,
            inline_cap=self._settings.result_inline_cap_bytes,
            hard_cap=self._settings.result_hard_cap_bytes,
            signing_key=self._signing_key,
            ttl_s=self._settings.artifact_url_ttl_s,
            clock=self._clock,
        )
        self._metrics.inflight.inc()
        try:
            # INVARIANT: both scopes are bound around the call and reset after it, so a sibling
            # request task can never observe this caller's identity or this request's log context.
            with (
                request_scope(bound),
                run_scope(None, parse_traceparent(bound.traceparent), origin="sync"),
            ):
                await inner(scope, receive, spill)
        finally:
            self._metrics.inflight.dec()
            duration = time.monotonic() - started
            status = observed.status
            self._metrics.request_duration.labels(status=str(status)).observe(duration)
            if status == 503:
                self._metrics.shed.inc()
            logger.info(
                "sync request mount=%s status=%d duration_ms=%.1f",
                path,
                status,
                duration * 1000.0,
            )

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
        if path == _METRICS_PATH:
            body = generate_latest(self._metrics.registry)
            await _write(send, 200, [(b"content-type", CONTENT_TYPE_LATEST.encode())], body)
            return
        if path == _READY_PATH:
            if self._readiness.ready:
                await _write_json(send, 200, {"status": "ready"})
            else:
                await _write_json(
                    send,
                    503,
                    {"status": "not_ready", "reason": self._readiness.reason},
                    retry_after=self._settings.retry_after_s,
                )
            return
        await _write_json(send, 200, {"status": "live"})


async def build_node_tier(
    *,
    env: Mapping[str, str],
    settings: NodeTierSettings | None = None,
    config: WorldConfig | None = None,
    client: httpx.AsyncClient | None = None,
    tavily_client: httpx.AsyncClient | None = None,
    benchmarks: BenchmarkRegistry = EMPTY_BENCHMARKS,
    engine_routes: Iterable[str] | None = None,
    metrics: NodeMetrics | None = None,
    readiness: NodeReadiness | None = None,
    artifact_store: ArtifactWriter | None = None,
    artifact_signing_key: str | None = None,
    clock: Callable[[], float] | None = None,
) -> NodeTier:
    """Build the world ONCE and return a servable tier, or refuse to.

    ``config``/``client``/``tavily_client``/``benchmarks``/``metrics``/``readiness`` are injection
    seams for tests, exactly as in :func:`world.factory.build_world`.

    The aigateway timeout is OVERRIDDEN here (contracts.md C3): the image's ``url4.toml`` declares
    600 s, which is right for the ensemble path and wrong for a 30 s sync budget, so the tier
    replaces it rather than inheriting it. ``allow_outbound`` is forced false (defence in depth,
    `contracts.md` §10): a direct hit never runs the DAG, so a URL-valued context stays opaque
    text, and a denying outbound layer is the backstop.

    On any build/guard failure the injected readiness is marked failed before the error
    propagates, so `/readyz` (when the process is alive enough to answer) reports the reason.
    """
    resolved_settings = settings or NodeTierSettings.from_env(env)
    resolved_config = _tier_config(
        config if config is not None else load_config(env), resolved_settings
    )
    resolved_metrics = metrics or build_node_metrics()
    resolved_readiness = readiness or NodeReadiness()
    # The spill store is built from the SAME env the run path reads (`result_writer_from_env`),
    # so the sync tier and the Runner park into one place — and the App reads that one place.
    resolved_store = artifact_store if artifact_store is not None else result_writer_from_env(env)
    # An injected key wins; otherwise the deployment env supplies it. Empty means "no signer",
    # which fails a spill with a 502 rather than emitting an unsigned (unfetchable) redirect.
    resolved_signing_key = (
        artifact_signing_key
        if artifact_signing_key is not None
        else env.get(job_env.ARTIFACT_SIGNING_KEY, "")
    )
    reserved = frozenset(engine_routes) if engine_routes is not None else _OPS_PATHS
    tier = NodeTier(
        settings=resolved_settings,
        metrics=resolved_metrics,
        readiness=resolved_readiness,
        artifact_store=resolved_store,
        signing_key=resolved_signing_key,
        clock=clock,
    )
    try:
        io, world_aclose = await compose_serving_world(
            env=env,
            engine_routes=reserved,
            config=resolved_config,
            client=client,
            tavily_client=tavily_client,
            benchmarks=benchmarks,
        )
    except Exception as exc:
        resolved_readiness.fail(str(exc))
        raise
    asgi = getattr(io, "asgi", None)
    if not isinstance(io, Url4Node) or not callable(asgi):
        if world_aclose is not None:
            await world_aclose()
        reason = (
            "the declared world has no url4 node (no [aigateway] and no read-side mounts) — "
            "the node tier serves a node's ASGI surface and cannot serve an empty world"
        )
        resolved_readiness.fail(reason)
        raise NodeTierError(reason)
    tier._node = io
    tier._aclose_world = world_aclose
    tier._mounts = frozenset(io.processor_routes())
    tier._inner = build_asgi_app(
        io,
        ServeConfig(
            timeout=resolved_settings.request_timeout_s,
            max_inflight=resolved_settings.max_inflight,
        ),
    )
    resolved_readiness.succeed()
    return tier


def _tier_config(config: WorldConfig, settings: NodeTierSettings) -> WorldConfig:
    """Apply the tier's aigateway overrides to the declared world (allow_outbound + timeout)."""
    section = config.aigateway
    if section is None:
        return config
    return replace(
        config,
        aigateway=replace(
            section,
            allow_outbound=False,
            timeout_s=settings.aigateway_timeout_s,
        ),
    )


def serve(env: Mapping[str, str] | None = None) -> None:
    """Run the node tier under uvicorn — the `screamingface-engine node` entry point.

    uvicorn is imported lazily, like every other serving entry in this package, so importing
    the tier for a test or a config check does not require the server extra.
    """
    asyncio.run(_serve(env if env is not None else os.environ))


async def _serve(env: Mapping[str, str]) -> None:
    import uvicorn

    settings = NodeTierSettings.from_env(env)
    tier = await build_node_tier(env=env, settings=settings)
    logger.info(
        "node tier serving mounts=%d request_timeout_s=%.0f aigateway_timeout_s=%.0f "
        "max_inflight=%d",
        len(tier._mounts),
        settings.request_timeout_s,
        settings.aigateway_timeout_s,
        settings.max_inflight,
    )
    server = uvicorn.Server(
        uvicorn.Config(tier, host=settings.host, port=settings.port, log_level=settings.log_level)
    )
    try:
        await server.serve()
    finally:
        await tier.aclose()


# --- response plumbing ---------------------------------------------------------------


class _ObservedSend:
    """Wraps the ASGI ``send`` to record the status and reword the 504 body.

    WHY the reword lives at the send boundary: url4's wrapper is the timeout OWNER (it decides
    when a request has exceeded its budget), but the engine owns the MESSAGE the sync contract
    promises (AC6 — long work belongs on the ensemble path). Intercepting the one message url4
    emits keeps the timeout mechanic url4's and the wording the engine's; re-implementing the
    timeout to change a string would be the thing `build_asgi_app` exists to prevent.
    """

    __slots__ = ("_send", "_timeout", "_rewrite", "_status")

    def __init__(self, send: AsgiSend, timeout: float) -> None:
        self._send = send
        self._timeout = timeout
        self._rewrite = False
        self._status = 0

    @property
    def status(self) -> int:
        return self._status

    async def __call__(self, message: MutableMapping[str, Any]) -> None:
        if message["type"] == "http.response.start":
            self._status = int(message.get("status", 0))
            if self._status == 504:
                self._rewrite = True
                message = {
                    **message,
                    "headers": [
                        (name, value)
                        for name, value in message.get("headers", ())
                        if name.lower() != b"content-length"
                    ],
                }
        elif message["type"] == "http.response.body" and self._rewrite:
            self._rewrite = False
            message = {
                **message,
                "body": _timeout_body(self._timeout),
                "more_body": False,
            }
        await self._send(message)


class _SpillSend:
    """Buffer one sync response and, over the inline cap, park it and redirect (D9, C5).

    FEATURE (unit 3, prd/03 §2.4): a body over 512 KiB is written to the artifact store and the
    caller gets ``303 See Other`` with a short-lived signed ``Location``; a body over the hard
    cap is ``413`` and NOTHING is written; a failed deposit is ``502`` and the body is NEVER
    returned inline — falling back would defeat the memory protection the caps exist for.

    WHY at the ASGI send boundary: url4's node computes the whole body before emitting it
    (``_StartGuard``), so the sync tier sees the complete response here without re-implementing
    dispatch, and ``node.fetch``'s output is the one place a size can be measured honestly.

    # INVARIANT: a response that is not a 2xx is forwarded unchanged. Error envelopes are
    # small by construction, and spilling one would replace a meaningful ``error.code`` with a
    # redirect the caller cannot interpret.
    """

    __slots__ = (
        "_send",
        "_store",
        "_inline_cap",
        "_hard_cap",
        "_signing_key",
        "_ttl_s",
        "_clock",
        "_status",
        "_headers",
        "_body",
    )

    def __init__(
        self,
        send: AsgiSend,
        *,
        store: ArtifactWriter | None,
        inline_cap: int,
        hard_cap: int,
        signing_key: str,
        ttl_s: int,
        clock: Callable[[], float],
    ) -> None:
        self._send = send
        self._store = store
        self._inline_cap = inline_cap
        self._hard_cap = hard_cap
        self._signing_key = signing_key
        self._ttl_s = ttl_s
        self._clock = clock
        self._status = 0
        self._headers: list[tuple[bytes, bytes]] = []
        self._body = bytearray()

    async def __call__(self, message: MutableMapping[str, Any]) -> None:
        kind = message["type"]
        if kind == "http.response.start":
            # Hold the start until the body is complete: the decision (inline/spill/refuse)
            # changes the status, so emitting the node's 200 first would make the rewrite
            # impossible. url4 sends the body in one message, so this holds nothing long.
            self._status = int(message.get("status", 0))
            self._headers = list(message.get("headers", ()))
            self._body = bytearray()
            return
        if kind != "http.response.body":
            await self._send(message)
            return
        self._body.extend(message.get("body", b""))
        if message.get("more_body"):
            return
        await self._finish()

    async def _finish(self) -> None:
        body = bytes(self._body)
        decision = decide_result_delivery(
            len(body),
            inline_cap=self._inline_cap,
            hard_cap=self._hard_cap,
            spill_available=self._store is not None,
        )
        if not _is_success(self._status) or decision is ResultDelivery.INLINE:
            await self._emit(self._status, self._headers, body)
            return
        if decision is ResultDelivery.TOO_LARGE:
            allowed = allowed_result_bytes(
                self._inline_cap, self._hard_cap, spill_available=self._store is not None
            )
            await _send_error(
                self._send,
                413,
                _RESULT_TOO_LARGE,
                f"sync response is {len(body)} bytes, cap is {allowed} bytes — the result is "
                "too large to deliver; reduce the request or use the ensemble path",
            )
            return
        assert self._store is not None
        try:
            # WHY a worker thread: the write hashes and may push to object storage — sync, and
            # blocking the loop here would stall every concurrent request for the deposit.
            location = await asyncio.to_thread(self._spill, body)
        except Exception:
            logger.exception("artifact spill failed for a %d-byte sync response", len(body))
            await _send_error(
                self._send,
                502,
                _ARTIFACT_SPILL_FAILED,
                "the response could not be parked in artifact storage; it is NOT returned "
                "inline, because that would defeat the size cap it exceeded",
            )
            return
        await self._emit(
            303,
            [(b"location", location.encode("latin-1")), (b"content-length", b"0")],
            b"",
        )

    def _spill(self, body: bytes) -> str:
        """Park the complete body and sign its redirect URL. Blocking; runs in a thread."""
        assert self._store is not None
        ref = self._store.write_bytes(body)
        return signed_artifact_path(
            ref.id, key=self._signing_key, ttl_s=self._ttl_s, now=self._clock
        )

    async def _emit(self, status: int, headers: Sequence[tuple[bytes, bytes]], body: bytes) -> None:
        await self._send(
            {"type": "http.response.start", "status": status, "headers": list(headers)}
        )
        await self._send({"type": "http.response.body", "body": body})


def _is_success(status: int) -> bool:
    return 200 <= status < 300


def _timeout_body(timeout: float) -> bytes:
    payload = {
        "error": {
            "code": str(ErrorCode.TIMEOUT),
            "message": (
                f"sync request exceeded the {timeout:g}s budget — long-running work belongs on "
                "the ensemble path (POST /token, attach the WebSocket, then GET /?q=<expression>)"
            ),
        }
    }
    return json.dumps(payload).encode()


async def _send_error(
    send: AsgiSend, status: int, code: str, message: str, *, retry_after: int | None = None
) -> None:
    headers = [(b"content-type", b"application/json")]
    if retry_after is not None:
        headers.append((b"retry-after", str(retry_after).encode()))
    body = json.dumps({"error": {"code": code, "message": message}}).encode()
    await _write(send, status, headers, body)


async def _write(
    send: AsgiSend, status: int, headers: Sequence[tuple[bytes, bytes]], body: bytes
) -> None:
    await send({"type": "http.response.start", "status": status, "headers": list(headers)})
    await send({"type": "http.response.body", "body": body})


async def _write_json(
    send: AsgiSend, status: int, payload: Mapping[str, Any], *, retry_after: int | None = None
) -> None:
    headers = [(b"content-type", b"application/json")]
    if retry_after is not None:
        headers.append((b"retry-after", str(retry_after).encode()))
    await _write(send, status, headers, json.dumps(payload).encode())


class _CaseInsensitiveHeaders(Mapping[str, str]):
    """An ASGI header list as a case-insensitive mapping.

    Raw ASGI gives headers as ``(bytes, bytes)`` pairs, whose order and casing are the client's.
    `job_env.identity_from_headers` and the sync producer look up canonical names
    (``X-User-Email``), so they need the case-insensitive view HTTP promises — the same lookup
    Starlette's ``Headers`` provides on the App side. Deliberately not Starlette: the node tier's
    request path stays framework-free, and this is the whole of what it needs.
    """

    __slots__ = ("_values",)

    def __init__(self, pairs: Iterable[tuple[str, str]]) -> None:
        self._values = {name.lower(): value for name, value in pairs}

    def __getitem__(self, key: str) -> str:
        return self._values[key.lower()]

    def __iter__(self) -> Any:
        return iter(self._values)

    def __len__(self) -> int:
        return len(self._values)

    def get(self, key: str, default: str | None = None) -> str | None:  # type: ignore[override]
        return self._values.get(key.lower(), default)


def _header_view(scope: AsgiScope) -> Mapping[str, str]:
    return _CaseInsensitiveHeaders(
        (name.decode("latin-1"), value.decode("latin-1"))
        for name, value in scope.get("headers") or ()
    )


__all__ = [
    "AsgiApp",
    "NodeMetrics",
    "NodeReadiness",
    "NodeTier",
    "NodeTierError",
    "NodeTierSettings",
    "build_node_metrics",
    "build_node_tier",
    "serve",
]
