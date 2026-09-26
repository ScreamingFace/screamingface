"""The FastAPI composition root for the screamingface-engine App.

Builds the App instance: wires the REST, model discovery, WS, and ops routers, installs
auth/problem handlers and the metrics middleware, and assembles the injectable adapters that
tests substitute for the production ones built here from `Settings`.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
from pathlib import Path
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, FastAPI, Request
from fastapi.staticfiles import StaticFiles

from screamingface_engine import job_env
from screamingface_engine.adapters.factory import build_job_runner
from screamingface_engine.artifacts import (
    ArtifactReader,
    ArtifactStore,
    S3ArtifactStore,
)
from screamingface_engine.artifacts.wiring import s3_config_from_values
from screamingface_engine.auth import Clock, install_problem_handlers
from screamingface_engine.benchmarks import EMPTY_BENCHMARKS, BenchmarkRegistry
from screamingface_engine.benchmarks.builtins import BUILTIN_BENCHMARKS
from screamingface_engine.catalog import build_executable_catalog_service
from screamingface_engine.catalog.cache import CatalogService
from screamingface_engine.catalog.port import ModelParameterSource
from screamingface_engine.config import INSECURE_DEFAULT_JWT_SECRET, Settings

if TYPE_CHECKING:  # the adapter is imported lazily at runtime; only the annotation needs the name
    from screamingface_engine.adapters.jetstream import JetStreamConsumer

from screamingface_engine.connections import build_connections
from screamingface_engine.connections.port import Connections
from screamingface_engine.metrics import (
    MetricsMiddleware,
    build_metrics,
    register_catalog_metrics,
    register_events_metrics,
    register_max_deliveries_metrics,
    register_queue_metrics,
    register_reaper_metrics,
    register_sync_metrics,
)
from screamingface_engine.ops import router as ops_router
from screamingface_engine.reaper import RunReaper
from screamingface_engine.rest import (
    SubscriberGate,
    artifact_router,
    benchmark_router,
    catalog_router,
    connection_router,
)
from screamingface_engine.rest import router as rest_router
from screamingface_engine.rest.mounts import install_mounts
from screamingface_engine.schemas import customize_openapi
from screamingface_engine.world.serving import derive_mount_table, engine_route_paths
from screamingface_engine.ws import ConnectionRegistry
from screamingface_engine.ws import router as ws_router
from url4.streaming.interfaces import EventConsumer, JobRunner

router = APIRouter()

_DIAGRAMS_DIR = Path(__file__).parent / "assets" / "diagrams"

# Mounted in this order by `create_app`. A tuple rather than seven calls: the wiring is data, and
# every new surface (benchmarks, connections, …) would otherwise grow the builder itself.
_ROUTERS = (
    router,
    rest_router,
    artifact_router,
    benchmark_router,
    catalog_router,
    connection_router,
    ws_router,
    ops_router,
)


@router.get("/healthz", include_in_schema=False)
def healthz(request: Request) -> dict[str, str]:
    # FEATURE (unit 3, erd.md §2): when the sync forwarder is wired, report the digest of the
    # config its mount set came from, so a rolling deploy where the App and the node tier briefly
    # read different worlds is visible (R11). An App with no sync surface keeps the exact
    # `{"status": "ok"}` contract it had before.
    digest = getattr(request.app.state, "config_digest", None)
    if digest:
        return {"status": "ok", "config_digest": digest}
    return {"status": "ok"}


def create_app(
    settings: Settings | None = None,
    *,
    stream: EventConsumer | None = None,
    job_runner: JobRunner | None = None,
    clock: Clock | None = None,
    interest: SubscriberGate | None = None,
    catalog: CatalogService | None = None,
    model_parameters: ModelParameterSource | None = None,
    connections: Connections | None = None,
    benchmarks: BenchmarkRegistry = EMPTY_BENCHMARKS,
) -> FastAPI:
    """Build the App instance.

    All keyword-only params are DI seams: production wiring supplies real adapters via
    `create_app_from_env`, tests inject fakes/mocks directly.
    """
    settings = settings or Settings()
    app = FastAPI(title="screamingface-engine", version="0.1.0", docs_url=None, redoc_url=None)
    app.state.settings = settings
    app.state.stream = stream
    app.state.job_runner = job_runner
    app.state.catalog = catalog
    app.state.model_parameters = model_parameters
    app.state.connections = connections
    app.state.benchmarks = benchmarks
    app.state.metrics = build_metrics()
    # FEATURE: deliver large results in full (OME-892) — the serve side of the spill store.
    # FEATURE: and survive a multi-pod deployment, where that store cannot be a local disk
    # (OME-929).
    app.state.artifact_store = _build_artifact_reader(settings)
    # WHY startup + periodic: fetching never deletes (OME-892 review — content addressing means
    # one object backs many tickets, and a Range request must leave the rest fetchable), so TTL
    # is the ONLY cleanup and every redeemed parcel also waits for it. The boot sweep clears the
    # backlog immediately; the periodic task covers a hosted App that stays up for weeks
    # between redeploys — startup-only would let parcels pool until the next
    # restart (owner decision on OME-892).
    #
    # AIDEV-NOTE: with `artifact_store=s3` the sweeper is a no-op by design — expiry is the
    # bucket's lifecycle rule. See `artifacts.s3.S3ArtifactStore.sweep`.
    _install_artifact_sweeper(app, app.state.artifact_store, settings)
    # WHY: pass a getter, not `catalog` directly — the collector re-reads app.state.catalog on
    # every /metrics scrape rather than capturing the value built here.
    register_catalog_metrics(app.state.metrics, lambda: app.state.catalog)
    _register_runner_metrics(app)
    # FEATURE: the shared events stream's own signals — store use and publish conflicts
    # (uniform executor, PRD 01 §4 Observability). A stream that can refresh its own usage
    # (the JetStream adapter; not the in-memory local one) also gets a periodic poller.
    _install_events_store_monitor(app, stream)
    app.add_middleware(MetricsMiddleware)
    app.state.registry = ConnectionRegistry()
    register_sync_metrics(app.state.metrics, lambda: app.state.registry)
    app.state.interest = interest if interest is not None else app.state.registry
    # FEATURE: tie a run's lifetime to its audience (OME-890).
    _install_orphan_reaper(app, app.state.registry, job_runner, settings)
    # FEATURE: a run the queue gave up on must end in a named failure, not silence
    # (OME-1090).
    _install_max_deliveries_advisor(app, settings)
    if clock is not None:
        app.state.clock = clock
    _install_surfaces(app)
    return app


def _install_surfaces(app: FastAPI) -> None:
    """Register every engine HTTP surface; `install_forwarder` appends the node route after them."""
    install_problem_handlers(app)
    for api_router in _ROUTERS:
        app.include_router(api_router)
    app.mount("/diagrams", StaticFiles(directory=_DIAGRAMS_DIR), name="diagrams")
    customize_openapi(app)


def _register_runner_metrics(app: FastAPI) -> None:
    """The queue's own signals (depth, oldest-unclaimed age) and the max-deliveries advisories
    (OME-1092). Registered unconditionally via getters, like the reaper's: a stream-only App
    exposes no queue series rather than a stale zero, and /metrics never depends on wiring
    order."""
    register_queue_metrics(app.state.metrics, lambda: app.state.job_runner)
    register_max_deliveries_metrics(app.state.metrics, lambda: app.state.max_deliveries_advisor)
    # WHY the publisher getter reaches through `job_runner.publisher` rather than a field of
    # its own: the queue runner is the one thing on `app.state` that already holds the
    # `JetStreamPublisher` the App's own writers (the queued-cancel tombstone) use — the same
    # publisher `publish_conflicts` counts against (writer="app"). `getattr` twice over (the
    # runner may be None, or not a `QueueJobRunner`) so a stream-only or `runner="none"` App
    # renders the series absent rather than raising.
    register_events_metrics(
        app.state.metrics,
        lambda: app.state.stream,
        lambda: getattr(app.state.job_runner, "publisher", None),
    )


# RFC 7518 §3.2: an HMAC key must be at least as long as the hash output — 32 bytes for SHA-256.
# PyJWT warns below this; here it is refused, because the token is the whole authorization model.
_logger = logging.getLogger(__name__)


def _build_artifact_reader(settings: Settings) -> ArtifactReader:
    """The serve side of the spill store, and a refusal for the combination that loses results.

    FEATURE: over-cap results survive the Runner Job on a multi-pod deployment (OME-929).

    INVARIANT: `runner="k8s"` with filesystem storage is refused. A Runner Job pod and this App
    pod do not share a disk, so the Runner writes into an `emptyDir` that dies with the Job and
    every over-cap redemption 404s — after the run has been paid for in full. That pairing was
    the DEFAULT before OME-929, reachable by configuring nothing, and nothing in the setup said
    so. It fails at boot now.

    INVARIANT (FX-38): a node tier (`node_base_url`) with filesystem storage is refused too: the
    node pod spills an over-cap sync result to ITS disk and redirects the caller here — a 404.

    AIDEV-NOTE: if a shared RWX volume is ever mounted into both pods, THIS is the check to
    relax — deliberately, and with the mount as evidence. Do not relax it to quiet a startup
    error; that restores the bug.
    """
    if settings.artifact_store == "s3":
        return S3ArtifactStore(
            s3_config_from_values(
                {
                    job_env.ARTIFACT_S3_ENDPOINT_URL: settings.artifact_s3_endpoint_url,
                    job_env.ARTIFACT_S3_BUCKET: settings.artifact_s3_bucket,
                    job_env.ARTIFACT_S3_REGION: settings.artifact_s3_region,
                    job_env.ARTIFACT_S3_ACCESS_KEY: settings.artifact_s3_access_key,
                    job_env.ARTIFACT_S3_SECRET_KEY: settings.artifact_s3_secret_key,
                }
            )
        )
    if settings.node_base_url:
        raise ValueError(
            "a node tier is configured (node_base_url), and the node pod's disk is not this "
            "App's (OME-929): a spilled sync result redirected here would 404. Set "
            f"{job_env.ARTIFACT_STORE}=s3 and the {job_env.ARTIFACT_S3_BUCKET} settings."
        )
    if settings.runner == "queue":
        # WHY: `queue` (OME-1090) runs each run in a worker pod — either way the run executes in
        # a different pod than this App, whose disk is destroyed with it, so results spilled
        # to a local directory can never be served back.
        raise ValueError(
            f"runner='{settings.runner}' runs each run in its own pod, whose disk is "
            f"destroyed with it, so results spilled to a local directory can never be "
            f"served back. Set {job_env.ARTIFACT_STORE}=s3 and the "
            f"{job_env.ARTIFACT_S3_BUCKET} settings, or use runner='none' for a "
            f"single-process deployment."
        )
    return ArtifactStore(Path(settings.artifacts_dir))


def _install_artifact_sweeper(app: FastAPI, store: ArtifactReader, settings: Settings) -> None:
    """Wire the artifact TTL sweep: once at startup, then every sweep interval for life.

    FEATURE: deliver large results in full (OME-892). The loop is an asyncio task on the
    App's own event loop — cancelled at shutdown so no task outlives the App. The sweep
    itself runs in a worker thread (`asyncio.to_thread`): it is directory I/O, and the
    event loop that pumps every WebSocket must never block on a disk scan.
    """

    async def _sweep_once() -> None:
        await asyncio.to_thread(store.sweep, ttl_seconds=settings.artifact_ttl_s)

    async def _sweep_forever() -> None:
        while True:
            await asyncio.sleep(settings.artifact_sweep_interval_s)
            # INVARIANT: one failed sweep must not kill the sweeper — an unhandled
            # exception here would end the task silently and disk cleanup would stop
            # until the next redeploy, exactly the leak the periodic sweep exists to
            # prevent. Log and keep the cadence.
            try:
                await _sweep_once()
            except Exception:
                _logger.exception("artifact sweep failed; retrying next interval")

    async def _start() -> None:
        await _sweep_once()
        app.state.artifact_sweep_task = asyncio.get_running_loop().create_task(_sweep_forever())

    async def _stop() -> None:
        task = getattr(app.state, "artifact_sweep_task", None)
        if task is not None:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

    app.router.on_startup.append(_start)
    app.router.on_shutdown.append(_stop)


def _install_orphan_reaper(
    app: FastAPI,
    registry: ConnectionRegistry,
    job_runner: JobRunner | None,
    settings: Settings,
) -> None:
    """Wire the orphan-run reaper: arm on audience-empty, sweep on a cadence, stop on expiry.

    FEATURE: tie a run's lifetime to its audience (OME-890). Modelled on
    `_install_artifact_sweeper` above — the policy object owns no task, the loop is an asyncio
    task on the App's own event loop, and shutdown cancels it so nothing outlives the App. No
    sweep at startup, unlike that one: nothing can be armed before a WebSocket has attached and
    then left, so a boot sweep would have nothing to look at.

    INVARIANT: the reaper is handed `registry` — the REAL one — and never `app.state.interest`.
    The gate seam answers "no subscriber" for every topic under `DenyAllGate`, which as a reap
    input would stop every run in this process one grace window after boot. Same call as
    `rest/routes.py::_deps` taking `registry` over `interest` for session state.
    """
    app.state.reaper = None
    app.state.reaper_task = None
    # WHY registered unconditionally, and via a getter: the collector reads whatever
    # `app.state.reaper` holds at scrape time, so a stream-only App exposes no reaper series
    # rather than a stale zero, and `/metrics` never depends on wiring order.
    register_reaper_metrics(app.state.metrics, lambda: app.state.reaper)
    if job_runner is None or settings.orphan_grace_s <= 0:
        # WHY the early return: a stream-only App has nothing to stop, and an operator may turn
        # the reaper off with `URL4_CLOUD_ORPHAN_GRACE_S=0`. Either way, no task is created — the
        # many tests that inject no runner must not grow a background task.
        return
    reaper = RunReaper(job_runner, registry, grace_s=settings.orphan_grace_s)
    app.state.reaper = reaper
    registry.listen(reaper)

    async def _sweep_forever() -> None:
        while True:
            await asyncio.sleep(reaper.tick_s)
            # INVARIANT: one failed sweep must not kill the reaper. An unhandled exception here
            # would end the task silently and every later orphan would run to the 16h ceiling
            # with no signal at all — worse than the bug this fixes, because it would LOOK fixed.
            # Log and keep the cadence. `CancelledError` is a BaseException and still propagates,
            # so shutdown is unaffected.
            try:
                await reaper.sweep()
            except Exception:
                _logger.exception("orphan sweep failed; retrying next interval")

    async def _start() -> None:
        app.state.reaper_task = asyncio.get_running_loop().create_task(_sweep_forever())
        # AIDEV-NOTE: the single-replica assumption is LOGGED, not merely noted in the chart. The
        # audience count lives in this process's memory, so a second replica would answer "nobody
        # is listening" for runs another replica is streaming and stop healthy runs. Multi-replica
        # needs a shared SubscriberGate (NATS consumer interest) first.
        _logger.info(
            "orphan reaper armed grace_s=%.0f tick_s=%.0f (assumes a single replica)",
            settings.orphan_grace_s,
            reaper.tick_s,
        )

    async def _stop() -> None:
        task = app.state.reaper_task
        if task is not None:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

    app.router.on_startup.append(_start)
    app.router.on_shutdown.append(_stop)


def _install_max_deliveries_advisor(app: FastAPI, settings: Settings) -> None:
    """Wire the max-deliveries advisory subscriber: a background task that publishes a
    named terminal failure for each run the queue gave up on (OME-1090).

    Modelled on `_install_orphan_reaper`: the advisor owns no task, the loop is an asyncio
    task on the App's own event loop, and shutdown cancels it and closes the advisor's
    connections so nothing outlives the App. Only the queue backend has a queue to give up
    on, so a stream-only App installs nothing.
    """
    app.state.max_deliveries_advisor = None
    app.state.max_deliveries_task = None
    if settings.runner != "queue":
        return
    from screamingface_engine.adapters.max_deliveries import MaxDeliveriesAdvisor

    advisor = MaxDeliveriesAdvisor(settings.nats_url, run_queue_stream=settings.run_queue_stream)
    app.state.max_deliveries_advisor = advisor

    async def _start() -> None:
        app.state.max_deliveries_task = asyncio.get_running_loop().create_task(advisor.run())

    async def _stop() -> None:
        task = app.state.max_deliveries_task
        if task is not None:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
        await advisor.aclose()

    app.router.on_startup.append(_start)
    app.router.on_shutdown.append(_stop)


_EVENTS_STORE_POLL_S = 15.0
"""How often the App re-reads the shared events stream's own usage (PRD 01 §4 Observability)."""


