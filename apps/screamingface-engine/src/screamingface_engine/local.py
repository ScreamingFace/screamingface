"""Local mode's composition root — the App and the run mode fused into one process.

    screamingface-engine serve --local

Runs the whole protocol with no Kubernetes and no NATS: an `InProcessJobRunner` spawns each run
as an `asyncio.Task` in the serving process, and an `InMemoryEventStream` carries its frames to
the same REST sync-hold and WS pump a deployed App reads from JetStream. Everything above the two
swapped adapters — auth, the 428 subscriber gate, sequencing, replay-from, the model catalog — is
the production code path, unmodified.

The one exception is the in-process sync surface (unit 3, contracts.md C8). A local sync call gets
none of the deployed node tier's guards: no 30 s timeout ladder, no admission cap, no missing-``q``
400 and no fair-share gate — only the in-process runs are gated. See `_LocalNodeMount`.

# INVARIANT: this module is the ONLY place the control plane and the run mode meet, which is why
# `.claude/scripts/check_layering.py` lists it in BOTH `CONTROL_PLANE` and `_EXEMPT` — exactly as
# it does `cli.py`, and for the same reason. Being exempt is not the same as being unexamined:
# naming it in `CONTROL_PLANE` is what puts it in the gate's field of view at all, so a future
# reader sees a declared exception rather than a module that quietly evaded the rule.
#
# INVARIANT: nothing imports this module except `cli.py`. `screamingface_engine.app`
# must stay importable without dragging in the engine, which is what keeps a
# deployed App's cold start unchanged — `tests/unit/test_local_app.py` pins the
# direction of that edge.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Mapping
from functools import partial
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from starlette.datastructures import Headers

from screamingface_engine import job_env
from screamingface_engine.adapters.inprocess import InProcessJobRunner
from screamingface_engine.adapters.memory import InMemoryEventStream
from screamingface_engine.app import create_app
from screamingface_engine.benchmarks import (
    BENCHMARK_ASSETS_ENV,
    EMPTY_BENCHMARKS,
    BenchmarkRegistry,
)
from screamingface_engine.benchmarks.builtins import BUILTIN_BENCHMARKS
from screamingface_engine.catalog import build_executable_catalog_service
from screamingface_engine.config import INSECURE_DEFAULT_JWT_SECRET, Settings
from screamingface_engine.connections import build_connections
from screamingface_engine.metrics import register_fair_share_metrics
from screamingface_engine.request_scope import (
    AnswerSeedError,
    request_scope,
    request_scope_from_headers,
    trace_from_headers,
)
from screamingface_engine.rest.forwarder import forwarded_headers
from screamingface_engine.runner.fair_share import FairShareGate
from screamingface_engine.trace_scope import run_trace_scope
from screamingface_engine.world.serving import (
    NodeMountRoute,
    compose_serving_world,
    engine_route_paths,
    install_node_route,
    node_eval_path,
    node_mount_paths,
)
from screamingface_engine.world.wire import AsgiReceive, AsgiScope, AsgiSend, send_url4_error

_logger = logging.getLogger(__name__)

LOCAL_HOST = "127.0.0.1"
"""INVARIANT: loopback only. Local mode deliberately skips `_require_prod_secret`, so it may be
running on the publicly-known dev JWT secret — anyone who can reach the port could mint a
capability token for any topic. The bind address is what keeps that from being remotely
reachable, and it is not configurable for that reason."""


class _EngineRuntimeLogHandler(logging.StreamHandler):
    """Marker subclass so repeated `create_local_app` calls stay idempotent."""


def _configure_engine_logging() -> None:
    """Route the engine's own INFO logs to stderr so they reach the runtime log.

    WHY here, in the LOCAL composition root: uvicorn's config routes only its own
    loggers, and Python's last-resort handler drops INFO — so the connector's
    model-call lifecycle lines (OME-1126) would vanish. The handler is created after
    `capture_runtime_log` has replaced stderr, so the lines land in `runtime.log`
    tagged with the serving service. The deployed App path is untouched — its log
    routing is the deployment's concern.
    """
    package_logger = logging.getLogger("screamingface_engine")
    if any(isinstance(handler, _EngineRuntimeLogHandler) for handler in package_logger.handlers):
        return
    handler = _EngineRuntimeLogHandler()
    handler.setFormatter(logging.Formatter("%(levelname)s:     %(name)s %(message)s"))
    package_logger.addHandler(handler)
    package_logger.setLevel(logging.INFO)


def _warn_if_insecure(settings: Settings) -> None:
    """Say plainly that auth is open when the dev default secret is in play.

    `create_app_from_env` REFUSES to boot on this secret; local mode accepts it so a developer
    need not mint one, and pairs that with the loopback bind above. The warning exists so the
    trade is visible in the log rather than inferred from the absence of an error.
    """
    if settings.jwt_secret == INSECURE_DEFAULT_JWT_SECRET:
        _logger.warning(
            "local mode is using the INSECURE default JWT secret — anyone who can reach %s can "
            "mint a capability token for any topic. Set URL4_CLOUD_JWT_SECRET to change it; "
            "never expose this process beyond loopback.",
            LOCAL_HOST,
        )


def _with_runner_config(env: Mapping[str, str]) -> Mapping[str, str]:
    """Point an unconfigured local run at the repo's own ``url4.toml``.

    The declared world is baked into the IMAGE at ``/etc/url4/url4.toml`` (the Dockerfile copies
    it there) and is not installed by the wheel — so in a dev checkout that path does not exist
    and every local run would terminate as ``failed`` with a missing-config error before it could
    reach a model. Falling back to the checkout's own ``url4.toml``, which sits two levels above
    this package, is what makes `--local` usable straight out of a clone.

    Deliberately narrow: an explicit ``URL4_RUNNER_CONFIG`` always wins, and so does a real
    ``/etc/url4/url4.toml`` — this only fills a gap that exists nowhere but a source checkout.
    """
    from screamingface_engine.world.config import DEFAULT_CONFIG_PATH

    if job_env.RUNNER_CONFIG in env or Path(DEFAULT_CONFIG_PATH).is_file():
        return env
    candidate = Path(__file__).resolve().parents[2] / "url4.toml"
    if not candidate.is_file():
        return env
    _logger.info("local mode: using the checkout's runner config at %s", candidate)
    return {**env, job_env.RUNNER_CONFIG: str(candidate)}


def _local_benchmarks(env: Mapping[str, str]) -> BenchmarkRegistry:
    """The Benchmarks a local run installs: the builtins only where assets were declared.

    WHY not the builtins unconditionally (which is what this used to be): `benchmarks.install()`
    runs while the WORLD is built — before, and independent of, what the expression addresses —
    so a Benchmark whose assets are absent fails EVERY run, including one that references no
    Benchmark at all. DRACO's cases live at ``/opt/benchmarks/draco/cases.json``, a path the
    Dockerfile creates and a source checkout does not, so the default was guaranteed to fail
    exactly where local mode is meant to be usable (OME-795).

    INVARIANT: naming an asset root is the operator asserting the assets exist. Local mode takes
    that at face value and installs, so a wrong path fails loudly rather than silently serving a
    Benchmark-less Engine. Absence of the variable is the only "install nothing" signal.
    """
    return BUILTIN_BENCHMARKS if BENCHMARK_ASSETS_ENV in env else EMPTY_BENCHMARKS


def _with_local_gateway(settings: Settings) -> Settings:
    """Substitute the loopback default into the ONE address the whole App resolves.

    INVARIANT: `aigateway_base_url` still wins when stated — the local value is a fallback, not
    an override, so a developer who names a gateway never has half the App quietly talk to a
    different one.
    """
    if settings.aigateway_base_url is not None:
        return settings
    return settings.model_copy(update={"aigateway_base_url": settings.local_aigateway_base_url})


def _local_activity_configuration(
    supplied: Settings | None, env: Mapping[str, str] | None
) -> tuple[Settings, str]:
    """Resolve explicit Settings > injected env > process env > off."""
    source = env if env is not None else os.environ
    level = (
        supplied.activity_level
        if supplied is not None and supplied.activity_level_is_explicit
        else source.get(job_env.ACTIVITY_LEVEL, "off")
    )
    # WHY: align the effective Settings with observer policy without mutating the caller.
    # INVARIANT: observation_factories validates this selection before app construction.
    settings = (
        supplied.model_copy(update={"activity_level": level})
        if supplied is not None
        else Settings(activity_level=level)
    )
    return settings, level


_NODE_MOUNT_NAME = "node"


class _LocalNodeMount:
    """Serve the shared node's ASGI surface in-process, behind the App's identity boundary (C8).

    FEATURE (unit 3, prd/03 §2.3): ``serve --local`` has no forwarder and no network hop, so the
    node's ASGI app is served directly by the App. It sits behind the SAME `NodeMountRoute` the
    deployed forwarder uses, installed last by the same `install_node_route`: only the node's
    mounts and its eval path reach it, and every other path keeps the engine's own answer.

    # INVARIANT: identity is BUILT, never copied. This wrapper runs the SAME strip-and-reset
    # helper the deployed forwarder uses (``forwarded_headers``): only the allowlisted request
    # headers plus the identity survive, so a client's Cookie, Authorization or URL4-Capability
    # never reaches the node. Local mode has no edge to verify against, so the header it reads IS
    # the caller's claim — the bind is loopback-only precisely because there is no trust boundary
    # here, which is also why this shape must never be deployed (C8).

    # INVARIANT: the caller's state is bound by the SAME sync scope producer the node tier uses
    # (``request_scope_from_headers``), so a mount call reads its identity, profile, seed and
    # cache policy from the ContextVar exactly as a deployed node does. F2's per-request binding
    # is what lets this one node serve both the mount and every in-process run without mixing
    # them.

    NOT a deployment option (C8). A local sync call gets none of the node tier's guards: no 30 s
    timeout ladder, no admission cap, no missing-``q`` 400 and no fair-share gate — only the
    in-process RUNS are gated. There is no forwarder and no NetworkPolicy either. It is the
    development shape of the sync surface.
    """

    __slots__ = ("_holder",)

    def __init__(self, holder: dict[str, Any]) -> None:
        # The holder is filled by the App's startup hook. A dict rather than a built node because
        # ``create_local_app`` is synchronous and building the world is not, and because the
        # executor factory (created before startup) must read the same world at run time.
        self._holder = holder

    async def __call__(self, scope: AsgiScope, receive: AsgiReceive, send: AsgiSend) -> None:
        # INVARIANT: the `NodeMountRoute` is the ONE place that decides "is this a mount". It
        # passes only `http` scopes on a path the built node serves, and its path set is empty
        # until startup has built a node — so a node always exists by the time this runs.
        node_asgi = self._holder["asgi"]
        raw_headers = Headers(scope=scope)
        try:
            bound = request_scope_from_headers(raw_headers)
        except AnswerSeedError as exc:
            # A declared sitting must not silently run without its seed (OME-1038). The node tier
            # maps this to 400 before dispatch; local mode calls the same producer itself, so it
            # owns the same mapping rather than letting a malformed seed escape as a 500.
            await send_url4_error(send, 400, "malformed_source", str(exc))
            return
        cleaned = forwarded_headers(
            (
                (name.decode("latin-1"), value.decode("latin-1"))
                for name, value in scope.get("headers") or ()
            ),
            verified_identity=bound.identity_headers,
        )
        child_scope = {
            **scope,
            "headers": [
                (name.encode("latin-1"), value.encode("latin-1")) for name, value in cleaned
            ],
        }
        # FX-64: the trace is bound in `trace_scope`, its ONE carrier, exactly as the node tier
        # binds it — the connector reads nothing trace-shaped off the request scope.
        with request_scope(bound), run_trace_scope(trace_from_headers(raw_headers)):
            await node_asgi(child_scope, receive, send)


def _install_local_node(
    app: FastAPI,
    *,
    holder: dict[str, Any],
    run_env: Mapping[str, str],
    benchmarks: BenchmarkRegistry,
) -> None:
    """Install the shared node's route LAST and register its build/teardown hooks (prd/03 C8).

    Extracted from :func:`create_local_app` so the composition root stays a readable sequence of
    wiring steps; the mount, the world build and the ordered teardown belong together.

    # INVARIANT: the shutdown hook is registered HERE, so the caller must call this AFTER the
    # runner's and the gate's own shutdown hooks. That ordering is the correctness property: the
    # world is the io the runs were using, so it is closed once they have drained and released
    # their gate permits.

    # WHY no node-tier aigateway overrides and no url4 admission/timeout wrapper. Local is a
    # DEVELOPMENT shape (C8), and ONE node serves both the sync mount and the in-process runs.
    # The run path is the regression oracle, so the shared node keeps the DECLARED aigateway
    # config (its timeout and ``allow_outbound``) rather than the deployed tier's 30 s/28 s ladder
    # and forced-off outbound layer — those are properties of a stateless public tier, not of a
    # loopback dev process that also evaluates arbitrary expressions.
    """
    node_mount = _LocalNodeMount(holder)
    app.state.node_mount = node_mount
    # WHY a provider over `holder`: the path set exists only once startup has built the world.
    install_node_route(
        app,
        NodeMountRoute(
            node_mount, paths=lambda: holder.get("paths", frozenset()), name=_NODE_MOUNT_NAME
        ),
    )

    async def _build_shared_node() -> None:
        """Compose the ONE world both surfaces use, guarded against the App's real route table."""
        world, aclose = await compose_serving_world(
            env=run_env,
            # F4/D3: run the collision guard against the routes the mount actually joins, so a
            # declared mount shadowed by an engine literal fails startup instead of vanishing.
            engine_routes=engine_route_paths(app),
            benchmarks=benchmarks,
        )
        holder["io"] = world
        holder["aclose"] = aclose
        asgi = getattr(world, "asgi", None)
        holder["asgi"] = asgi() if callable(asgi) else None
        # No node means no mounts and no eval path: every path is then the engine's.
        holder["paths"] = (
            node_mount_paths(world) | {node_eval_path(world)}
            if holder["asgi"] is not None
            else frozenset()
        )
        app.state.node_world = world

    async def _close_shared_node() -> None:
        aclose = holder.get("aclose")
        if aclose is not None:
            await aclose()

    app.router.on_startup.append(_build_shared_node)
    app.router.on_shutdown.append(_close_shared_node)


