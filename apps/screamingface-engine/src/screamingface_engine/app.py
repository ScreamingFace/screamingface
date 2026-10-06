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
from collections.abc import Awaitable, Callable
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
from screamingface_engine.auth import Clock, default_clock, install_problem_handlers
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
from screamingface_engine.cors import install_cors
from screamingface_engine.logs import configure as configure_logging
from screamingface_engine.metrics import (
    MetricsMiddleware,
    build_metrics,
    register_active_runs_metrics,
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
from screamingface_engine.tracing.loader import load_span_sink
from screamingface_engine.tracing.relay import SpanSink
from screamingface_engine.unclaimed import QueuedRuns, UnclaimedRunWarner
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
    # FEATURE (uniform executor PRD 04): when mounts are registered, report the digest of the
    # config the mount table came from (the App's own view only — the runner pool reports no
    # digest, so compare App pods with each other). An App with no mounts keeps the exact
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
    span_sink: SpanSink | None = None,
) -> FastAPI:
    """Build the App instance.

    All keyword-only params are DI seams: production wiring supplies real adapters via
    `create_app_from_env`, tests inject fakes/mocks directly.
    """
    # FEATURE (OME-942): every ASGI entry keeps app logging, not just `cli.main`.
    #
    # WHY here and not only in the CLI: `uvicorn.run()` installs handlers for the `uvicorn*`
    # loggers ONLY, so a `screamingface_engine` record falls through to `logging.lastResort`
    # and is discarded below WARNING — the regression `logs.py`'s docstring documents. Any
    # other ASGI host (`uvicorn screamingface_engine.app:create_app_from_env`, an embedding
    # process, a test harness) reproduced it in full. `create_app` is the one door they all go
    # through.
    #
    # INVARIANT: `configure` is idempotent about ITS OWN handler, so the CLI's call followed by
    # this one installs exactly one, and a process that builds two Apps does not double every
    # line. FIRST statement in the builder, because a failure while building `Settings` below
    # is precisely the failure whose log line the operator needs.
    configure_logging()
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
    _register_metrics(app)
    # FEATURE: the shared events stream's own signals — store use and publish conflicts
    # (uniform executor, PRD 01 §4 Observability). A stream that can refresh its own usage
    # (the JetStream adapter; not the in-memory local one) also gets a periodic poller.
    _install_events_store_monitor(app, stream)
    _install_middleware(app, settings)
    app.state.registry = ConnectionRegistry()
    register_sync_metrics(app.state.metrics, lambda: app.state.registry)
    app.state.interest = interest if interest is not None else app.state.registry
    # FEATURE: tie a run's lifetime to its audience (OME-890).
    _install_orphan_reaper(app, app.state.registry, job_runner, settings)
    # FEATURE: warn the client about an unclaimed queued run (under OME-1086).
    _install_unclaimed_run_warner(
        app,
        app.state.registry,
        job_runner,
        settings,
        clock if clock is not None else default_clock,
    )
    # FEATURE: a run the queue gave up on must end in a named failure, not silence
    # (OME-1090).
    _install_max_deliveries_advisor(app, settings)
    if clock is not None:
        app.state.clock = clock
    _install_surfaces(app, span_sink)
    return app


control_plane_span_sink = load_span_sink
"""The App's span sink (OME-1218): the `tracing` leaf's loader — the same one the run uses
(OME-1462). Lazy OTel import, never raises; see `tracing.loader`."""


def _install_span_sink(app: FastAPI, sink: SpanSink | None) -> None:
    """Publish the sink to the routes and flush it at shutdown.

    WHY `to_thread`: `OtlpSpanSink.close` blocks for up to its flush bound, and the event loop
    is still serving other shutdown hooks.
    """
    app.state.span_sink = sink
    if sink is None:
        return

    async def _close() -> None:
        try:
            await asyncio.to_thread(sink.close)
        except Exception:
            _logger.warning("the span sink did not shut down cleanly", exc_info=True)

    app.router.on_shutdown.append(_close)


def _install_middleware(app: FastAPI, settings: Settings) -> None:
    """Add the App's ASGI middleware; the last one added is the outermost."""
    app.add_middleware(MetricsMiddleware)
    # WHY CORS last (outermost): a preflight is answered before routing, and a handled error
    # (the problem+json 4xx/5xx) carries the grant too, so the browser can read its body.
    install_cors(app, settings.cors_allowed_origins)


def _install_surfaces(app: FastAPI, span_sink: SpanSink | None = None) -> None:
    """Register every engine HTTP surface; declared mounts are registered separately, by
    `install_mounts` at startup."""
    # FEATURE (OME-1218): the run-submission route's accept span. `None` (the default) keeps
    # the route exactly as it was: no span, the inbound traceparent forwarded verbatim.
    _install_span_sink(app, span_sink)
    install_problem_handlers(app)
    for api_router in _ROUTERS:
        app.include_router(api_router)
    app.mount("/diagrams", StaticFiles(directory=_DIAGRAMS_DIR), name="diagrams")
    customize_openapi(app)


