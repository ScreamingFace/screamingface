"""Prometheus metrics for the worker (OME-1092): the pool's own observability.

The worker is a separate process from the App, so its metrics live on their own scrape
endpoint — `prometheus_client.start_http_server` on `worker_metrics_port` — not on the
App's `/metrics`. The chart exposes the port on the runner pool Deployment.

The metrics are the Observability section's list: slots busy and total, claim latency,
run duration, redelivery count, child exit codes (137 = OOM), worker restarts, and the
drain count. Cardinality is bounded: the only label is the child's exit code, which is
an integer.

LAYERING: this module imports only `prometheus_client` — a serving-half dependency the
worker may already import — so it stays a shared leaf under `.claude/scripts/check_layering.py`.
"""

from __future__ import annotations

from dataclasses import dataclass

from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram

# The claim-latency buckets: a pull waits up to `PULL_TIMEOUT_S` (5s) for the first
# message, so the histogram must cover the whole wait.
_CLAIM_LATENCY_BUCKETS = (0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0)
# The run-duration buckets: a run is bounded by `job_deadline_s` (16h), and the worker's
# hard wall adds the stream grace + margin — the histogram covers the full range.
_RUN_DURATION_BUCKETS = (1, 5, 15, 60, 300, 900, 3600, 14400)


@dataclass
class WorkerMetrics:
    """The worker's metric handles, created once per process on one registry."""

    registry: CollectorRegistry
    slots_busy: Gauge
    slots_total: Gauge
    claim_latency_s: Histogram
    run_duration_s: Histogram
    redeliveries: Counter
    child_exit_codes: Counter
    started: Counter
    drains: Counter


def build_worker_metrics() -> WorkerMetrics:
    """Build the worker's metrics on a fresh registry.

    WHY a per-process registry rather than the global default: the worker is one process,
    but tests construct `Worker` many times — a shared registry would collide on duplicate
    registration. `run_worker` hands the same registry to `start_http_server`.
    """
    registry = CollectorRegistry()
    return WorkerMetrics(
        registry=registry,
        slots_busy=Gauge(
            "screamingface_engine_worker_slots_busy",
            "Run slots currently in use by this worker.",
            registry=registry,
        ),
        slots_total=Gauge(
            "screamingface_engine_worker_slots_total",
            "Run slots this worker has (run_queue_worker_slots).",
            registry=registry,
        ),
        claim_latency_s=Histogram(
            "screamingface_engine_worker_claim_latency_s",
            "Seconds a pull took to return a claimed message.",
            buckets=_CLAIM_LATENCY_BUCKETS,
            registry=registry,
        ),
        run_duration_s=Histogram(
            "screamingface_engine_worker_run_duration_s",
            "Seconds one supervised run took from claim to ack.",
            buckets=_RUN_DURATION_BUCKETS,
            registry=registry,
        ),
        redeliveries=Counter(
            "screamingface_engine_worker_redeliveries_total",
            "Claimed messages that had been redelivered at least once.",
            registry=registry,
        ),
        child_exit_codes=Counter(
            "screamingface_engine_worker_child_exit_codes_total",
            "Child process exit codes, labeled by code (137 = OOM).",
            ["code"],
            registry=registry,
        ),
        started=Counter(
            "screamingface_engine_worker_started_total",
            "Worker process starts — the in-process half of the restart signal.",
            registry=registry,
        ),
        drains=Counter(
            "screamingface_engine_worker_drains_total",
            "Drain events (SIGTERM received, stopped pulling).",
            registry=registry,
        ),
    )


__all__ = ["WorkerMetrics", "build_worker_metrics"]