class _EventsStoreMonitor:
    """One tick of the events-store usage poll: refresh the gauge, and log a failed refresh.

    Split from `_install_events_store_monitor`'s task wiring so a test can call `tick()`
    directly, with no sleep involved — the `failing` state that makes "log once per failure
    streak, not every failed tick" true lives here.

    WHY no utilization-threshold logging here: the chart's own alert rule
    (`screamingface_engine_events_store_utilization_ratio >= 0.8` for 5m, deploy/helm/README.md)
    is the single owner of that threshold. Logging a second copy of it here duplicated the
    alert's own logic in a second place that could drift from it (a changed alert rule left
    this log's threshold stale); the gauge this tick refreshes is all the alert needs.
    """

    def __init__(self, stream: Any) -> None:
        self._stream = stream
        self._failing = False

    async def tick(self) -> None:
        try:
            await self._stream.refresh_store_usage()
        except Exception:
            # WHY once per streak, not once per tick: a broker outage lasting several
            # intervals must not fill the App's log with the same warning every
            # `_EVENTS_STORE_POLL_S` — and a failed read leaves `store_snapshot` at its
            # last value, so the gauge keeps reporting the last known reading.
            if not self._failing:
                _logger.warning(
                    "events store usage refresh failed; keeping the last reading", exc_info=True
                )
                self._failing = True
            return
        self._failing = False