def create_local_app(
    settings: Settings | None = None,
    *,
    env: Mapping[str, str] | None = None,
    benchmarks: BenchmarkRegistry | None = None,
) -> FastAPI:
    """Build the local-mode App: in-process runner, in-memory stream, real everything else.

    `env` is the ambient environment each run's executor is built from (the deploy-time half a
    Job would receive via `envFrom`); it defaults to the process environment and is a parameter
    so tests need not mutate `os.environ`.
    """
    settings, activity_level = _local_activity_configuration(settings, env)
    _warn_if_insecure(settings)
    _configure_engine_logging()

    # ONE object, handed to both sides — it is an `EventStream`, so it satisfies the App's
    # `EventConsumer` and the runner's `EventPublisher` at once. That shared instance IS the bus.
    stream = InMemoryEventStream(max_frames_per_topic=settings.local_stream_max_frames)

    # WHY the import is function-local: it is THE line that crosses the layering boundary, and
    # keeping it here means the crossing happens when a local App is actually built rather than on
    # any import of this module. What it defers is the RUN mode — `runner.main`, `runner.executor`
    # and the observation plugins. It does NOT defer `world.connector` or httpx: the module-level
    # `world.serving` import (the shared node) already loads both, and `url4/__init__` loads the
    # engine itself via any `url4.streaming` import (see the SCOPE NOTE in `check_layering.py`).
    from screamingface_engine.observation_plugins import observation_factories
    from screamingface_engine.runner.main import build_executor

    run_env = dict(_with_runner_config(env if env is not None else os.environ))
    run_env[job_env.ACTIVITY_LEVEL] = activity_level
    observers = observation_factories(run_env)
    if benchmarks is None:
        benchmarks = _local_benchmarks(run_env)
    # INVARIANT: the local default is substituted ONCE, here, before anything reads the address —
    # so discovery and connections resolve the same gateway by construction rather than by two
    # call sites agreeing. This substitution used to sit BELOW the catalog and feed only
    # `build_connections`, which left `/v1/models` answering 503 "not configured" on the one
    # deployment shape whose address is known in advance, while `/v1/connections` on that very
    # address answered 200 (OME-795).
    settings = _with_local_gateway(settings)
    # Catalog before the runner (OME-880): the runner takes the admitted-model overlay so a
    # dynamically admitted model is routable by the very next local run.
    catalog = build_executable_catalog_service(settings, run_env)
    # FEATURE (OME-908): ONE gate, shared by every local run — the composition point that
    # makes local fair-share dynamic where a deployed Job gets a static budget instead.
    # Built beside the runner (its runs' executors bind into it through `build_executor`'s
    # `io_gate`) and closed AFTER the runner on shutdown, so cancelled runs release their
    # permits into a gate that still accepts the releases.
    io_gate = FairShareGate(settings.local_io_capacity)
    # FEATURE (unit 3, C8): ONE world serves both the mounted node's ASGI surface and every
    # in-process run. The world is built in the App's startup hook (building is async; this
    # function is not) and parked here, so the executor factory below can read it at run time.
    # Empty until startup completes; a run scheduled without the App's lifespan falls back to the
    # per-run world builder.
    holder: dict[str, Any] = {}
    job_runner = InProcessJobRunner(
        stream,
        partial(
            build_executor,
            benchmarks=benchmarks,
            io_gate=io_gate,
            observers=observers,
            # Read AT RUN TIME so the shared node exists by the time a run is scheduled.
            io_provider=lambda: holder.get("io"),
        ),
        base_env=run_env,
        max_concurrent_runs=settings.local_max_concurrent_runs,
        max_history=settings.local_max_run_history,
        extra_models=None if catalog is None else (lambda: catalog.admitted_model_ids),
    )
    # INVARIANT: local mode keeps the caller-managed rows that back its BYOK controls; the
    # read-only availability listing is the deployed (Hosted) Engine policy and must not replace
    # this mutable state (D15).
    connections = build_connections(settings, mutable=True)
    app = create_app(
        settings,
        stream=stream,
        job_runner=job_runner,
        catalog=catalog,
        model_parameters=catalog.model_parameter_source if catalog is not None else None,
        connections=connections,
        benchmarks=benchmarks,
    )
    register_fair_share_metrics(app.state.metrics, lambda: io_gate)
    # On app.state for operators and tests: the one gate every local run shares. Read-only
    # by convention — nothing outside `runner.fair_share` mutates it.
    app.state.fair_share_gate = io_gate
    app.router.on_shutdown.append(job_runner.aclose)
    # WHY after `job_runner.aclose`: shutdown cancels every in-flight run first, and each
    # cancelled fetch releases its permit in a `finally` — closing the gate before those
    # releases land would drop them on a dead object instead of the books.
    app.router.on_shutdown.append(io_gate.aclose)
    # FEATURE (unit 3, prd/03 §2.3 / C8): the local node route, installed after ALL routes and
    # after the runner/gate shutdown hooks whose ordering it depends on. `install_node_route`
    # asserts the route order rather than trusting it; there is NO forwarder and NO NetworkPolicy
    # here — this is the development shape of the sync surface, never a deployment option.
    _install_local_node(app, holder=holder, run_env=run_env, benchmarks=benchmarks)
    for adapter in (catalog, connections):
        if adapter is not None:
            app.router.on_shutdown.append(adapter.aclose)
    return app


__all__ = ["LOCAL_HOST", "create_local_app"]
