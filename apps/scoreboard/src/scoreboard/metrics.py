"""Per-app counters of the clustered submit (E14, OME-1307).

WHY a per-instance `CollectorRegistry`: several `create_app()` calls (across tests) would otherwise
collide on duplicate registration in the global default registry. Same reason as
`apps/screamingface-engine/src/screamingface_engine/metrics.py`.

INVARIANT (D7 X-15): the counters stay in process. There is no exporter and no `/metrics` route.
SB-grants and SB-publish add their counters to `Metrics`.
"""

from __future__ import annotations

from dataclasses import dataclass

from prometheus_client import CollectorRegistry, Counter, Gauge


@dataclass(frozen=True)
class Metrics:
    registry: CollectorRegistry
    # scoreboard_submits_total{kind}: kind is new_head | reported_result | replay_idempotent.
    submits: Counter
    # scoreboard_receipt_rejections_total{reason}: a RejectReason, or not_yours | already_bound.
    receipt_rejections: Counter
    # FEATURE: OME-1307 (E14) replay grants.
    # scoreboard_replay_grants_total{result}: issued | not_found | withdrawn | mismatch | invalid |
    # unavailable | unauthenticated.
    replay_grants: Counter
    # FEATURE: OME-1307 (E14) publish and takedown (SB-publish).
    # scoreboard_publish_attempts_total{result}: result is ok | retry | error.
    publish_attempts: Counter
    # scoreboard_publish_integrity_failures_total: archive missing, digest mismatch, release
    # conflict. Any increase is an alert (DEPLOYMENT.md).
    publish_integrity_failures: Counter
    # scoreboard_publish_jobs{state}: publication rows by state.
    publish_jobs: Gauge
    # scoreboard_withdraw_cleanup_pending: withdrawn rows whose release delete has been pending
    # for more than one hour.
    withdraw_cleanup_pending: Gauge


def build_metrics() -> Metrics:
    registry = CollectorRegistry()
    submits = Counter(
        "scoreboard_submits",
        "Clustered submits answered, by what they did.",
        ["kind"],
        registry=registry,
    )
    receipt_rejections = Counter(
        "scoreboard_receipt_rejections",
        "Cache-version receipts refused, by reason.",
        ["reason"],
        registry=registry,
    )
    # FEATURE: OME-1307 (E14) replay grants.
    replay_grants = Counter(
        "scoreboard_replay_grants",
        "Replay grant requests answered, by result.",
        ["result"],
        registry=registry,
    )
    publish_attempts = Counter(
        "scoreboard_publish_attempts",
        "Publish worker attempts, by result.",
        ["result"],
        registry=registry,
    )
    publish_integrity_failures = Counter(
        "scoreboard_publish_integrity_failures",
        "Publish jobs stopped by an archive or release integrity failure.",
        registry=registry,
    )
    publish_jobs = Gauge(
        "scoreboard_publish_jobs",
        "Publication rows, by state.",
        ["state"],
        registry=registry,
    )
    withdraw_cleanup_pending = Gauge(
        "scoreboard_withdraw_cleanup_pending",
        "Withdrawn publications whose GitHub release delete is pending for more than 1 hour.",
        registry=registry,
    )
    return Metrics(
        registry=registry,
        submits=submits,
        receipt_rejections=receipt_rejections,
        replay_grants=replay_grants,
        publish_attempts=publish_attempts,
        publish_integrity_failures=publish_integrity_failures,
        publish_jobs=publish_jobs,
        withdraw_cleanup_pending=withdraw_cleanup_pending,
    )