def _install_events_store_monitor(
    app: FastAPI, stream: EventConsumer | None, *, interval_s: float = _EVENTS_STORE_POLL_S
) -> None:
    """Poll the shared events stream's own usage on a cadence, for `_EventsStoreCollector` to
    read at scrape time.

    Modelled on `_install_artifact_sweeper`: an asyncio task on the App's own event loop,
    cancelled at shutdown so nothing outlives the App. Installed ONLY when `stream` can refresh
    its own usage (`refresh_store_usage`) — the in-memory local stream has no store to read, and
    a stream-only or `runner='none'` App may be given no stream at all.

    WHY the first tick waits one interval rather than firing immediately (unlike
    `_install_artifact_sweeper`, which sweeps once at startup): this task is started from an
    `on_startup` handler registered BEFORE `create_app_from_env` appends
    `stream.declare_events_stream`, and `on_startup` handlers run in registration order but this
    one only SCHEDULES a task rather than awaiting it — so an immediate first tick can run
    during a later handler's own await and read a stream that has not been declared yet, logging
    a spurious cold-start warning. Sleeping first gives `declare_events_stream` the whole
    interval to finish before the first read.
    """
    if not hasattr(stream, "refresh_store_usage"):
        return
    monitor = _EventsStoreMonitor(stream)

    async def _poll_forever() -> None:
        while True:
            await asyncio.sleep(interval_s)
            await monitor.tick()

    async def _start() -> None:
        app.state.events_store_monitor_task = asyncio.get_running_loop().create_task(
            _poll_forever()
        )

    async def _stop() -> None:
        task = getattr(app.state, "events_store_monitor_task", None)
        if task is not None:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

    app.router.on_startup.append(_start)
    app.router.on_shutdown.append(_stop)


