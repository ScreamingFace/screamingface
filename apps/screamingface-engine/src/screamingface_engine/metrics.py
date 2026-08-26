"""Prometheus/OpenMetrics wiring for the screamingface-engine App: a per-request
counter middleware and a custom collector that surfaces the model-catalog cache
counters at scrape time."""

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any

from prometheus_client import CollectorRegistry, Counter
from prometheus_client.core import CounterMetricFamily, GaugeMetricFamily
from starlette.types import ASGIApp, Message, Receive, Scope, Send


@dataclass(frozen=True)
class Metrics:
    """The App's private Prometheus registry and metric handles, held on `app.state.metrics`.

    Uses a per-instance `CollectorRegistry` rather than the global default one so multiple
    `create_app()` calls (e.g. across tests) don't collide on duplicate metric registration.
    """

    registry: CollectorRegistry
    requests: Counter


# The `path` label value used when a request matched no route. Every unrouted request — a 404, a
# probe for `/wp-login.php`, an asset under a mounted sub-app — collapses onto this one string.
UNMATCHED_PATH = "<unmatched>"


def build_metrics() -> Metrics:
    registry = CollectorRegistry()
    requests = Counter(
        "screamingface_engine_requests",
        "HTTP requests handled by the screamingface-engine control plane.",
        ["method", "path", "status"],
        registry=registry,
    )
    return Metrics(registry=registry, requests=requests)


