"""The node tier's own Prometheus registry and the three signals test-plan §9 names.

FEATURE (unit 3, prd/03): the observability the accepted risks need to be visible — whether
the 30 s budget is too short (R7) and whether the in-flight cap is wrong (R5). Served on its own
port (FX-5, RD2), never on the mount port.
"""

from __future__ import annotations

from dataclasses import dataclass

from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram

# WHY buckets past 30 s (FX-7): the default buckets stop at 10 s, so every request that reached
# the 30 s budget fell into `+Inf` and the histogram could not show how close to the budget the
# slow requests ran. 35 s and 40 s cover the spill that runs after the budget (§2.2).
_DURATION_BUCKETS = (0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 15.0, 20.0, 25.0, 30.0, 35.0, 40.0)


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
    budget_exhausted: Counter


def build_node_metrics() -> NodeMetrics:
    """Build the node tier's registry.

    ``budget_exhausted`` is the R7 signal (§2.2b): it counts the requests whose budget ran out,
    whichever layer noticed — url4's ``504 timeout``, or the connector's ``502
    aigateway_deadline_exceeded`` when the deadline stopped an aigateway attempt first. The 504
    count alone is NOT that signal: with the deadline, a slow model usually ends as that 502.
    ``request_duration`` is labelled by the FINAL ``status``, so it shows how long each outcome
    took. ``inflight`` and ``shed`` answer whether the cap (R5) is wrong.
    """
    registry = CollectorRegistry()
    request_duration = Histogram(
        "screamingface_engine_node_sync_request_duration_seconds",
        "Duration of sync-surface requests handled by the node tier.",
        ["status"],
        buckets=_DURATION_BUCKETS,
        registry=registry,
    )
    inflight = Gauge(
        "screamingface_engine_node_sync_inflight",
        "Sync requests admitted by the node tier, spill phase included.",
        registry=registry,
    )
    shed = Counter(
        "screamingface_engine_node_sync_shed_total",
        "Sync requests shed with 503 overloaded because the node tier was at capacity.",
        registry=registry,
    )
    budget_exhausted = Counter(
        "screamingface_engine_node_sync_budget_exhausted_total",
        "Sync requests whose budget ran out: 504 timeout or 502 aigateway_deadline_exceeded.",
        registry=registry,
    )
    return NodeMetrics(
        registry=registry,
        request_duration=request_duration,
        inflight=inflight,
        shed=shed,
        budget_exhausted=budget_exhausted,
    )


__all__ = ["NodeMetrics", "build_node_metrics"]