_MIN_JWT_SECRET_BYTES = 32


def _require_prod_secret(settings: Settings) -> None:
    """Raise RuntimeError if `settings.jwt_secret` is unset or too weak to sign a capability.

    Sentinel equality alone was not enough: it rejected the shipped dev default but accepted any
    other string, so a 4-character production secret passed. The capability token IS the topic
    authorization, so a brute-forceable signing key is a full authorization bypass — refused at
    boot rather than at the first forged token.
    """
    if settings.jwt_secret == INSECURE_DEFAULT_JWT_SECRET:
        raise RuntimeError("URL4_CLOUD_JWT_SECRET must be set in production")
    if len(settings.jwt_secret.encode("utf-8")) < _MIN_JWT_SECRET_BYTES:
        raise RuntimeError(
            f"URL4_CLOUD_JWT_SECRET must be at least {_MIN_JWT_SECRET_BYTES} bytes "
            f"(RFC 7518 §3.2 for HS256); it signs the topic-capability token"
        )


def build_stream_consumer(settings: Settings) -> JetStreamConsumer:
    """The App's event-stream consumer, carrying the CONFIGURED events stream limits.

    Extracted from `create_app_from_env` so the stream-wiring test can hold this root to
    the same Settings as the worker's and the App's runner.
    """
    from screamingface_engine.adapters.factory import events_stream_config
    from screamingface_engine.adapters.jetstream import JetStreamConsumer

    return JetStreamConsumer(settings.nats_url, events=events_stream_config(settings))