class MetricsMiddleware:
    """ASGI middleware that increments `Metrics.requests`, labeled by method/route/status, for
    every HTTP response the App sends."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        method = str(scope.get("method", "GET"))

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                metrics = _metrics_of(scope)
                if metrics is not None:
                    status = str(message.get("status", 0))
                    # WHY the label is read here and not before `self.app(...)`: routing happens
                    # inside the app, so `scope["route"]` only exists once a response starts.
                    metrics.requests.labels(
                        method=method, path=_route_label(scope), status=status
                    ).inc()
            await send(message)

        await self.app(scope, receive, send_wrapper)


def _route_label(scope: Scope) -> str:
    """The matched route's template (`/v1/models`, `/runs/{run_id}`), never the raw request path.

    INVARIANT: the returned value comes from a finite set — one entry per registered route, plus
    `UNMATCHED_PATH`. This is what bounds the `requests` counter's cardinality. Labeling with
    `scope["path"]` instead would let any unauthenticated caller mint an unbounded number of
    permanent Counter children (`GET /aaaa1`, `/aaaa2`, ...) and exhaust the process's memory;
    `POST /token` needs no credential, so nothing upstream stops them reaching this middleware.

    FastAPI's `APIRoute.matches` puts the matched route on the scope, which is the cheap path.
    Plain Starlette routes and `Mount`s (the `/diagrams` static assets) do not, so those are
    resolved by asking the router itself; anything still unmatched is a genuine 404.
    """
    path_format = getattr(scope.get("route"), "path_format", None)
    if isinstance(path_format, str) and path_format:
        return path_format
    return _match_against_router(scope)


def _match_against_router(scope: Scope) -> str:
    """Resolve the route template by re-running the router's own matching.

    Bounded by the number of registered routes, and only reached when the framework did not
    already record the match. Deliberately uses `route.matches` rather than reimplementing path
    matching, so this can never disagree with where the request was actually dispatched.
    """
    routes = getattr(scope.get("app"), "routes", None) or ()
    for route in routes:
        matches = getattr(route, "matches", None)
        path_format = getattr(route, "path_format", None)
        if matches is None or not isinstance(path_format, str) or not path_format:
            continue
        try:
            match, _ = matches(scope)
        except Exception:  # a route that cannot answer is simply not the match
            continue
        if getattr(match, "name", "") == "FULL":
            return path_format
    return UNMATCHED_PATH


def _metrics_of(scope: Scope) -> Metrics | None:
    """Best-effort lookup of `Metrics` off the ASGI scope's app state; None if unset or the wrong
    type (e.g. a bare test double without `create_app`'s wiring)."""
    app = scope.get("app")
    state = getattr(app, "state", None)
    metrics = getattr(state, "metrics", None)
    return metrics if isinstance(metrics, Metrics) else None


class _CatalogCollector:
    """A `prometheus_client` custom collector that exposes the catalog service's cache counters."""

    def __init__(self, get_service: Callable[[], Any]) -> None:
        self._get_service = get_service

    def collect(self) -> Iterable[Any]:
        """Called by `prometheus_client` once per `/metrics` scrape."""
        service = self._get_service()
        counters = getattr(service, "counters", None)
        if counters is None:
            return
        yield CounterMetricFamily(
            "screamingface_engine_catalog_cache_hits",
            "Catalog served from a fresh cache entry.",
            value=counters.hits,
        )
        yield CounterMetricFamily(
            "screamingface_engine_catalog_cache_misses",
            "Catalog fetched from aigateway.",
            value=counters.misses,
        )
        yield CounterMetricFamily(
            "screamingface_engine_catalog_stale_serves",
            "Stale catalog served because a refresh failed.",
            value=counters.stale_serves,
        )
        yield CounterMetricFamily(
            "screamingface_engine_catalog_errors",
            "Upstream catalog fetches that failed.",
            value=counters.errors,
        )
        yield CounterMetricFamily(
            "screamingface_engine_catalog_bulkhead_waits",
            "Catalog fetches that waited on the upstream concurrency bulkhead.",
            value=counters.bulkhead_waits,
        )
        yield GaugeMetricFamily(
            "screamingface_engine_catalog_entries",
            "Cached catalog entries currently held.",
            value=float(getattr(service, "entry_count", 0)),
        )


def register_catalog_metrics(metrics: Metrics, get_service: Callable[[], Any]) -> None:
    """Register a `_CatalogCollector` for `get_service` on `metrics.registry`."""
    metrics.registry.register(_CatalogCollector(get_service))


class _ReaperCollector:
    """A `prometheus_client` custom collector for the orphan reaper's counters (OME-890)."""

    def __init__(self, get_reaper: Callable[[], Any]) -> None:
        self._get_reaper = get_reaper

    def collect(self) -> Iterable[Any]:
        """Called by `prometheus_client` once per `/metrics` scrape."""
        reaper = self._get_reaper()
        if reaper is None:
            return
        yield CounterMetricFamily(
            "screamingface_engine_orphan_runs_reaped",
            "Runs stopped for having no WebSocket subscriber.",
            value=reaper.reaped_total,
        )
        # WHY a gauge beside the counter: a value that never returns to zero is the only signal
        # that distinguishes "the sweep task died" from "no orphans happened" — the counter reads
        # identically in both cases.
        yield GaugeMetricFamily(
            "screamingface_engine_orphan_runs_armed",
            "Runs currently inside their no-subscriber grace window.",
            value=float(reaper.armed_count),
        )


def register_reaper_metrics(metrics: Metrics, get_reaper: Callable[[], Any]) -> None:
    """Register a `_ReaperCollector` for `get_reaper` on `metrics.registry`."""
    metrics.registry.register(_ReaperCollector(get_reaper))


class _FairShareCollector:
    """A `prometheus_client` custom collector for the local fair-share gate (OME-908).

    WHY no per-run labels: topics are unbounded and attacker-mintable (`POST /token` needs no
    credential), so labeling by run would let anyone mint permanent gauge children — the same
    cardinality discipline `_route_label` enforces for the request counter. The snapshot carries
    per-run detail for tests and logs; the scrape surface stays totals-only.
    """

    def __init__(self, get_gate: Callable[[], Any]) -> None:
        self._get_gate = get_gate

    def collect(self) -> Iterable[Any]:
        gate = self._get_gate()
        if gate is None:
            return
        snapshot = gate.snapshot()
        yield CounterMetricFamily(
            "screamingface_engine_fair_share_granted_total",
            "Downstream fetch permits the local fair-share gate has granted.",
            value=snapshot.granted_total,
        )
        yield GaugeMetricFamily(
            "screamingface_engine_fair_share_in_flight",
            "Downstream fetch permits currently held by local runs.",
            value=float(snapshot.in_flight),
        )
        yield GaugeMetricFamily(
            "screamingface_engine_fair_share_waiting",
            "Local-run fetches currently queued for a fair-share permit.",
            value=float(sum(entry.waiting for entry in snapshot.runs)),
        )
        yield GaugeMetricFamily(
            "screamingface_engine_fair_share_active_runs",
            "Local runs currently holding or waiting on fair-share permits.",
            value=float(len(snapshot.runs)),
        )


def register_fair_share_metrics(metrics: Metrics, get_gate: Callable[[], Any]) -> None:
    """Register a `_FairShareCollector` for `get_gate` on `metrics.registry`."""
    metrics.registry.register(_FairShareCollector(get_gate))
