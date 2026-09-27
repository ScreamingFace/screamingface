"""Prometheus metrics for the worker (OME-1092): the pool's own observability.

The worker is a separate process from the App, so its metrics live on their own scrape
endpoint — `prometheus_client.start_http_server` on `worker_metrics_port` — not on the
App's `/metrics`. The chart exposes the port on the runner pool Deployment.

The metrics are the Observability section's list: slots busy and total, claim latency,
run duration, redelivery count, child exit codes (137 = OOM), worker restarts, and the
drain count. Cardinality is bounded: the only label is the child's exit code, which is
an integer.

LAYERING: this module imports `prometheus_client` and, for the publish-conflicts family,
`screamingface_engine.metrics` (the control plane's own module) — allowed one-way, per
`.claude/scripts/check_layering.py`: the worker may import a control-plane module; the reverse
is what the gate refuses.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram

from screamingface_engine.metrics import publish_conflicts_family

# The claim-latency buckets: a pull waits up to `PULL_TIMEOUT_S` (5s) for the first
# message, so the histogram must cover the whole wait.
_CLAIM_LATENCY_BUCKETS = (0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0)
# The run-duration buckets: a run is bounded by `job_deadline_s` (16h), and the worker's
# hard wall adds the stream grace + margin — the histogram covers the full range.
_RUN_DURATION_BUCKETS = (1, 5, 15, 60, 300, 900, 3600, 14400)
# The hand-off and boot buckets: a warm hand-off is milliseconds, a cold boot (Python start-up
# plus the imports) is seconds — the histogram shows both ends.
_HANDOFF_BUCKETS = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0)


@dataclass
class WorkerMetrics:
    """The worker's metric handles, created once per process on one registry."""

    registry: CollectorRegistry
    slots_busy: Gauge
    slots_total: Gauge
    last_claim_attempt: Gauge
    pull_failures_total: Counter
    claim_latency_s: Histogram
    run_duration_s: Histogram
    redeliveries: Counter
    cross_pod_duplicate_claims: Counter
    child_exit_codes: Counter
    warm_children: Gauge
    warm_spawn_failures: Counter
    handoff_latency_s: Histogram
    child_boot_s: Histogram
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
        last_claim_attempt=Gauge(
            "screamingface_engine_worker_last_claim_attempt_unix_seconds",
            "Unix time of the claim loop's last pull attempt — the loop-liveness signal. "
            "A wedged claim loop with a live scrape thread passes a /metrics liveness probe; "
            "this gauge stops advancing when the loop is stuck. Alert when it goes stale "
            "while slots_busy < slots_total and the queue has depth.",
            registry=registry,
        ),
        pull_failures_total=Counter(
            "screamingface_engine_worker_pull_failures_total",
            "Broker errors the claim loop caught and retried. The liveness stamp advances "
            "on every pull ATTEMPT, so a pull that keeps failing still looks alive — a "
            "rising counter is the operator's signal that the worker's broker path needs "
            "attention (V-5).",
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
        cross_pod_duplicate_claims=Counter(
            "screamingface_engine_worker_cross_pod_duplicate_claims_total",
            "Redelivered claims this worker acked away because the ownership probe "
            "(url4.runown.*) found the run still executing on ANOTHER pod (OME-1089). "
            "The in-process duplicate guard cannot see across pods, so at replicas > 1 "
            "this counter is the operator's only signal that the fleet is hitting the "
            "double-execution path — a rising count means the workers' broker path is "
            "dropping in_progress heartbeats for longer than ack_wait.",
            registry=registry,
        ),
        child_exit_codes=Counter(
            "screamingface_engine_worker_child_exit_codes_total",
            "Child process exit codes, labeled by code (137 = OOM).",
            ["code"],
            registry=registry,
        ),
        # The warm child pool (uniform executor PRD 03).
        warm_children=Gauge(
            "screamingface_engine_worker_warm_children",
            "Idle warm children ready to take a run.",
            registry=registry,
        ),
        warm_spawn_failures=Counter(
            "screamingface_engine_worker_warm_spawn_failures_total",
            "Warm children that failed to start, timed out before READY, or died idle.",
            registry=registry,
        ),
        handoff_latency_s=Histogram(
            "screamingface_engine_worker_handoff_latency_s",
            "Claim to the child's ACK of its run spec.",
            buckets=_HANDOFF_BUCKETS,
            registry=registry,
        ),
        child_boot_s=Histogram(
            "screamingface_engine_worker_child_boot_s",
            "Child spawn to its READY (the per-process work a warm child does ahead).",
            buckets=_HANDOFF_BUCKETS,
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


class _PublishConflictsCollector:
    """A `prometheus_client` custom collector for the worker's publisher's publish-conflict
    counter (uniform executor, PRD 01 §4 Observability, I-EV3).

    `JetStreamPublisher.publish_next` is how a non-child writer — here, the supervisor's own
    classification frame — appends onto a subject another writer may have just appended to;
    a `Nats-Expected-Last-Subject-Sequence` mismatch means it retried.

    WHY the publisher directly, and not a getter like the App-side collectors: those exist
    because `app.state.job_runner`/`app.state.stream` are read at scrape time off state that
    may not be wired yet at registration. The worker builds exactly ONE publisher for the life
    of the process (`worker_composition`) before this is ever registered, so there is nothing
    to defer — a getter here would only wrap a constant.
    """

    def __init__(self, publisher: Any) -> None:
        self._publisher = publisher

    def collect(self) -> Iterable[Any]:
        conflicts = getattr(self._publisher, "publish_conflicts", None)
        if conflicts is None:
            return
        yield publish_conflicts_family(conflicts)


def register_events_publish_conflicts_metrics(metrics: WorkerMetrics, publisher: Any) -> None:
    """Register a `_PublishConflictsCollector` for `publisher` on `metrics.registry`."""
    metrics.registry.register(_PublishConflictsCollector(publisher))


__all__ = [
    "WorkerMetrics",
    "build_worker_metrics",
    "register_events_publish_conflicts_metrics",
]
