"""Per-app counters of the clustered submit (E14, OME-1307).

WHY a per-instance `CollectorRegistry`: several `create_app()` calls (across tests) would otherwise
collide on duplicate registration in the global default registry. Same reason as
`apps/screamingface-engine/src/screamingface_engine/metrics.py`.

INVARIANT (D7 X-15): the counters stay in process. There is no exporter and no `/metrics` route.
SB-grants and SB-publish add their counters to `Metrics`.
"""

from __future__ import annotations

from dataclasses import dataclass

from prometheus_client import CollectorRegistry, Counter


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
    return Metrics(
        registry=registry,
        submits=submits,
        receipt_rejections=receipt_rejections,
        replay_grants=replay_grants,
    )