def create_app_from_env() -> FastAPI:  # pragma: no cover - env/NATS wiring (INFRA rule, spec §11)
    """Production entrypoint (used by `cli.py` via uvicorn's factory mode).

    Builds real adapters from `Settings` — a JetStream event consumer, the configured job-runner
    backend, and the catalog service — then wires them into `create_app` and registers their
    shutdown hooks on the App's router.
    """
    settings = Settings()
    _require_prod_secret(settings)
    stream = build_stream_consumer(settings)
    # Catalog first (OME-880): the job runner needs the admitted-model overlay so a
    # dynamically admitted model is routable by the very next scheduled run.
    catalog = build_executable_catalog_service(settings, os.environ)
    job_runner = build_job_runner(
        settings,
        extra_models=None if catalog is None else (lambda: catalog.admitted_model_ids),
    )
    if job_runner is None:
        logging.warning(
            "URL4_CLOUD_RUNNER is 'none' — this App bridges NATS but cannot schedule runs"
        )
    # INVARIANT: deployed availability comes from the signed-in caller's provider access as the
    # gateway publishes it (`GET /v1/provider-access`); this Engine owns none of it and refuses
    # every mutation (D15). The provider catalogue describes capability, not what this caller holds.
    connections = build_connections(settings, mutable=False)
    app = create_app(
        settings,
        stream=stream,
        job_runner=job_runner,
        catalog=catalog,
        model_parameters=catalog.model_parameter_source if catalog is not None else None,
        connections=connections,
        benchmarks=BUILTIN_BENCHMARKS,
    )
    # The App owns the configured limits: declare the shared events stream (and apply a
    # changed limit) before the first request, and fail startup on a config it cannot apply.
    app.router.on_startup.append(stream.declare_events_stream)
    app.router.on_shutdown.append(stream.close)
    if job_runner is not None:
        # The queue runner owns a control connection of its own (OME-1090). `getattr` rather
        # than an isinstance: the factory returns the port, and the app must not import a
        # concrete adapter.
        aclose = getattr(job_runner, "aclose", None)
        if aclose is not None:
            app.router.on_shutdown.append(aclose)
    if catalog is not None:
        app.router.on_shutdown.append(catalog.aclose)
    if connections is not None:
        app.router.on_shutdown.append(connections.aclose)
    # FEATURE (uniform executor PRD 04): every declared mount is a route of its own, projected
    # into /openapi.json, and every call runs as a DIRECT run on the worker pool — the node-tier
    # forwarder is no longer installed (PRD 05 removes it).
    install_mounts(
        app,
        lambda: derive_mount_table(env=os.environ, engine_routes=engine_route_paths(app)),
    )
    return app
