"""The node tier's own Prometheus registry and the three signals test-plan §9 names.

FEATURE (unit 3, prd/03): the observability the accepted risks need to be visible — the 504
rate and duration (R7) and the in-flight cap (R5). Served on its own port (FX-5, RD2), never on
the mount port.
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
        buckets=_DURATION_BUCKETS,
        registry=registry,
    )
    inflight = Gauge(
        "screamingface_engine_node_sync_inflight",
        "Sync requests inside the node tier, including shed ones.",
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


__all__ = ["NodeMetrics", "build_node_metrics"]