def _register_metrics(app: FastAPI) -> None:
    """Every custom collector this App exposes, in one place.

    WHY getters throughout, never the built value: each collector re-reads `app.state` at
    SCRAPE time, so a series reflects the App as it is rather than as it was at boot, and
    /metrics never depends on wiring order.
    """
    register_catalog_metrics(app.state.metrics, lambda: app.state.catalog)
    _register_runner_metrics(app)


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
    # FEATURE (OME-942): runs in flight in THIS process — the admission gate's own input, and
    # until now a number only the code enforcing it could see. Through a getter like the rest,
    # so it is read at SCRAPE time rather than captured at boot.
    register_active_runs_metrics(app.state.metrics, lambda: app.state.job_runner)


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

    def _armed() -> None:
        # AIDEV-NOTE: the single-replica assumption is LOGGED, not merely noted in the chart. The
        # audience count lives in this process's memory, so a second replica would answer "nobody
        # is listening" for runs another replica is streaming and stop healthy runs. Multi-replica
        # needs a shared SubscriberGate (NATS consumer interest) first.
        _logger.info(
            "orphan reaper armed grace_s=%.0f tick_s=%.0f (assumes a single replica)",
            settings.orphan_grace_s,
            reaper.tick_s,
        )

    # INVARIANT: one failed sweep must not kill the reaper. An unhandled exception would end the
    # task silently and every later orphan would run to the 16h ceiling with no signal at all —
    # worse than the bug this fixes, because it would LOOK fixed.
    _install_periodic(
        app,
        task_attr="reaper_task",
        tick_s=reaper.tick_s,
        sweep=reaper.sweep,
        failure_message="orphan sweep failed; retrying next interval",
        on_start=_armed,
    )


def _install_periodic(
    app: FastAPI,
    *,
    task_attr: str,
    tick_s: float,
    sweep: Callable[[], Awaitable[object]],
    failure_message: str,
    on_start: Callable[[], None],
) -> None:
    """Run ``sweep`` every ``tick_s`` seconds as ONE asyncio task on the App's own event loop,
    stored on ``app.state.<task_attr>``, started at startup and cancelled at shutdown.

    The shared loop of the grace-bounded control-plane policies (the orphan reaper, the
    unclaimed-run warner): each policy owns no task, and this is the one place the loop is
    written.

    INVARIANT: a failed sweep is logged with ``failure_message`` and the cadence continues — a
    policy whose loop died silently would LOOK like "nothing happened". `CancelledError` is a
    BaseException and still propagates, so shutdown is unaffected.
    """

    async def _sweep_forever() -> None:
        while True:
            await asyncio.sleep(tick_s)
            try:
                await sweep()
            except Exception:
                _logger.exception(failure_message)

    async def _start() -> None:
        setattr(app.state, task_attr, asyncio.get_running_loop().create_task(_sweep_forever()))
        on_start()

    async def _stop() -> None:
        task = getattr(app.state, task_attr)
        if task is not None:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

    app.router.on_startup.append(_start)
    app.router.on_shutdown.append(_stop)


def _install_unclaimed_run_warner(
    app: FastAPI,
    registry: ConnectionRegistry,
    job_runner: JobRunner | None,
    settings: Settings,
    clock: Clock,
) -> None:
    """Wire the unclaimed-run warner: one process-wide sweep that warns, once, each attached
    run still queued past `unclaimed_run_warn_s`.

    Same shape as `_install_orphan_reaper`: the policy object owns no task, and the loop is the
    shared `_install_periodic` — ONE task per App process, never one per run.

    WHY its own task and not a second call inside the reaper's loop: (1) the reaper's loop does
    not exist when `orphan_grace_s=0`, and an operator who turns reaping off must not also lose a
    client-visible notice without a sign; (2) the reaper's cadence derives from ITS grace, and
    two policies on one cadence is the "two knobs that disagree" shape `reaper.py` rejects;
    (3) the inputs differ — the reaper listens to audience edges, this polls the runner's
    accepted set.

    INVARIANT: handed the REAL `registry`, never `app.state.interest` — a gate that answers
    "someone is listening" for every topic would decide runs nobody can hear.
    """
    app.state.unclaimed_warner = None
    app.state.unclaimed_warner_task = None
    if not isinstance(job_runner, QueuedRuns) or settings.unclaimed_run_warn_s <= 0:
        # WHY structural: only a queue-backed runner has runs that WAIT (the in-process runner
        # starts at once), and it is the one that answers `accepted_ages()`. A stream-only App
        # and `URL4_CLOUD_UNCLAIMED_RUN_WARN_S=0` install nothing, and no task is created.
        return
    warner = UnclaimedRunWarner(
        job_runner, registry, grace_s=settings.unclaimed_run_warn_s, frame_clock=clock
    )
    app.state.unclaimed_warner = warner

    def _armed() -> None:
        # AIDEV-NOTE: the single-replica limit is LOGGED, like the reaper's. Only the replica that
        # scheduled a run remembers it (`accepted_ages` is in-process), and a notice reaches only
        # sockets attached to THAT replica — with more than one App replica, a client whose WS
        # lands elsewhere is simply never warned.
        _logger.info(
            "unclaimed-run warner armed grace_s=%.0f tick_s=%.0f (assumes a single replica)",
            settings.unclaimed_run_warn_s,
            warner.tick_s,
        )

    # INVARIANT: one failed sweep must not kill the warner — the notice is advisory, and a dead
    # loop would put every later client back on a silent 16h socket.
    _install_periodic(
        app,
        task_attr="unclaimed_warner_task",
        tick_s=warner.tick_s,
        sweep=warner.sweep,
        failure_message="unclaimed-run sweep failed; retrying next interval",
        on_start=_armed,
    )


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
        span_sink=control_plane_span_sink(os.environ),
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
    # into /openapi.json, and every call runs as a DIRECT run on the worker pool.
    install_mounts(
        app,
        lambda: derive_mount_table(env=os.environ, engine_routes=engine_route_paths(app)),
    )
    return app
