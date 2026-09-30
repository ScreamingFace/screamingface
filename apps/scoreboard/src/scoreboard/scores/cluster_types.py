"""Value types, errors and two row helpers of the clustered submit.

FEATURE: OME-1307 (E14) — split out of `cluster_store` to keep each file at 450 lines or less.
`cluster_store` re-exports the public names, so importers keep `scores.cluster_store` as the path.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal
from uuid import UUID

from scoreboard.core.submissions.receipts import ReceiptClaims

from .models import Benchmark, ReportedResult, Score
from .schemas import ScoreSubmission, SubmitNotice

Kind = Literal["new_head", "reported_result", "replay_idempotent"]


@dataclass(frozen=True, slots=True)
class ClusterOutcome:
    head: Score
    result: ReportedResult | None  # None only for a legacy-key replay of a head with no original
    publication_state: str | None
    results_count: int
    notices: list[SubmitNotice]
    kind: Kind


@dataclass(frozen=True, slots=True)
class ReplayTarget:
    result: ReportedResult
    head: Score
    benchmark: Benchmark
    publication_state: str | None


class CacheVersionAlreadyBound(Exception):
    """The cache version of the receipt already belongs to another run (-> 409)."""


class InvalidReplayClaim(Exception):
    """The replay claim does not name a result the caller may replay (-> 422)."""


@dataclass(frozen=True, slots=True)
class _Call:
    """What one request decided at its single read of the board, kept together."""

    submission: ScoreSubmission
    per_submitter: bool
    identity_verified: bool
    stored_key: str | None  # the SCOPED idempotency key (OME-894)
    claims: ReceiptClaims | None


@dataclass(frozen=True, slots=True)
class _Placement:
    """Where a run goes: an existing head, or the fields of the head to insert."""

    head: Score | None
    submission: ScoreSubmission  # the submission to store as a NEW head
    system_revision_id: UUID | None
    metadata: dict[str, Any] | None  # set only on a private board (the server fingerprint)
    notices: list[SubmitNotice]


def _column(row: Any, name: str) -> Any:
    # WHY getattr: a native FK column `<attr>_id` (D8) is not a declared model attribute.
    return getattr(row, name)


def _revision_filter(rows: Any, revision: str | None) -> Any:
    # A NULL revision needs `__isnull`: `benchmark_revision=None` would compare with `= NULL`.
    if revision is None:
        return rows.filter(benchmark_revision__isnull=True)
    return rows.filter(benchmark_revision=revision)
