"""Adapter-side rules of the clustered submit: they read the pydantic request models.

FEATURE: OME-1307 (E14).

WHY not in `core/`: importing `scoreboard.scores.schemas` runs `scoreboard/scores/__init__.py`,
which imports `store.py` and so Tortoise. The pure rules that need only primitive values live in
`core/submissions/clustering.py`.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any, cast
from uuid import UUID

from scoreboard.core.registry import SystemAlreadyNamed
from scoreboard.core.submissions.clustering import result_labels
from scoreboard.core.submissions.receipts import ReceiptClaims, receipt_columns

from .cluster_types import _column
from .models import ReportedResult
from .schemas import (
    CacheVersionSummary,
    ReplayClaim,
    ReplayProvenance,
    ReportedResultSchema,
    ScoreSubmission,
    SubmitNotice,
)
from .store import _derived_providers, _resolve_benchmark_revision


def cluster_revision(submission: ScoreSubmission) -> str | None:
    """INVARIANT (SC-D4): the RESOLVED revision (`store._resolve_benchmark_revision`), never the
    raw metadata value when a typed value exists."""
    return _resolve_benchmark_revision(submission)


@dataclass(frozen=True, slots=True)
class ResultFields:
    reporter: str | None
    run_id: str | None
    trace_id: str | None
    score: float
    total_questions: int
    correct_questions: int | None
    run_cost_usd: Decimal | None
    run_cost_status: str | None
    cache_saved_cost_usd: Decimal | None
    models: list[str] | None
    ran_with_providers: list[str]
    answer_seed: int | None
    client_name: str | None
    client_version: str | None
    client_platform: str | None
    receipt: dict[str, object]
    replay: dict[str, object]


def replay_columns(replay: ReplayClaim | None) -> dict[str, object]:
    """I-R2: the five replay columns, all set from the claim or all None. Stored as reported."""
    if replay is None:
        return {
            "replayed_from_result_id": None,
            "replay_hits": None,
            "replay_misses": None,
            "pinned_baseline_result_id": None,
            "replay_repeated_key_collapses": None,
        }
    return {
        "replayed_from_result_id": replay.result_id,
        "replay_hits": replay.hits,
        "replay_misses": replay.misses,
        "pinned_baseline_result_id": replay.pinned_baseline_result_id,
        "replay_repeated_key_collapses": replay.repeated_key_collapses,
    }


def result_fields(
    submission: ScoreSubmission, *, run_id: str | None, claims: ReceiptClaims | None
) -> ResultFields:
    """The columns of one result, from the request and the VERIFIED receipt only.

    INVARIANT: only the receipt sets the five cache columns (C4 security): no client value about
    versions is read. `answer_seed` is NULL (spec gap G5, decided (default)).
    """
    client = submission.client
    return ResultFields(
        reporter=submission.submitted_by,
        run_id=run_id,
        trace_id=submission.trace_id,
        score=submission.score,
        total_questions=submission.total_questions,
        correct_questions=submission.correct_questions,
        run_cost_usd=submission.run_cost_usd,
        run_cost_status=submission.run_cost_status,
        cache_saved_cost_usd=submission.cache_saved_cost_usd,
        models=submission.models,
        ran_with_providers=_derived_providers(submission),
        answer_seed=None,
        client_name=client.name if client else None,
        client_version=client.version if client else None,
        client_platform=client.platform if client else None,
        receipt=receipt_columns(claims),
        replay=replay_columns(submission.replay),
    )


def _cache_version(rr: ReportedResult) -> CacheVersionSummary | None:
    if rr.cache_version_id is None:
        return None
    return CacheVersionSummary(
        id=rr.cache_version_id,
        sha256=cast(str, rr.cache_version_sha256),
        entry_count=cast(int, rr.cache_entry_count),
        call_count=cast(int, rr.cache_call_count),
        coverage_status=cast(Any, rr.cache_coverage_status),
    )


def _replay(rr: ReportedResult) -> ReplayProvenance | None:
    source = _column(rr, "replayed_from_result_id")
    if source is None:
        return None
    return ReplayProvenance(
        replayed_from_result_id=source,
        hits=cast(int, rr.replay_hits),
        misses=cast(int, rr.replay_misses),
        pinned_baseline_result_id=_column(rr, "pinned_baseline_result_id"),
        # WHY explicit although it is the default: the submit route answers with
        # `response_model_exclude_unset=True`, which would drop an unset default (C4 trust rule).
        reported_by="client",
    )


def result_schema(rr: ReportedResult, publication_state: str | None) -> ReportedResultSchema:
    """The ONE place a `ReportedResult` becomes its DTO (the submit answer and the results list)."""
    return ReportedResultSchema(
        id=rr.id,
        score_id=_column(rr, "head_id"),
        is_original=rr.is_original,
        reporter=rr.reporter,
        submitted_at=rr.submitted_at,
        score=rr.score,
        total_questions=rr.total_questions,
        correct_questions=rr.correct_questions,
        models=cast("list[str] | None", rr.models),
        run_cost_usd=rr.run_cost_usd,
        run_cost_status=cast(Any, rr.run_cost_status),
        cache_saved_cost_usd=rr.cache_saved_cost_usd,
        cache_version=_cache_version(rr),
        publication_state=cast(Any, publication_state),
        replay=_replay(rr),
        labels=result_labels(
            coverage_status=rr.cache_coverage_status,
            entry_count=rr.cache_entry_count,
            call_count=rr.cache_call_count,
            replayed_from_result_id=_column(rr, "replayed_from_result_id"),
            replay_hits=rr.replay_hits,
            replay_misses=rr.replay_misses,
        ),
    )


def clustered_notice(score_id: UUID) -> SubmitNotice:
    return SubmitNotice(code="clustered_under", score_id=score_id)


def named_notice(notice: SystemAlreadyNamed) -> SubmitNotice:
    return SubmitNotice(code="system_already_named", name=notice.name, owner=notice.owner)
